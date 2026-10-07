from alembic import context

from app import models  # noqa: F401 -- register product tables with Alembic
from app.config import Settings
from app.database import Base, make_engine
from app.logging import models as logging_models  # noqa: F401 -- register Phase 2 tables
from app.ml import models as ml_models  # noqa: F401 -- register Phase 3A tables
from app.social import models as social_models  # noqa: F401 -- register social tables

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
