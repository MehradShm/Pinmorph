"""Phase 5 is additive to Phase 4; validate both directions in an exact scratch database."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import Settings
from app.database import make_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Real Postgres"),
]


def test_phase5_upgrade_retains_phase4_data_and_defaults_to_personal(monkeypatch):
    admin = make_engine(Settings()).execution_options(isolation_level="AUTOCOMMIT")
    database = "pinmorph_phase5_test_" + uuid4().hex
    scratch = None
    created = False
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
        url = admin.url.set(database=database)
        monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        scratch = create_engine(url)
        config = Config("alembic.ini")
        command.upgrade(config, "4f1a7b239abc")
        user_id, pin_id = str(uuid4()), str(uuid4())
        with scratch.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, display_name, created_at) VALUES (:id, 'Legacy', now())"
                ),
                {"id": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO pins (id, owner_id, title, description, provenance, "
                    "source_metadata, "
                    "original_key, status, variants, available_at, created_at) VALUES "
                    "(:pin, :owner, 'Legacy pin', '', 'manual_upload', '{}', 'unused', "
                    "'ready', '{}', now(), now())"
                ),
                {"pin": pin_id, "owner": user_id},
            )
        command.upgrade(config, "head")
        with scratch.begin() as conn:
            assert conn.scalar(text("SELECT is_business FROM users")) is False
            assert conn.scalar(text("SELECT count(*) FROM pins")) == 1
            assert conn.scalar(text("SELECT count(*) FROM pin_products")) == 0
            assert conn.scalar(text("SELECT count(*) FROM pin_daily_rollups")) == 0
            conn.execute(
                text(
                    "INSERT INTO pin_products (pin_id, price, currency, availability, "
                    "merchant_url, updated_at) VALUES "
                    "(:pin, 19.90, 'CAD', 'in_stock', 'https://example.test', now())"
                ),
                {"pin": pin_id},
            )
            assert str(conn.scalar(text("SELECT price FROM pin_products"))) == "19.90"
        command.downgrade(config, "4f1a7b239abc")
        with scratch.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM pins")) == 1
            assert conn.scalar(text("SELECT count(*) FROM users")) == 1
        command.upgrade(config, "head")
    finally:
        if scratch is not None:
            scratch.dispose()
        if created:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()
