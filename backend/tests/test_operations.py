from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.operations import diagnostics
from app.operations.metrics import RequestMetrics

TOKEN = "test-control-token-32-characters-long"


def sim_settings(**changes):
    return Settings(
        _env_file=None,
        sim_mode=True,
        sim_disposable=True,
        sim_environment_id="pinmorph-sim-test",
        sim_control_token=TOKEN,
        **changes,
    )


def test_simulation_mode_requires_explicit_isolation_and_control_auth():
    for changes in (
        {},
        {"sim_disposable": True},
        {
            "sim_disposable": True,
            "sim_environment_id": "pinmorph-sim-test",
            "sim_control_token": "short",
        },
    ):
        with pytest.raises(ValidationError, match="disposable"):
            Settings(_env_file=None, sim_mode=True, **changes)

    with pytest.raises(ValidationError) as invalid:
        Settings(
            _env_file=None,
            sim_mode=True,
            sim_disposable=True,
            sim_environment_id="invalid environment",
            sim_control_token=TOKEN,
        )
    assert TOKEN not in str(invalid.value)


def test_controls_are_disabled_in_normal_environment():
    with TestClient(create_app(Settings(_env_file=None), health_checks={})) as client:
        assert client.get("/sim/capabilities").status_code == 404
        assert client.post("/sim/reset", headers={"X-Sim-Control-Token": TOKEN}).status_code == 404
        assert (
            client.get("/api/auth/me", headers={"X-Sim-Run-Id": "unregistered"}).status_code == 422
        )


def test_capabilities_require_control_auth_and_advertise_only_diagnostics():
    with TestClient(create_app(sim_settings(), health_checks={})) as client:
        assert client.get("/sim/capabilities").status_code == 401
        assert (
            client.get("/sim/capabilities", headers={"X-Sim-Control-Token": "wrong"}).status_code
            == 401
        )
        response = client.get("/sim/capabilities", headers={"X-Sim-Control-Token": TOKEN})
        capabilities = response.json()
        assert capabilities["surfaces"] == capabilities["event_types"] == []
        assert capabilities["supports_diagnostics"] and not capabilities["ready_for_traffic"]
        assert not any(
            value
            for key, value in capabilities.items()
            if key.startswith("supports_") and key != "supports_diagnostics"
        )
        assert response.headers["Cache-Control"] == "no-store"
        assert TOKEN not in response.text
        for operation in ("reset", "runs", "users", "events", "train", "config"):
            result = client.post(
                f"/sim/{operation}", json={}, headers={"X-Sim-Control-Token": TOKEN}
            )
            assert result.status_code == 501
        assert client.get("/sim/catalog", headers={"X-Sim-Control-Token": TOKEN}).status_code == 501
        assert client.get("/api/pins", headers={"X-Sim-Run-Id": "unknown"}).status_code == 422


def test_request_metrics_bound_cardinality_and_count_errors():
    app = create_app(Settings(_env_file=None), health_checks={})
    with TestClient(app) as client:
        for index in range(10):
            client.get(f"/missing-{index}?secret={index}")
        client.get("/health/live")
        groups = app.state.request_metrics.snapshot()["requests"]
    assert len(groups) == 2
    missing = next(group for group in groups if group["route"] == "unmatched")
    assert missing["count"] == 10 and missing["status_class"] == "4xx"
    assert "secret" not in str(groups) and "missing-" not in str(groups)


def test_histogram_has_known_counts_and_is_thread_safe():
    metrics = RequestMetrics()
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda value: metrics.observe("GET", "/api/pins/{pin_id}", 200, value),
                [5, 25, 3000, 6000] * 25,
            )
        )
    group = metrics.snapshot()["requests"][0]
    assert group["count"] == group["latency_infinite_bucket"] == 100
    assert group["latency_buckets_ms"]["10"] == 25
    assert group["latency_buckets_ms"]["25"] == 50
    assert group["latency_buckets_ms"]["5000"] == 75
    assert group["latency_sum_ms"] == 225750


def test_component_failure_is_partial_and_does_not_leak_connection_secrets(monkeypatch):
    def offline(*args):
        raise ConnectionError("postgres://user:secret-password@host/db")

    monkeypatch.setattr(diagnostics, "database_snapshot", offline)
    monkeypatch.setattr(diagnostics, "queue_snapshot", lambda *args: {"queued": 0})
    result = diagnostics.collect_diagnostics(object(), object(), RequestMetrics())
    assert result["components"]["database"]["status"] == "error"
    assert result["components"]["queue"]["status"] == "ok"
    assert "secret-password" not in str(result)


def test_queue_inspection_does_not_clean_stale_workers_or_registries(monkeypatch):
    class ReadOnlyRedis:
        def hmget(self, key, *fields):
            return (
                [b"idle", b"2026-10-07T00:00:00.000000Z"] if key.endswith("live") else [None, None]
            )

        def zcard(self, key):
            return 2  # Expired registry entries are counted as stored, not cleaned up.

    queue = SimpleNamespace(
        name="default",
        count=0,
        connection=ReadOnlyRedis(),
        serializer=None,
        get_job_ids=lambda offset, length: [],
    )
    for name in ("started", "failed", "scheduled", "deferred"):
        setattr(queue, f"{name}_job_registry", SimpleNamespace(key=name))
    monkeypatch.setattr(
        diagnostics.worker_registration,
        "get_keys",
        lambda **kwargs: {"rq:worker:live", "rq:worker:stale"},
    )
    report = diagnostics.queue_snapshot(queue, datetime(2026, 10, 7, tzinfo=UTC))
    assert len(report["workers"]) == 1 and report["stale_sampled_worker_registrations"] == 1
    assert report["registered_worker_count"] == 2
    assert set(report["registries"].values()) == {2}
