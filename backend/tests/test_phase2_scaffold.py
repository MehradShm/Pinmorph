from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.auth import current_user, get_db
from app.config import Settings
from app.experiments.config import Arm, Experiment, FeedConfig
from app.feed.registry import Registry
from app.feed.service import FeedService
from app.logging.schemas import VIEW_RULE_VERSION, EventInput
from app.main import create_app
from app.models import User

USER_ID = "00000000-0000-4000-8000-000000000001"
REQUEST_ID = "00000000-0000-4000-8000-000000000010"
PIN_ID = "00000000-0000-4000-8000-000000000020"
EVENT_ID = "00000000-0000-4000-8000-000000000030"


def view_payload(**changes):
    return {
        "kind": "impression",
        "event_id": EVENT_ID,
        "pin_id": PIN_ID,
        "request_id": REQUEST_ID,
        "position": 0,
        "view_rule_version": VIEW_RULE_VERSION,
        **changes,
    }


@contextmanager
def scaffold_client():
    app = create_app(Settings(_env_file=None), health_checks={})
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[current_user] = lambda: User(id=USER_ID, display_name="Tester")
    with TestClient(app) as client:
        yield client


def test_registry_rejects_unknown_and_duplicate_versions():
    registry = Registry[str]()
    registry.register("ranker:test:v1", "implementation")
    assert registry.resolve("ranker:test:v1") == "implementation"
    with pytest.raises(ValueError, match="already registered"):
        registry.register("ranker:test:v1", "replacement")
    with pytest.raises(ValueError, match="Unknown implementation"):
        registry.resolve("ranker:typo:v1")


def test_experiment_requires_complete_unique_allocation():
    with pytest.raises(ValidationError, match="10,000"):
        Experiment(arms=(Arm(name="recency", buckets=9999, ranker="ranker:recency:v1"),))
    with pytest.raises(ValidationError, match="unique"):
        Experiment(
            arms=(
                Arm(name="same", buckets=5000, ranker="ranker:recency:v1"),
                Arm(name="same", buckets=5000, ranker="ranker:popularity:v1"),
            )
        )


def test_unknown_configured_model_fails_before_startup():
    config = FeedConfig(candidate_source="candidate:misspelled:v1")
    with pytest.raises(ValueError, match="Unknown implementation"):
        FeedService(config)


@pytest.mark.parametrize(
    "changes",
    [
        {"position": -1},
        {"position": 0.5},
        {"position": True},
        {"event_id": "not-a-uuid"},
        {"view_rule_version": "scroll-only"},
        {"user_id": USER_ID},
        {"event_time": "2000-01-01T00:00:00Z"},
        {"sim_run_id": REQUEST_ID},
        {"client_event_time": "2026-10-07T12:00:00"},
    ],
)
def test_view_schema_rejects_invalid_or_untrusted_fields(changes):
    with pytest.raises(ValidationError):
        TypeAdapter(EventInput).validate_python(view_payload(**changes))


def test_actions_require_complete_optional_attribution():
    body = {"kind": "engagement", "type": "save", "event_id": EVENT_ID, "pin_id": PIN_ID}
    adapter = TypeAdapter(EventInput)
    assert adapter.validate_python(body).request_id is None
    with pytest.raises(ValidationError, match="supplied together"):
        adapter.validate_python({**body, "request_id": REQUEST_ID})
    with pytest.raises(ValidationError, match="requires served-item"):
        adapter.validate_python({**body, "impression_event_id": EVENT_ID})
    with pytest.raises(ValidationError):
        adapter.validate_python({**body, "type": "purchase"})


def test_event_api_maps_invalid_attribution_to_validation_error():
    from app.logging.service import InvalidAttribution

    class RejectingIngestor:
        def ingest(self, *args):
            raise InvalidAttribution()

    with scaffold_client() as client:
        client.app.state.event_ingestor = RejectingIngestor()
        response = client.post("/api/events", json=view_payload())
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"


def test_new_routes_reject_simulation_overrides_and_cross_origin_mutations():
    with scaffold_client() as client:
        assert client.get("/api/feed", headers={"X-Sim-Time": "2000-01-01"}).status_code == 422
        assert (
            client.post(
                "/api/events", json=view_payload(), headers={"X-Sim-Run-ID": REQUEST_ID}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/events", json=view_payload(), headers={"Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/feed?limit=101").status_code == 422
