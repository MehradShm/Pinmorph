"""Real PostgreSQL schema checks and opt-in ingestion learning targets."""

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.experiments.config import FeedConfig
from app.feed.contracts import FeedContext
from app.feed.service import FeedService
from app.logging.models import Engagement, EventReceipt, FeedRequest, Impression, ServedItem
from app.logging.schemas import VIEW_RULE_VERSION, EngagementEvent, ImpressionEvent
from app.logging.service import EventConflict, EventIngestor, InvalidAttribution
from app.ml.baselines import CatalogCandidateSource
from app.models import Board, ImportedInteraction, ImportRun, Pin, Save, User, utcnow
from scripts.inspect_feed import inspect_request

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


@pytest.fixture
def serving_records():
    engine = make_engine(Settings())
    with Session(engine) as db:
        user = User(id=str(uuid4()), display_name="Phase 2 fixture")
        other = User(id=str(uuid4()), display_name="Other fixture user")
        pins = [
            Pin(
                id=str(uuid4()),
                title=f"Phase 2 fixture {index}",
                original_key="unused/fixture.png",
                status="ready",
                available_at=utcnow() - timedelta(days=1),
            )
            for index in range(3)
        ]
        db.add_all([user, other, *pins])
        db.flush()
        request = FeedRequest(
            request_id=str(uuid4()),
            user_id=user.id,
            surface="home",
            context={},
            experiment_arms={"baseline_feed:v1": "recency"},
            model_versions={"ranker": "ranker:recency:v1"},
            config_version="feed:baseline:v1",
            latency_ms=2.0,
            served_at=utcnow(),
            received_at=utcnow(),
        )
        db.add(request)
        db.flush()
        for position, pin in enumerate(pins):
            db.add(
                ServedItem(
                    request_id=request.request_id,
                    pin_id=pin.id,
                    position=position,
                    candidate_sources=["candidate:catalog:v1"],
                    rank_score=-24.0,
                    final_score=-24.0,
                )
            )
        db.flush()
        user_ids = [user.id, other.id]
        pin_ids = [pin.id for pin in pins]
        try:
            yield db, user, other, request, pins
        finally:
            # Ingestion exercises may commit. Delete only this fixture's records afterwards.
            db.rollback()
            for pin_id in pin_ids:
                existing = db.get(Pin, pin_id)
                if existing:
                    db.delete(existing)
            for user_id in user_ids:
                existing = db.get(User, user_id)
                if existing:
                    db.delete(existing)
            db.commit()
    engine.dispose()


def receipt(db, user_id, event_id=None, kind="impression"):
    record = EventReceipt(
        event_id=event_id or str(uuid4()),
        user_id=user_id,
        kind=kind,
        payload_hash="0" * 64,
        payload={},
        outcome="accepted",
        event_time=utcnow(),
        received_at=utcnow(),
    )
    db.add(record)
    db.flush()
    return record


def impression(db, user_id, request_id, pin_id, position):
    event = receipt(db, user_id)
    return Impression(
        event_id=event.event_id,
        user_id=user_id,
        request_id=request_id,
        pin_id=pin_id,
        position=position,
        event_time=utcnow(),
        received_at=utcnow(),
        view_rule_version=VIEW_RULE_VERSION,
    )


def test_served_records_do_not_create_views(serving_records):
    db, _, _, request, _ = serving_records
    assert (
        db.scalar(
            select(func.count())
            .select_from(ServedItem)
            .where(ServedItem.request_id == request.request_id)
        )
        == 3
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(Impression)
            .where(Impression.request_id == request.request_id)
        )
        == 0
    )
    report = inspect_request(db, request.request_id)
    assert (report["served_count"], report["viewed_count"], report["unviewed_count"]) == (3, 0, 3)
    assert report["model_versions"]["ranker"] == "ranker:recency:v1"


@pytest.mark.parametrize("invalid", ["wrong_user", "wrong_position", "duplicate_view"])
def test_impression_constraints_reject_invalid_identity_and_duplicate_views(
    serving_records, invalid
):
    db, user, other, request, pins = serving_records
    db.add(impression(db, user.id, request.request_id, pins[0].id, 0))
    db.flush()
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.add(
            impression(
                db,
                other.id if invalid == "wrong_user" else user.id,
                request.request_id,
                pins[0].id if invalid == "duplicate_view" else pins[1].id,
                1 if invalid == "wrong_user" else 0,
            )
        )
        db.flush()
    expected = {
        "wrong_user": "fk_impressions_request_id_feed_requests",
        "wrong_position": "fk_impressions_request_id_served_items",
        "duplicate_view": "uq_impressions_request_id",
    }
    assert error.value.orig.diag.constraint_name == expected[invalid]


def test_event_key_is_global_across_types(serving_records):
    db, user, _, _, _ = serving_records
    first = receipt(db, user.id)
    event_id = first.event_id
    db.expunge(first)
    with pytest.raises(IntegrityError), db.begin_nested():
        receipt(db, user.id, event_id=event_id, kind="engagement")


def test_served_position_is_unique(serving_records):
    db, _, _, request, pins = serving_records
    # Free this pin's old row so only position, rather than pin ID, conflicts.
    db.delete(db.get(ServedItem, (request.request_id, pins[2].id)))
    db.flush()
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.add(
            ServedItem(
                request_id=request.request_id,
                pin_id=pins[2].id,
                position=0,
                candidate_sources=[],
                rank_score=0,
                final_score=0,
            )
        )
        db.flush()
    assert error.value.orig.diag.constraint_name == "uq_served_items_request_position"


