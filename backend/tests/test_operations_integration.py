import os

import pytest
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer

from app.config import Settings
from app.database import make_engine
from app.operations.diagnostics import collect_diagnostics
from app.operations.metrics import RequestMetrics

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Requires local stack"),
]


def test_real_database_and_worker_diagnostics_are_read_only_and_inspectable():
    settings = Settings()
    engine = make_engine(settings)
    connection = Redis.from_url(settings.redis_url.get_secret_value(), socket_timeout=2)
    queue = Queue("default", connection=connection, serializer=JSONSerializer)
    try:
        before = queue.count
        report = collect_diagnostics(engine, queue, RequestMetrics())
        assert report["components"]["database"]["status"] == "ok"
        assert report["components"]["queue"]["status"] == "ok"
        data = report["components"]["queue"]["data"]
        assert data["queued"] >= 0 and data["workers"]
        assert data["queue_head_sample_limit"] == 100
        assert queue.count == before
        assert settings.database_url.get_secret_value() not in str(report)
    finally:
        connection.close()
        engine.dispose()
