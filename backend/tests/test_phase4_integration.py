"""Real PostgreSQL privacy, search, relationship races and section invariants."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_core_loop_integration import png_bytes

from app.config import Settings
from app.database import make_engine
from app.logging.models import FeedRequest, Impression
from app.models import Pin, Save
from app.social.models import Notification, UserFollow

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


def ready_pin(client, title, *, future=False, description=""):
    owner_id = client.get("/api/auth/me").json()["id"]
    pin_id = str(uuid4())
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            db.add(
                Pin(
                    id=pin_id,
                    owner_id=owner_id,
                    title=title,
                    description=description,
                    status="ready",
                    original_key=f"pins/{pin_id}/original",
                    available_at=datetime.now(UTC) + timedelta(days=1 if future else -1),
                )
            )
            db.commit()
    finally:
        engine.dispose()
    return pin_id


def test_keyword_search_filters_suggestions_pagination_and_no_implied_views(clients):
    owner, public = clients(), clients(False)
    word = f"orchard{uuid4().hex}"
    pins = {ready_pin(owner, f"{word} collection {index}") for index in range(3)}
    future = ready_pin(owner, f"{word} future", future=True)
    params = {"q": word, "limit": 2}
    first = public.get("/api/search/pins", params=params).json()
    assert first["model_versions"] == {"search": "search:postgres-fts-recency:v1"}
    assert first["request_id"] and len(first["items"]) == 2
    second = public.get(
        "/api/search/pins", params={**params, "cursor": first["next_cursor"]}
    ).json()
    assert {pin["id"] for pin in first["items"] + second["items"]} == pins
    assert second["next_cursor"] is None
    assert (
        public.get(
            "/api/search/pins", params={"q": "other", "cursor": first["next_cursor"]}
        ).status_code
        == 422
    )
    assert (
        public.get("/api/search/pins", params={"q": word, "provenance": "synthetic_demo"}).json()[
            "items"
        ]
        == []
    )
    suggestions = public.get("/api/search/suggest", params={"q": word[:-2]}).json()["items"]
    assert len(suggestions) == 3 and not any("future" in item for item in suggestions)
    assert future not in {pin["id"] for pin in first["items"]}
    assert public.get("/api/search/pins", params={"q": "  "}).status_code == 422
    assert (
        public.get(
            "/api/search/pins", params={"q": word, "created_after": "2026-01-01"}
        ).status_code
        == 422
    )

    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            request_ids = [first["request_id"], second["request_id"]]
            for model in [FeedRequest, Impression]:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.request_id.in_(request_ids))
                    )
                    == 0
                )
    finally:
        engine.dispose()


def test_public_profile_never_exposes_email_and_can_be_edited(clients):
    owner, public = clients(), clients(False)
    own = owner.get("/api/auth/me").json()
    edited = owner.patch(
        "/api/profiles/me", json={"display_name": "Garden collector", "bio": "Plants and parks"}
    )
    assert edited.status_code == 200
    profile = public.get(f"/api/profiles/{own['id']}").json()
    assert profile["bio"] == "Plants and parks"
    assert "email" not in profile and "source_key" not in profile and "password_hash" not in profile
    assert own["id"] in {
        row["id"]
        for row in public.get("/api/profiles", params={"q": "Garden collector"}).json()["items"]
    }
    assert owner.patch("/api/profiles/me", json={"display_name": " "}).status_code == 422
    assert public.patch("/api/profiles/me", json={"display_name": "No account"}).status_code == 401


def test_follow_retries_concurrency_notifications_and_recipient_ownership(clients):
    owner, other = clients(), clients()
    own_id = owner.get("/api/auth/me").json()["id"]
    other_id = other.get("/api/auth/me").json()["id"]
    route = f"/api/social/users/{own_id}/follow"
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: other.put(route), range(4)))
    assert all(row.status_code == 200 for row in results)
    assert owner.get(f"/api/profiles/{own_id}").json()["follower_count"] == 1
    assert (
        owner.get(f"/api/profiles/{own_id}/connections/followers").json()["items"][0]["id"]
        == other_id
    )
    notices = owner.get("/api/notifications").json()["items"]
    assert len(notices) == 1 and notices[0]["kind"] == "user_follow"
    read_url = f"/api/notifications/{notices[0]['id']}/read"
    assert other.put(read_url).status_code == 404
    assert owner.put(read_url).status_code == 204
    assert owner.put(read_url).status_code == 204
    assert owner.get("/api/notifications").json()["items"][0]["read_at"] is not None
    assert owner.put(f"/api/social/users/{own_id}/follow").status_code == 422
    assert other.delete(route).status_code == other.delete(route).status_code == 204


def test_secret_boards_publication_and_revocation_of_board_follows(clients):
    owner, other, public = clients(), clients(), clients(False)
    own_id = owner.get("/api/auth/me").json()["id"]
    board = owner.post("/api/boards", json={"name": "Private collection"}).json()
    assert board["is_secret"] is True
    board_url = f"/api/boards/{board['id']}"
    pin_id = ready_pin(owner, "Shared pin")
    assert owner.post(f"{board_url}/pins/{pin_id}").status_code == 200
    assert public.get(board_url).status_code == 404
    assert public.get(f"/api/profiles/{own_id}/boards").json()["items"] == []
    assert other.put(f"/api/social/boards/{board['id']}/follow").status_code == 404
    assert owner.put(board_url, json={"name": board["name"], "is_secret": False}).status_code == 200
    assert public.get(f"{board_url}/pins").json()["items"][0]["id"] == pin_id
    assert other.put(f"/api/social/boards/{board['id']}/follow").status_code == 200
    assert (
        other.put(f"{board_url}/pins/{pin_id}/section", json={"section_id": None}).status_code
        == 404
    )
    assert owner.put(board_url, json={"name": board["name"], "is_secret": True}).status_code == 200
    assert other.get(f"{board_url}/pins").status_code == 404
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            from app.social.models import BoardFollow

            assert (
                db.get(BoardFollow, (other.get("/api/auth/me").json()["id"], board["id"])) is None
            )
    finally:
        engine.dispose()
    # Board membership privacy does not make the uploaded pin private.
    assert public.get(f"/api/pins/{pin_id}").status_code == 200


def test_sections_enforce_board_membership_and_delete_preserves_saves(clients):
    owner, other = clients(), clients()
    board = owner.post("/api/boards", json={"name": "Sections"}).json()
    another = owner.post("/api/boards", json={"name": "Another"}).json()
    section = owner.post(f"/api/boards/{board['id']}/sections", json={"name": "Green"}).json()
    wrong = owner.post(f"/api/boards/{another['id']}/sections", json={"name": "Elsewhere"}).json()
    pin_id = ready_pin(owner, "Green plant")
    save_url = f"/api/boards/{board['id']}/pins/{pin_id}"
    owner.post(save_url)
    assert owner.put(f"{save_url}/section", json={"section_id": wrong["id"]}).status_code == 404
    assert owner.put(f"{save_url}/section", json={"section_id": section["id"]}).status_code == 200
    assert (
        owner.get(f"/api/boards/{board['id']}/pins", params={"section_id": section["id"]}).json()[
            "items"
        ][0]["id"]
        == pin_id
    )
    assert other.delete(f"/api/boards/{board['id']}/sections/{section['id']}").status_code == 404
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            save = db.scalar(
                select(Save).where(Save.board_id == board["id"], Save.pin_id == pin_id)
            )
            save.section_id = wrong["id"]
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        engine.dispose()
    assert owner.delete(f"/api/boards/{board['id']}/sections/{section['id']}").status_code == 204
    assert owner.get(f"/api/boards/{board['id']}/pins").json()["items"][0]["id"] == pin_id


def test_block_and_mute_apply_to_existing_catalog_search_and_public_reads(clients):
    owner, other, public = clients(), clients(), clients(False)
    own_id = owner.get("/api/auth/me").json()["id"]
    other_id = other.get("/api/auth/me").json()["id"]
    word = f"forest{uuid4().hex}"
    pin_id = ready_pin(owner, word)
    board = other.post("/api/boards", json={"name": "Saved before blocking"}).json()
    assert other.post(f"/api/boards/{board['id']}/pins/{pin_id}").status_code == 200
    assert other.put(f"/api/social/users/{own_id}/mute").status_code == 200
    assert other.get("/api/search/pins", params={"q": word}).json()["items"] == []
    assert other.get(f"/api/pins/{pin_id}").status_code == 200
    assert other.delete(f"/api/social/users/{own_id}/mute").status_code == 204
    assert other.put(f"/api/social/users/{own_id}/follow").status_code == 200
    assert owner.put(f"/api/social/users/{other_id}/follow").status_code == 200
    assert other.put(f"/api/social/users/{own_id}/block").status_code == 200
    assert owner.get(f"/api/profiles/{other_id}").status_code == 404
    assert other.get(f"/api/pins/{pin_id}").status_code == 404
    assert other.get("/api/boards").json()[0]["pin_count"] == 0
    assert other.get(f"/api/boards/{board['id']}/pins").json()["items"] == []
    assert other.get(f"/api/media/{pin_id}/thumb.jpg").status_code == 404
    assert other.get("/api/search/pins", params={"q": word}).json()["items"] == []
    assert other.get("/api/search/suggest", params={"q": word[:-2]}).json()["items"] == []
    assert other.put(f"/api/social/users/{own_id}/follow").status_code == 404
    assert public.get(f"/api/pins/{pin_id}").status_code == 200
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(UserFollow)
                    .where(UserFollow.follower_id.in_([own_id, other_id]))
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.recipient_id.in_([own_id, other_id]))
                )
                == 0
            )
    finally:
        engine.dispose()
    assert other.delete(f"/api/social/users/{own_id}/block").status_code == 204
    assert other.get(f"/api/profiles/{own_id}").json()["is_following"] is False


def test_new_controls_enforce_auth_origin_and_explicit_pending_discovery(clients):
    owner, public = clients(), clients(False)
    own_id = owner.get("/api/auth/me").json()["id"]
    assert public.put(f"/api/social/users/{own_id}/follow").status_code == 401
    assert (
        owner.patch(
            "/api/profiles/me",
            json={"display_name": "Blocked origin"},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert public.get("/api/feed/following").status_code == 401
    page = owner.get("/api/feed/following")
    assert page.status_code == 200 and page.json()["items"] == []
    pin_id = ready_pin(owner, "Context pin")
    assert owner.get(f"/api/pins/{pin_id}/related").status_code == 200
    assert (
        owner.post("/api/lens", files={"image": ("bad.png", b"bad", "image/png")}).status_code
        == 422
    )
    valid = owner.post(
        "/api/lens",
        data={"crop_box": '{"right": 0.5}'},
        files={"image": ("crop.png", png_bytes(), "image/png")},
    )
    assert valid.status_code == 200 and valid.json()["request_id"]
