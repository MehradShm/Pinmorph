"""Acceptance of the finished Phase 4 paths using real local services."""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_core_loop_integration import png_bytes, wait_ready
from test_phase4_integration import ready_pin

from app.config import Settings
from app.database import make_engine
from app.logging.models import Engagement, FeedRequest, Impression, ServedFeature, ServedItem
from app.media import process_pin
from app.models import Pin, User
from app.product.digests import deliver_pending
from app.product.models import EmailOutbox, SafetyReport

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Real services"),
]


def ids(page):
    return [row["pin"]["id"] for row in page["items"]]


def test_following_union_versions_cursor_views_and_policy(clients):
    viewer, creator, other = clients(), clients(), clients()
    creator_id = creator.get("/api/auth/me").json()["id"]
    own_pin = ready_pin(creator, "Fashion inspiration")
    board_pin = ready_pin(other, "Public board idea")
    future_pin = ready_pin(creator, "Future idea", future=True)
    board = creator.post("/api/boards", json={"name": "Ideas", "is_secret": False}).json()
    for pin_id in (own_pin, board_pin):
        assert creator.post(f"/api/boards/{board['id']}/pins/{pin_id}").status_code == 200
    viewer.put(f"/api/social/users/{creator_id}/follow")
    viewer.put(f"/api/social/boards/{board['id']}/follow")
    first = viewer.get("/api/feed/following?limit=1").json()
    second = viewer.get(
        "/api/feed/following", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert set(ids(first) + ids(second)) == {own_pin, board_pin}
    assert future_pin not in ids(first) + ids(second)
    assert viewer.get("/api/feed", params={"cursor": first["next_cursor"]}).status_code == 422
    assert (
        other.get("/api/feed/following", params={"cursor": first["next_cursor"]}).status_code == 422
    )
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            item = db.get(ServedItem, (first["request_id"], ids(first)[0]))
            assert item and db.get(ServedFeature, (first["request_id"], ids(first)[0]))
            if item.pin_id == own_pin:
                assert len(item.candidate_sources) == 2
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Impression)
                    .where(Impression.request_id == first["request_id"])
                )
                == 0
            )
    finally:
        engine.dispose()
    creator.put(f"/api/boards/{board['id']}", json={"name": "Ideas", "is_secret": True})
    assert ids(viewer.get("/api/feed/following").json()) == [own_pin]
    viewer.put(f"/api/social/users/{creator_id}/mute")
    assert ids(viewer.get("/api/feed/following").json()) == []


def test_related_ignores_secret_boards_and_future_saves(clients):
    owner, viewer = clients(), clients()
    context = ready_pin(owner, "Context")
    public_pin, secret_pin = (
        ready_pin(owner, "Public neighbor"),
        ready_pin(owner, "Secret neighbor"),
    )
    for secret, neighbor in ((False, public_pin), (True, secret_pin)):
        board = owner.post("/api/boards", json={"name": str(secret), "is_secret": secret}).json()
        for pin in (context, neighbor):
            owner.post(f"/api/boards/{board['id']}/pins/{pin}")
    response = viewer.get(f"/api/pins/{context}/related").json()
    assert ids(response) == [public_pin]
    assert response["model_versions"]["candidate_source"] == "candidate:related-public-boards:v1"
    owner_id = owner.get("/api/auth/me").json()["id"]
    viewer.put(f"/api/social/users/{owner_id}/block")
    assert viewer.get(f"/api/pins/{context}/related").status_code == 404


def test_search_attribution_and_event_retries_reconciliation(clients):
    viewer, other = clients(), clients()
    title = "needle" + uuid4().hex
    pin_id = ready_pin(viewer, title)
    page = viewer.get("/api/search/pins", params={"q": title}).json()
    assert page["attributed"] and len(page["items"]) == 1
    view_id = str(uuid4())
    action = {
        "kind": "engagement",
        "type": "closeup",
        "event_id": str(uuid4()),
        "pin_id": pin_id,
        "request_id": page["request_id"],
        "position": 0,
        "impression_event_id": view_id,
    }
    assert viewer.post("/api/events", json=action).json()["outcome"] == "pending"
    view = {
        "kind": "impression",
        "event_id": view_id,
        "pin_id": pin_id,
        "request_id": page["request_id"],
        "position": 0,
        "view_rule_version": "viewport:50pct:1000ms:v1",
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(lambda _: viewer.post("/api/events", json=view).json()["outcome"], range(3))
        )
    assert results.count("accepted") == 1 and results.count("duplicate") == 2
    assert other.post("/api/events", json={**view, "event_id": str(uuid4())}).status_code == 422
    assert viewer.post("/api/events", json={**action, "type": "save"}).status_code == 409
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            saved = db.get(Engagement, action["event_id"])
            assert saved.attribution_status == "attributed" and saved.impression_event_id == view_id
    finally:
        engine.dispose()


