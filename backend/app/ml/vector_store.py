"""Immutable image-only catalog recipe and version-specific HNSW index."""

import hashlib

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.feed.contracts import FeedContext
from app.ml.config import EmbeddingConfig
from app.ml.contracts import Embedding, PinContent, VectorItem
from app.ml.embeddings import ClipPinEmbedder
from app.ml.models import EmbeddingModel, PinEmbedding
from app.models import Pin, User, utcnow
from app.product.models import HiddenPin
from app.social.policy import visible_owner

CLIP_VERSION = "embedder:clip-image-crop:v1"
CLIP_SHA = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"


def runtime_info(settings: Settings):
    with httpx.Client(timeout=90, trust_env=False) as client:
        response = client.get(settings.lens_endpoint + "/health")
        response.raise_for_status()
        info = response.json()
    if (
        info["version"] != CLIP_VERSION
        or info["weights_sha256"] != CLIP_SHA
        or info["dimension"] != 512
    ):
        raise ValueError("Lens runtime does not match pinned model")
    return info


def encode_image(data: bytes, settings: Settings) -> Embedding:
    with httpx.Client(timeout=90, trust_env=False) as client:
        response = client.post(
            settings.lens_endpoint + "/encode", files={"image": ("crop.png", data, "image/png")}
        )
        response.raise_for_status()
        embedding = Embedding.model_validate(response.json())
    if embedding.embedder_version != CLIP_VERSION or embedding.dimension != 512:
        raise ValueError("Incompatible encoder response")
    return embedding


def register_model(db: Session, info: dict):
    db.execute(text("SELECT pg_advisory_xact_lock(442041)"))
    model = db.get(EmbeddingModel, CLIP_VERSION)
    if model:
        if model.weights_sha256 != CLIP_SHA or model.image_weight != 1 or model.dimension != 512:
            raise ValueError("Immutable embedding recipe changed")
        return
    db.add(
        EmbeddingModel(
            version=CLIP_VERSION,
            dimension=512,
            architecture="ViT-B/32",
            checkpoint="openai:ViT-B-32",
            weights_sha256=CLIP_SHA,
            preprocess_version=info["preprocess_version"],
            text_policy="image_only:v1",
            image_weight=1.0,
            library_versions=info["library_versions"],
        )
    )
    db.flush()
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_lens_clip_hnsw ON pin_embeddings "
            "USING hnsw ((embedding::vector(512)) vector_cosine_ops) "
            "WHERE embedder_version = 'embedder:clip-image-crop:v1' AND dimension = 512"
        )
    )


def store_image_embedding(db: Session, pin: Pin, data: bytes, settings: Settings):
    digest = hashlib.sha256(data).hexdigest()
    identity = (pin.id, CLIP_VERSION, digest)
    if db.get(PinEmbedding, identity):
        return
    embedding = encode_image(data, settings)
    register_model(db, runtime_info(settings))
    db.add(
        PinEmbedding(
            pin_id=pin.id,
            embedder_version=CLIP_VERSION,
            content_hash=digest,
            dimension=512,
            embedding=list(embedding.values),
            known_at=utcnow(),
        )
    )
    db.flush()


def store_content_embedding(db: Session, pin: Pin, data: bytes, settings: Settings):
    config = EmbeddingConfig()
    # Length prefix makes the exact title/pixel boundary unambiguous.
    title = pin.title.encode("utf-8")
    digest = hashlib.sha256(len(title).to_bytes(8, "big") + title + data).hexdigest()
    db.execute(text("SELECT pg_advisory_xact_lock(442043)"))
    identity = (pin.id, config.version, digest)
    if db.get(PinEmbedding, identity):
        return False
    encoder = ClipPinEmbedder(config, settings.lens_endpoint)
    metadata = encoder.metadata()
    model = db.get(EmbeddingModel, config.version)
    fields = {
        name: metadata[name]
        for name in (
            "dimension",
            "architecture",
            "checkpoint",
            "weights_sha256",
            "preprocess_version",
            "text_policy",
            "image_weight",
            "library_versions",
        )
    }
    if model:
        if any(getattr(model, name) != value for name, value in fields.items()):
            raise ValueError("Immutable content embedding recipe changed")
    else:
        db.add(EmbeddingModel(version=config.version, **fields))
        db.flush()
    vector = encoder.embed(
        [
            PinContent(
                pin_id=pin.id,
                title=pin.title,
                image_bytes=data,
                content_hash=digest,
            )
        ]
    )[0]
    db.add(
        PinEmbedding(
            pin_id=pin.id,
            embedder_version=config.version,
            content_hash=digest,
            dimension=vector.dimension,
            embedding=list(vector.values),
            known_at=utcnow(),
        )
    )
    db.flush()
    return True


def catalog_vectors(db: Session, version: str, context: FeedContext) -> list[VectorItem]:
    viewer = db.get(User, context.user_id)
    hidden = select(HiddenPin.pin_id).where(HiddenPin.user_id == context.user_id)
    rows = db.execute(
        select(Pin, PinEmbedding)
        .join(PinEmbedding, PinEmbedding.pin_id == Pin.id)
        .where(
            Pin.status == "ready",
            Pin.available_at <= context.as_of,
            Pin.created_at <= context.as_of,
            PinEmbedding.embedder_version == version,
            PinEmbedding.known_at <= context.as_of,
            visible_owner(Pin.owner_id, viewer, include_muted=True),
            Pin.id.not_in(hidden),
        )
        .order_by(Pin.id, PinEmbedding.known_at.desc(), PinEmbedding.content_hash.desc())
    ).all()
    seen = set()
    items = []
    for pin, row in rows:
        if pin.id in seen:
            continue
        seen.add(pin.id)
        items.append(
            VectorItem(
                pin_id=pin.id,
                available_at=pin.available_at,
                known_at=row.known_at,
                embedding=Embedding(embedder_version=version, values=tuple(row.embedding)),
            )
        )
    return items
