import httpx
import pytest
from test_operations import TOKEN, sim_settings

from scripts import export_operations


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://127.0.0.1:8002?secret=1",
        "http://user:password@localhost:8002",
        "http://localhost:8002/path",
    ],
)
def test_export_never_sends_control_credentials_to_nonlocal_or_nonorigin_urls(url):
    with pytest.raises(ValueError, match="loopback"):
        export_operations.export(sim_settings(), url)


def test_export_checks_identity_before_requesting_diagnostics(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.headers["X-Sim-Control-Token"] == TOKEN
        return httpx.Response(200, json={"environment_id": "pinmorph-sim-wrong"})

    original = httpx.Client
    monkeypatch.setattr(
        export_operations.httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ValueError, match="environment"):
        export_operations.export(sim_settings(), "http://localhost:8002")
    assert calls == ["/sim/capabilities"]


def test_export_records_observations_without_assessing_an_exercise(monkeypatch):
    def handler(request):
        result = {"environment_id": "pinmorph-sim-test", "supports_reset": False}
        if request.url.path == "/health/ready":
            return httpx.Response(503, json={"status": "not_ready"})
        if request.url.path == "/sim/diagnostics":
            result = {"components": {"database": {"status": "ok"}}}
        return httpx.Response(200, json=result)

    original = httpx.Client
    monkeypatch.setattr(
        export_operations.httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    report = export_operations.export(sim_settings(), "http://localhost:8002")
    assert report["exercise_outcome"] == "not_assessed"
    assert report["readiness"]["http_status"] == 503
    assert TOKEN not in str(report)
    assert not report["capabilities"]["supports_reset"]
