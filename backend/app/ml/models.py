"""Immutable, versioned embedding storage; writing model outputs is a learning exercise."""

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
    cast,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import utcnow


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"
    __table_args__ = (
        UniqueConstraint("version", "dimension"),
        CheckConstraint("dimension BETWEEN 1 AND 2000", name="supported_dimension"),
    )
    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    dimension: Mapped[int] = mapped_column(Integer)
    architecture: Mapped[str] = mapped_column(String(100))
    checkpoint: Mapped[str] = mapped_column(String(200))
    weights_sha256: Mapped[str] = mapped_column(String(64))
    preprocess_version: Mapped[str] = mapped_column(String(100))
    text_policy: Mapped[str] = mapped_column(String(100))
    image_weight: Mapped[float] = mapped_column()
    library_versions: Mapped[dict] = mapped_column(JSON)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PinEmbedding(Base):
    __tablename__ = "pin_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["embedder_version", "dimension"],
            ["embedding_models.version", "embedding_models.dimension"],
            ondelete="CASCADE",
        ),
        CheckConstraint("vector_dims(embedding) = dimension", name="matching_dimension"),
        CheckConstraint("abs(vector_norm(embedding) - 1) < 0.0001", name="unit_vector"),
    )
    pin_id: Mapped[str] = mapped_column(ForeignKey("pins.id", ondelete="CASCADE"), primary_key=True)
    embedder_version: Mapped[str] = mapped_column(String(100), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[int] = mapped_column(Integer)
    # Unbounded type permits new dimensions; ANN indexes must be per model/version/dimension.
    embedding: Mapped[list[float]] = mapped_column(VECTOR())
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# The shipped image-only recipe has one schema-managed fixed-dimension partial index.
Index(
    "ix_lens_clip_hnsw",
    cast(PinEmbedding.embedding, VECTOR(512)).label("embedding"),
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_where=and_(
        PinEmbedding.embedder_version == "embedder:clip-image-crop:v1",
        PinEmbedding.dimension == 512,
    ),
)
