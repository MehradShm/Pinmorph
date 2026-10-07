"""The API validates uploads; workers create immutable, metadata-free JPEG variants."""

import io
import json
import logging
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from rq import Queue, Retry, get_current_job
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import Pin, new_id
from app.storage import make_s3_client

logger = logging.getLogger("pinmorph.media")
VARIANT_SIZES = {"thumb": 400, "display": 1200}


class InvalidImage(ValueError):
    pass


def validate_image(data: bytes, settings: Settings) -> tuple[int, int]:
    if not data or len(data) > settings.upload_max_bytes:
        raise InvalidImage("Image must be between 1 byte and 12 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise InvalidImage("Use a JPEG, PNG, or WebP image")
                if image.width * image.height > settings.image_max_pixels:
                    raise InvalidImage("Image exceeds the 24 megapixel limit")
                if getattr(image, "n_frames", 1) != 1:
                    raise InvalidImage("Animated images are not supported")
                size = image.size
                image.verify()
            # verify() checks container structure; decoding also rejects truncated pixel data.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return size
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise InvalidImage("The file is not a valid image") from exc


def build_variants(data: bytes, settings: Settings) -> tuple[dict, int, int, str]:
    validate_image(data, settings)
    with Image.open(io.BytesIO(data)) as source:
        oriented = ImageOps.exif_transpose(source)
        # Flatten transparency on white and strip EXIF/GPS by constructing a new RGB image.
        rgba = oriented.convert("RGBA")
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
        sample = image.copy()
        sample.thumbnail((64, 64))
        palette = sample.quantize(colors=8)
        _, dominant_index = max(palette.getcolors(), key=lambda entry: entry[0])
        rgb = palette.getpalette()[dominant_index * 3 : dominant_index * 3 + 3]
        color = "#" + "".join(f"{channel:02x}" for channel in rgb)
        variants = {}
        for name, size in VARIANT_SIZES.items():
            variant = image.copy()
            variant.thumbnail((size, size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            variant.save(output, format="JPEG", quality=85, optimize=True)
            variants[name] = {
                "data": output.getvalue(),
                "width": variant.width,
                "height": variant.height,
            }
        return variants, image.width, image.height, color


def enqueue_pin(db: Session, queue: Queue, pin: Pin, request_id: str | None = None):
    job_id = f"media-{new_id()}"
    pin.status = "queued"
    pin.processing_error = None
    pin.media_job_id = job_id
    db.commit()
    try:
        return queue.enqueue(
            process_pin,
            pin.id,
            request_id,
            job_id=job_id,
            job_timeout=120,
            result_ttl=3600,
            failure_ttl=86400,
            retry=Retry(max=3, interval=[2, 5, 10]),
        )
    except Exception:
        pin.status = "failed"
        pin.processing_error = "QueueUnavailable"
        db.commit()
        raise


def process_pin(pin_id: str, request_id: str | None = None) -> str:
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    job = get_current_job()
    try:
        with Session(engine) as db:
            pin = db.get(Pin, pin_id)
            if pin is None:
                return "missing"
            if job and pin.media_job_id != job.id:
                return "superseded"
            if pin.status == "ready":
                return "ready"
            pin.status = "processing"
            db.commit()
            try:
                result = storage.get_object(Bucket=settings.s3_bucket, Key=pin.original_key)
                try:
                    data = result["Body"].read(settings.upload_max_bytes + 1)
                finally:
                    result["Body"].close()
                variants, width, height, color = build_variants(data, settings)
                metadata = {}
                for name, variant in variants.items():
                    key = f"pins/{pin.id}/{name}.jpg"
                    storage.put_object(
                        Bucket=settings.s3_bucket,
                        Key=key,
                        Body=variant["data"],
                        ContentType="image/jpeg",
                    )
                    metadata[name] = {
                        "key": key,
                        "width": variant["width"],
                        "height": variant["height"],
                    }
                # Re-check after work: a newer manual retry must not be overwritten.
                db.refresh(pin)
                if job and pin.media_job_id != job.id:
                    return "superseded"
                pin.width, pin.height, pin.dominant_color = width, height, color
                pin.variants, pin.status, pin.processing_error = metadata, "ready", None
                db.commit()
                logger.info(
                    json.dumps(
                        {
                            "event": "media_ready",
                            "pin_id": pin_id,
                            "request_id": request_id,
                            "job_id": job.id if job else None,
                        }
                    )
                )
                return "ready"
            except Exception as exc:
                db.rollback()
                db.refresh(pin)
                if not job or pin.media_job_id == job.id:
                    pin.status = "failed"
                    pin.processing_error = type(exc).__name__
                    db.commit()
                logger.error(
                    json.dumps(
                        {
                            "event": "media_failed",
                            "pin_id": pin_id,
                            "request_id": request_id,
                            "error_type": type(exc).__name__,
                            "job_id": job.id if job else None,
                        }
                    )
                )
                raise
    finally:
        storage.close()
        engine.dispose()