@pytest.mark.phase2_exercise
class TestEventLearningTargets:
    def test_retries_and_a_second_view_id_do_not_inflate_views(self, serving_records):
        db, user, _, request, pins = serving_records
        ingestor = EventIngestor()
        view = ImpressionEvent(
            kind="impression",
            event_id=uuid4(),
            pin_id=pins[0].id,
            request_id=request.request_id,
            position=0,
            view_rule_version=VIEW_RULE_VERSION,
        )
        assert ingestor.ingest(db, user.id, view, utcnow()).outcome == "accepted"
        assert ingestor.ingest(db, user.id, view, utcnow()).outcome == "duplicate"
        alias = view.model_copy(update={"event_id": uuid4()})
        assert ingestor.ingest(db, user.id, alias, utcnow()).outcome == "duplicate_view"
        assert (
            db.scalar(
                select(func.count())
                .select_from(Impression)
                .where(Impression.request_id == request.request_id)
            )
            == 1
        )

    def test_global_conflict_and_wrong_user_are_explicit(self, serving_records):
        db, user, other, request, pins = serving_records
        ingestor = EventIngestor()
        view = ImpressionEvent(
            kind="impression",
            event_id=uuid4(),
            pin_id=pins[0].id,
            request_id=request.request_id,
            position=0,
            view_rule_version=VIEW_RULE_VERSION,
        )
        ingestor.ingest(db, user.id, view, utcnow())
        action = EngagementEvent(
            kind="engagement", type="save", event_id=view.event_id, pin_id=pins[0].id
        )
        with pytest.raises(EventConflict):
            ingestor.ingest(db, user.id, action, utcnow())
        with pytest.raises(InvalidAttribution):
            ingestor.ingest(db, other.id, view.model_copy(update={"event_id": uuid4()}), utcnow())

    def test_action_before_view_reconciles_without_changing_boards(self, serving_records):
        db, user, _, request, pins = serving_records
        ingestor = EventIngestor()
        save_count = (
            select(func.count()).select_from(Save).join(Board).where(Board.owner_id == user.id)
        )
        before = db.scalar(save_count)
        view_id = uuid4()
        action = EngagementEvent(
            kind="engagement",
            type="save",
            event_id=uuid4(),
            pin_id=pins[0].id,
            request_id=request.request_id,
            position=0,
            impression_event_id=view_id,
        )
        assert ingestor.ingest(db, user.id, action, utcnow()).outcome == "pending"
        view = ImpressionEvent(
            kind="impression",
            event_id=view_id,
            pin_id=pins[0].id,
            request_id=request.request_id,
            position=0,
            view_rule_version=VIEW_RULE_VERSION,
        )
        ingestor.ingest(db, user.id, view, utcnow())
        db.expire_all()
        record = db.get(Engagement, str(action.event_id))
        assert record.attribution_status == "attributed"
        assert record.impression_event_id == str(view_id)
        assert db.scalar(save_count) == before


@pytest.mark.phase2_exercise
class TestCandidateLearningTargets:
    def test_time_cutoffs_and_proxy_provenance(self, serving_records):
        db, user, other, request, pins = serving_records
        as_of = utcnow() + timedelta(seconds=5)
        pins[0].available_at = as_of - timedelta(hours=24)
        pins[1].available_at = as_of + timedelta(hours=1)
        pins[2].status = "queued"
        import_run = ImportRun(id=str(uuid4()), dataset="fixture", manifest={})
        db.add(import_run)
        db.flush()
        for index, (who, occurred, received) in enumerate(
            [
                (user, as_of - timedelta(days=2), as_of - timedelta(seconds=1)),
                (user, as_of - timedelta(days=1), as_of - timedelta(seconds=1)),
                (other, as_of - timedelta(days=1), as_of + timedelta(seconds=1)),
                (other, as_of, as_of - timedelta(seconds=1)),
            ]
        ):
            db.add(
                ImportedInteraction(
                    source_key=f"{import_run.id}:{index}",
                    import_run_id=import_run.id,
                    user_id=who.id,
                    pin_id=pins[0].id,
                    event_time=occurred,
                    original_event_time=occurred,
                    received_at=received,
                )
            )
        db.flush()
        context = FeedContext(request.request_id, user.id, as_of, as_of)
        candidates = CatalogCandidateSource().retrieve(db, context)
        by_id = {row.pin.id: row for row in candidates}
        assert pins[1].id not in by_id and pins[2].id not in by_id
        # Repeat purchases from one user count once. Late and tied-boundary rows count zero.
        assert by_id[pins[0].id].features == {
            "age_hours": 24.0,
            "observed_save_count": 0,
            "imported_purchase_count": 1,
        }

    def test_feed_persists_list_versions_and_features_without_views(self, serving_records):
        db, user, _, _, _ = serving_records
        now = utcnow()
        context = FeedContext(str(uuid4()), user.id, now, now, limit=2)
        page = FeedService(FeedConfig()).serve(db, context)
        assert page.request_id == context.request_id
        assert [item.position for item in page.items] == [0, 1]
        assert len({item.pin.id for item in page.items}) == 2
        report = inspect_request(db, page.request_id)
        assert report["served_count"] == 2 and report["viewed_count"] == 0
        assert report["model_versions"] == page.model_versions
        assert report["experiment_arms"] == page.experiment_arms
        assert all(item["features"] is not None for item in report["items"])
        assert all(
            item["feature_schema_version"] == "features:baseline:v1" for item in report["items"]
        )
