from alembic import context

from app import models  # noqa: F401 -- register product tables with Alembic
from app.config import Settings
from app.database import Base, make_engine
from app.logging import models as logging_models  # noqa: F401 -- register Phase 2 tables
from app.ml import models as ml_models  # noqa: F401 -- register Phase 3A tables
from app.product import models as product_models  # noqa: F401
from app.social import models as social_models  # noqa: F401 -- register social tables

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Alembic cannot round-trip the cast/operator-class expression reliably.
    # These fixed recipe indexes are explicitly migrated and separately asserted in tests.
    return not (type_ == "index" and name in {"ix_lens_clip_hnsw", "ix_personalized_clip_hnsw"})


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
