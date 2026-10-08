"""Add the image/title recipe's own fixed-dimension HNSW index.

Revision ID: 72aa31f096bc
Revises: e9b3c71d5f02
"""

from alembic import op

revision = "72aa31f096bc"
down_revision = "e9b3c71d5f02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX ix_personalized_clip_hnsw ON pin_embeddings "
        "USING hnsw ((embedding::vector(512)) vector_cosine_ops) "
        "WHERE embedder_version = 'embedder:clip-image-title:v1' AND dimension = 512"
    )


def downgrade():
    op.drop_index("ix_personalized_clip_hnsw", table_name="pin_embeddings")
