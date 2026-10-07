"""Upgrade an earlier schema with real rows in a newly created disposable database."""

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
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


def test_phase4_upgrade_preserves_private_membership_and_backfills_search(monkeypatch):
    admin = make_engine(Settings()).execution_options(isolation_level="AUTOCOMMIT")
    database = f"pinmorph_phase4_test_{uuid4().hex}"
    scratch = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
        url = admin.url.set(database=database)
        monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        scratch = create_engine(url)
        config = Config("alembic.ini")
        command.upgrade(config, "cdfce4ed4eea")
        user_id, board_id, pin_id, save_id, section_id = [str(uuid4()) for _ in range(5)]
        with scratch.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, display_name, created_at) "
                    "VALUES (:id, 'Old user', now())"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO boards (id, owner_id, name, created_at) "
                    "VALUES (:id, :owner, 'Existing private board', now())"
                ),
                {"id": board_id, "owner": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO pins (id, owner_id, title, description, "
                    "provenance, source_metadata, "
                    "original_key, status, variants, available_at, created_at) VALUES "
                    "(:id, :owner, 'Orchard chairs', '', 'manual_upload', '{}', 'unused', "
                    "'ready', '{}', now(), now())"
                ),
                {"id": pin_id, "owner": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO saves (id, board_id, pin_id, created_at) "
                    "VALUES (:id, :board, :pin, now())"
                ),
                {"id": save_id, "board": board_id, "pin": pin_id},
            )
        command.upgrade(config, "head")
        with scratch.begin() as connection:
            definition = connection.scalar(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_lens_clip_hnsw'")
            )
            assert "hnsw" in definition and "vector_cosine_ops" in definition
            assert "vector(512)" in definition and "embedder:clip-image-crop:v1" in definition
            assert connection.scalar(text("SELECT is_moderator FROM users")) is False
            assert connection.scalar(text("SELECT is_secret FROM boards")) is True
            assert connection.scalar(text("SELECT bio FROM users")) == ""
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pins WHERE search_document "
                        "@@ plainto_tsquery('english', 'chairs')"
                    )
                )
                == 1
            )
            connection.execute(
                text(
                    "INSERT INTO board_sections (id, board_id, name, created_at) "
                    "VALUES (:id, :board, 'Plants', now())"
                ),
                {"id": section_id, "board": board_id},
            )
            connection.execute(text("UPDATE saves SET section_id = :id"), {"id": section_id})
        with scratch.begin() as connection:
            connection.execute(text("DELETE FROM board_sections"))
        with scratch.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM saves")) == 1
            assert connection.scalar(text("SELECT section_id FROM saves")) is None
        command.downgrade(config, "cdfce4ed4eea")
        command.upgrade(config, "head")
    finally:
        if scratch is not None:
            scratch.dispose()
        if created:
            with admin.connect() as connection:
                # Only the exact random database created by this test is removed.
                connection.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()