def test_comments_reactions_notifications_hide_and_moderation(clients):
    owner, viewer = clients(), clients()
    pin_id = ready_pin(owner, "Reviewable pin")
    comment = viewer.post(f"/api/pins/{pin_id}/comments", json={"body": "A thoughtful idea"}).json()
    assert owner.delete(f"/api/comments/{comment['id']}").status_code == 404
    for _ in range(2):
        assert viewer.put(f"/api/pins/{pin_id}/reaction").json()["count"] == 1
    assert {n["kind"] for n in owner.get("/api/notifications").json()["items"]} == {
        "comment",
        "reaction",
    }
    viewer.put(f"/api/pins/{pin_id}/hide")
    assert pin_id not in ids(viewer.get("/api/feed?limit=100").json())
    assert not viewer.get("/api/search/pins?q=Reviewable").json()["items"]
    viewer.delete(f"/api/pins/{pin_id}/hide")
    assert pin_id in ids(viewer.get("/api/feed?limit=100").json())
    report = viewer.post(
        f"/api/pins/{pin_id}/report", json={"reason": "Please review this image"}
    ).json()
    assert viewer.get("/api/moderation/reports").status_code == 403
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            user = db.get(User, owner.get("/api/auth/me").json()["id"])
            user.is_moderator = True
            pin = db.get(Pin, pin_id)
            pin.variants = {"display": {"key": "unused"}}
            db.commit()
        assert owner.get("/api/moderation/reports").json()["items"][0]["id"] == report["id"]
        assert (
            owner.put(
                f"/api/moderation/reports/{report['id']}", json={"action": "remove"}
            ).status_code
            == 200
        )
        assert viewer.get(f"/api/pins/{pin_id}").status_code == 404
        assert pin_id not in ids(viewer.get("/api/feed?limit=100").json())
        assert (
            owner.put(
                f"/api/moderation/reports/{report['id']}", json={"action": "restore"}
            ).status_code
            == 409
        )
        # A new classifier review can restore a previously removed pin.
        with Session(engine) as db:
            row = SafetyReport(pin_id=pin_id, reason="Reconsider removal", source="operator")
            db.add(row)
            db.commit()
            review_id = row.id
        assert (
            owner.put(
                f"/api/moderation/reports/{review_id}", json={"action": "restore"}
            ).status_code
            == 200
        )
        assert viewer.get(f"/api/pins/{pin_id}").status_code == 200
    finally:
        engine.dispose()
    assert viewer.delete(f"/api/comments/{comment['id']}").status_code == 204


def test_interest_onboarding_changes_order_and_records_feature_snapshot(clients):
    viewer = clients()
    a = ready_pin(viewer, "Fashion wardrobe")
    b = ready_pin(viewer, "Unrelated idea")
    assert (
        viewer.put(
            "/api/settings", json={"interests": ["fashion"], "onboarding_complete": True}
        ).status_code
        == 200
    )
    page = viewer.get("/api/feed?limit=100").json()
    assert ids(page).index(a) < ids(page).index(b)
    assert viewer.get("/api/settings").json()["onboarding_complete"]
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            assert db.get(ServedFeature, (page["request_id"], a)).features["interest_matches"] == 1
            assert db.get(FeedRequest, page["request_id"]).context["interests"] == ["fashion"]
    finally:
        engine.dispose()


