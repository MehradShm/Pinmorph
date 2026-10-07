"""Exercise real services; run after `docker compose up --build -d --wait`."""

import os
from time import monotonic, sleep
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer
from sqlalchemy import text

from app.config import Settings
from app.database import make_engine
from app.jobs import echo
from app.main import create_app
from app.storage import make_s3_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


def test_migration_is_repeatable_and_enables_vector():
    configuration = Config("alembic.ini")
    command.upgrade(configuration, "head")
    command.upgrade(configuration, "head")
    engine = make_engine(Settings())
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert connection.scalar(text("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector")) == 0
    finally:
        engine.dispose()


def test_ready_with_real_dependencies():
    with TestClient(create_app()) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200, response.json()


def test_object_storage_round_trip():
    settings = Settings()
    client = make_s3_client(settings)
    key = f"smoke/{uuid4()}.txt"
    try:
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"pinmorph")
        response = client.get_object(Bucket=settings.s3_bucket, Key=key)
        try:
            assert response["Body"].read() == b"pinmorph"
        finally:
            response["Body"].close()
    finally:
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
        client.close()


def test_worker_executes_a_real_job():
    settings = Settings()
    with Redis.from_url(settings.redis_url.get_secret_value()) as connection:
        queue = Queue("default", connection=connection, serializer=JSONSerializer)
        message = f"smoke-{uuid4()}"
        job = queue.enqueue(echo, message, job_timeout=10, result_ttl=60)
        deadline = monotonic() + 30
        try:
            while monotonic() < deadline:
                job.refresh()
                if job.is_finished:
                    assert job.return_value() == message
                    break
                assert not job.is_failed, job.exc_info
                sleep(0.1)
            else:
                pytest.fail("RQ worker did not complete the smoke job within 30 seconds")
        finally:
            job.delete()
