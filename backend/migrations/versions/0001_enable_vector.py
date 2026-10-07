"""Enable pgvector before the product tables arrive in phase 1."""

from alembic import op

revision = "0001_enable_vector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Do not CASCADE: later vector columns must be removed by their own migrations first.
    op.execute("DROP EXTENSION IF EXISTS vector")
