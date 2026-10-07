"""Phase 3A versioned pin embeddings

Revision ID: cdfce4ed4eea
Revises: ddac47bcc846
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision = "cdfce4ed4eea"
down_revision = "ddac47bcc846"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_models",
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("architecture", sa.String(length=100), nullable=False),
        sa.Column("checkpoint", sa.String(length=200), nullable=False),
        sa.Column("weights_sha256", sa.String(length=64), nullable=False),
        sa.Column("preprocess_version", sa.String(length=100), nullable=False),
        sa.Column("text_policy", sa.String(length=100), nullable=False),
        sa.Column("image_weight", sa.Double(), nullable=False),
        sa.Column("library_versions", sa.JSON(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dimension BETWEEN 1 AND 2000", name=op.f("ck_embedding_models_supported_dimension")
        ),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_embedding_models")),
        sa.UniqueConstraint("version", "dimension", name=op.f("uq_embedding_models_version")),
    )
    op.create_table(
        "pin_embeddings",
        sa.Column("pin_id", sa.String(length=36), nullable=False),
        sa.Column("embedder_version", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "abs(vector_norm(embedding) - 1) < 0.0001", name=op.f("ck_pin_embeddings_unit_vector")
        ),
        sa.CheckConstraint(
            "vector_dims(embedding) = dimension", name=op.f("ck_pin_embeddings_matching_dimension")
        ),
        sa.ForeignKeyConstraint(
            ["embedder_version", "dimension"],
            ["embedding_models.version", "embedding_models.dimension"],
            name=op.f("fk_pin_embeddings_embedder_version_embedding_models"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pin_id"], ["pins.id"], name=op.f("fk_pin_embeddings_pin_id_pins"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint(
            "pin_id", "embedder_version", "content_hash", name=op.f("pk_pin_embeddings")
        ),
    )
    op.create_index(
        op.f("ix_pin_embeddings_known_at"), "pin_embeddings", ["known_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pin_embeddings_known_at"), table_name="pin_embeddings")
    op.drop_table("pin_embeddings")
    op.drop_table("embedding_models")
