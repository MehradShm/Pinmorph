import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_liveness_does_not_contact_dependencies():
    calls = []

    def unavailable():
        calls.append("called")
        raise ConnectionError("offline")

    app = create_app(Settings(_env_file=None), health_checks={"postgres": unavailable})
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == []
    assert UUID(response.headers["X-Request-ID"])


def test_readiness_identifies_failed_dependency_without_leaking_credentials():
    def unavailable():
        raise ConnectionError("postgresql://user:secret-password@host/db")

    app = create_app(
        Settings(_env_file=None),
        health_checks={"postgres": unavailable, "redis": lambda: True},
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["postgres"]["error_type"] == "ConnectionError"
    assert payload["dependencies"]["redis"]["status"] == "ok"
    assert payload["request_id"] == response.headers["X-Request-ID"]
    assert "secret-password" not in response.text


def test_readiness_succeeds_when_all_dependencies_work():
    app = create_app(
        Settings(_env_file=None),
        health_checks={name: lambda: True for name in ("postgres", "redis", "object_storage")},
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert all(item["latency_ms"] >= 0 for item in response.json()["dependencies"].values())


def test_request_errors_have_correlated_safe_diagnostics(caplog):
    app = create_app(Settings(_env_file=None), health_checks={})

    @app.get("/broken")
    def broken():
        raise RuntimeError("secret-token")

    with caplog.at_level(logging.INFO, logger="pinmorph.requests"), TestClient(app) as client:
        response = client.get("/broken?token=secret-query")
    assert response.status_code == 500
    request_id = response.headers["X-Request-ID"]
    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "pinmorph.requests"
    ]
    assert {record["request_id"] for record in records} == {request_id}
    assert [record["event"] for record in records] == ["request_failed", "request_completed"]
    assert records[-1]["status_code"] == 500
    assert "secret-token" not in response.text + str(records)
    assert "secret-query" not in str(records)