def test_lens_real_encoder_crop_and_model_attribution(clients):
    viewer = clients()
    upload = viewer.post(
        "/api/pins",
        data={"title": "Lens source"},
        files={"image": ("source.png", png_bytes(), "image/png")},
    )
    assert upload.status_code == 202, upload.json()
    pin_id = upload.json()["id"]
    wait_ready(viewer, pin_id)
    duplicate = viewer.post(
        "/api/pins",
        data={"title": "Repeated source"},
        files={"image": ("source.png", png_bytes(), "image/png")},
    )
    assert duplicate.status_code == 409
    response = viewer.post(
        "/api/lens",
        data={"limit": 5, "crop_box": '{"left":0.1,"right":0.9}'},
        files={"image": ("crop.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.json()
    page = response.json()
    assert ids(page)[0] == pin_id
    assert page["model_versions"]["embedder"] == "embedder:clip-image-crop:v1"
    assert page["model_versions"]["retriever"] == "retriever:pgvector-hnsw:v1"
    related = viewer.get(f"/api/pins/{pin_id}/related").json()
    assert related["items"] and pin_id not in ids(related)


def test_classifier_hold_is_private_and_moderator_can_restore(clients, monkeypatch):
    viewer, other = clients(), clients()
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "#546da5").save(buf, "PNG")
    response = viewer.post(
        "/api/pins",
        data={"title": "Held upload"},
        files={"image": ("hold.png", buf.getvalue(), "image/png")},
    )
    pin_id = response.json()["id"]
    wait_ready(viewer, pin_id)
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            pin = db.get(Pin, pin_id)
            pin.status = "queued"
            db.commit()
        monkeypatch.setattr(
            "app.product.safety.classify",
            lambda *a: {"hold": True, "version": "safety:clip-zero-shot:v1"},
        )
        assert process_pin(pin_id) == "quarantined"
        assert viewer.get(f"/api/pins/{pin_id}").json()["status"] == "quarantined"
        assert other.get(f"/api/pins/{pin_id}").status_code == 404
        assert other.get(f"/api/media/{pin_id}/display.jpg").status_code == 404
        with Session(engine) as db:
            row = db.scalar(select(SafetyReport).where(SafetyReport.pin_id == pin_id))
            assert row.source == "safety:clip-zero-shot:v1"
    finally:
        engine.dispose()


def test_digest_local_smtp_idempotency_and_opt_out(clients):
    owner, actor = clients(), clients()
    owner_id = owner.get("/api/auth/me").json()["id"]
    actor.put(f"/api/social/users/{owner_id}/follow")
    owner.put("/api/settings", json={"interests": [], "email_digest": True})
    first = owner.post("/api/notifications/digest").json()
    second = owner.post("/api/notifications/digest").json()
    assert first["outbox_id"] == second["outbox_id"]
    deliver_pending()
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            row = db.get(EmailOutbox, first["outbox_id"])
            assert row.status == "delivered"
        messages = httpx.get("http://127.0.0.1:8025/api/v1/messages", timeout=5).json()["messages"]
        matches = [
            row
            for row in messages
            if any(r["Address"] == owner.get("/api/auth/me").json()["email"] for r in row["To"])
        ]
        assert matches
        # Remove only the message for this fixture's recipient.
        for row in matches:
            httpx.delete(f"http://127.0.0.1:8025/api/v1/messages/{row['ID']}", timeout=5)
        owner.put("/api/settings", json={"interests": [], "email_digest": False})
        assert owner.post("/api/notifications/digest").json()["status"] == "no_activity"
    finally:
        engine.dispose()


def test_url_import_uses_upload_pipeline_and_rejects_private_urls(clients, monkeypatch):
    viewer = clients()
    assert (
        viewer.post(
            "/api/pins/import",
            json={"title": "Unsafe URL", "url": "http://127.0.0.1:9000/image.png"},
        ).status_code
        == 422
    )
    # Fixture transport only; real network fetching has separate DNS/redirect checks.
    monkeypatch.setattr("app.product.api.fetch_image", lambda *a: png_bytes())
    response = viewer.post(
        "/api/pins/import",
        json={"title": "Imported image", "url": "https://images.example.test/pin.png"},
    )
    assert response.status_code == 202, response.json()
    pin = wait_ready(viewer, response.json()["id"])
    assert pin["source_url"] == "https://images.example.test/pin.png"
