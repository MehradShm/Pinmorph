"""Explicit catalog backfill; the API never downloads weights on a request."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.discovery.crop import CropBox, prepare_crop
from app.ml.vector_store import store_image_embedding
from app.models import Pin
from app.product.safety import pixel_hash
from app.storage import make_s3_client


def main():
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    count = 0
    try:
        with Session(engine) as db:
            for pin in db.scalars(select(Pin).where(Pin.status == "ready").order_by(Pin.id)):
                response = storage.get_object(Bucket=settings.s3_bucket, Key=pin.original_key)
                try:
                    data = response["Body"].read(settings.upload_max_bytes + 1)
                finally:
                    response["Body"].close()
                crop = prepare_crop(data, CropBox(), settings)
                store_image_embedding(db, pin, crop.image_bytes, settings)
                pin.pixel_hash = pixel_hash(data)
                db.commit()
                count += 1
        print(json.dumps({"indexed_ready_pins": count}))
    finally:
        storage.close()
        engine.dispose()


if __name__ == "__main__":
    main()
