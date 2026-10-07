"""Exercise Phase 1 against the real database, object store, and Linux RQ worker."""

import io
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, token_digest
from app.config import Settings
from app.database import make_engine
from app.main import create_app
from app.media import enqueue_pin
from app.models import AuthSession, ImportedInteraction, ImportRun, Pin, Save, User
from app.storage import make_s3_client
from scripts.seed import build_hm_plan, import_plan

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


def png_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (1800, 900), "#507c44").save(stream, "PNG")
    return stream.getvalue()


def wait_ready(client, pin_id, seconds=40):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        response = client.get(f"/api/pins/{pin_id}")
        if response.status_code == 200 and response.json()["status"] == "ready":
            return response.json()
        sleep(0.1)
    pytest.fail(f"Worker did not finish pin {pin_id}: {response.json()}")


def delete_pin_objects(storage, bucket, pin_id):
    result = storage.list_objects_v2(Bucket=bucket, Prefix=f"pins/{pin_id}/")
    for item in result.get("Contents", []):
        storage.delete_object(Bucket=bucket, Key=item["Key"])


@pytest.fixture
def clients():
    settings = Settings()
    prefix = f"test-{uuid4()}"
    with ExitStack() as stack:

        def make_client(authenticated=True):
            client = stack.enter_context(TestClient(create_app(settings)))
            if authenticated:
                response = client.post(
                    "/api/auth/signup",
                    json={
                        "email": f"{prefix}-{uuid4()}@example.test",
                        "password": "test-password-123",
                        "display_name": "Integration tester",
                    },
                )
                assert response.status_code == 201, response.json()
            return client

        yield make_client
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    try:
        with Session(engine) as db:
            users = list(db.scalars(select(User.id).where(User.email.like(f"{prefix}%"))))
            pins = list(db.scalars(select(Pin.id).where(Pin.owner_id.in_(users))))
            for pin_id in pins:
                delete_pin_objects(storage, settings.s3_bucket, pin_id)
            db.execute(delete(Pin).where(Pin.id.in_(pins)))
            db.execute(delete(User).where(User.id.in_(users)))
            db.commit()
    finally:
        engine.dispose()
        storage.close()


def test_signup_login_logout_expiry_and_origin_check(clients):
    client = clients()
    me = client.get("/api/auth/me").json()
    assert me["display_name"] == "Integration tester"
    token = client.cookies.get(COOKIE_NAME)
    settings = Settings()
    engine = make_engine(settings)
    try:
        with Session(engine) as db:
            user = db.get(User, me["id"])
            assert user.password_hash.startswith("$argon2id$")
            assert user.password_hash != "test-password-123"
            session = db.get(AuthSession, token_digest(token))
            assert session and session.token_hash != token
        assert (
            client.post(
                "/api/boards",
                json={"name": "Blocked"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        duplicate = client.post(
            "/api/auth/signup",
            json={
                "email": me["email"].upper(),
                "password": "test-password-123",
                "display_name": "Duplicate",
            },
        )
        assert duplicate.status_code == 409
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/me").status_code == 401
        body = {"email": me["email"], "password": "wrong-password"}
        assert client.post("/api/auth/login", json=body).status_code == 401
        body["password"] = "test-password-123"
        login = client.post("/api/auth/login", json=body)
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=lax" in login.headers["set-cookie"]
        new_token = client.cookies.get(COOKIE_NAME)
        assert new_token != token
        with Session(engine) as db:
            session = db.get(AuthSession, token_digest(new_token))
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/auth/me").status_code == 401
    finally:
        engine.dispose()


def test_upload_worker_media_save_unsave_and_board_ownership(clients):
    owner, other, anonymous = clients(), clients(), clients(False)
    assert anonymous.post("/api/boards", json={"name": "No account"}).status_code == 401
    response = owner.post(
        "/api/pins",
        data={"title": "Worker test", "source_url": "https://example.com/product"},
        files={"image": ("test.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 202, response.json()
    pin_id = response.json()["id"]
    pin = wait_ready(owner, pin_id)
    assert (pin["width"], pin["height"], pin["dominant_color"]) == (1800, 900, "#507c44")
    assert pin["source_url"] == "https://example.com/product"
    assert anonymous.get(f"/api/pins/{pin_id}").status_code == 200
    for field, size in {"thumbnail_url": (400, 200), "image_url": (1200, 600)}.items():
        media = anonymous.get(pin[field])
        assert media.status_code == 200
        assert media.headers["content-type"] == "image/jpeg"
        with Image.open(io.BytesIO(media.content)) as image:
            assert image.size == size
    board = owner.post("/api/boards", json={"name": "Favorites"}).json()
    assert other.get(f"/api/boards/{board['id']}/pins").status_code == 404
    save_url = f"/api/boards/{board['id']}/pins/{pin_id}"
    assert other.post(save_url).status_code == 404
    first, retry = owner.post(save_url), owner.post(save_url)
    assert first.json()["id"] == retry.json()["id"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        simultaneous = list(executor.map(lambda _: owner.post(save_url), range(4)))
    assert all(response.status_code == 200 for response in simultaneous)
    assert {response.json()["id"] for response in simultaneous} == {first.json()["id"]}
    assert owner.get("/api/boards").json()[0]["pin_count"] == 1
    assert owner.get(f"/api/boards/{board['id']}/pins").json()["items"][0]["id"] == pin_id
    assert owner.delete(save_url).status_code == 204
    assert owner.delete(save_url).status_code == 204
    assert owner.get("/api/boards").json()[0]["pin_count"] == 0


def test_future_items_cannot_be_browsed_or_saved(clients):
    owner, public = clients(), clients(False)
    settings = Settings()
    engine = make_engine(settings)
    pin_id = str(uuid4())
    try:
        with Session(engine) as db:
            db.add(
                Pin(
                    id=pin_id,
                    owner_id=owner.get("/api/auth/me").json()["id"],
                    title="Future item",
                    status="ready",
                    original_key=f"pins/{pin_id}/original",
                    available_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            db.commit()
        assert public.get(f"/api/pins/{pin_id}").status_code == 404
        assert public.get(f"/api/media/{pin_id}/thumb.jpg").status_code == 404
        assert all(pin["id"] != pin_id for pin in public.get("/api/pins").json()["items"])
        board = owner.post("/api/boards", json={"name": "Future collection"}).json()
        assert owner.post(f"/api/boards/{board['id']}/pins/{pin_id}").status_code == 404
    finally:
        engine.dispose()


def test_bad_uploads_and_sources_are_rejected(clients):
    client = clients()
    assert (
        client.post(
            "/api/pins",
            data={"title": "Invalid"},
            files={"image": ("bad.jpg", b"not image", "image/jpeg")},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/pins",
            data={"title": "Invalid", "source_url": "javascript:alert(1)"},
            files={"image": ("test.png", png_bytes(), "image/png")},
        ).status_code
        == 422
    )
    assert client.get("/api/pins?cursor=bad").status_code == 422
    assert client.get("/api/pins?limit=101").status_code == 422


def test_queue_failure_is_visible_and_owner_can_retry(clients, monkeypatch):
    owner, other = clients(), clients()
    queue = owner.app.state.queue
    with monkeypatch.context() as patch:

        def queue_down(*args, **kwargs):
            raise ConnectionError("queue unavailable")

        patch.setattr(queue, "enqueue", queue_down)
        response = owner.post(
            "/api/pins",
            data={"title": "Recoverable upload"},
            files={"image": ("test.png", png_bytes(), "image/png")},
        )
    assert response.status_code == 503
    pin_id = response.json()["detail"]["pin_id"]
    assert owner.get(f"/api/pins/{pin_id}").json()["status"] == "failed"
    assert other.get(f"/api/pins/{pin_id}").status_code == 404
    assert other.post(f"/api/pins/{pin_id}/retry").status_code == 404
    assert owner.post(f"/api/pins/{pin_id}/retry").status_code == 202
    wait_ready(owner, pin_id)
    assert owner.post(f"/api/pins/{pin_id}/retry").status_code == 409


def test_worker_retries_after_a_transient_missing_object(clients):
    client = clients()
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    connection = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        with Session(engine) as db:
            user_id = client.get("/api/auth/me").json()["id"]
            pin_id = str(uuid4())
            key = f"pins/{pin_id}/original"
            pin = Pin(id=pin_id, owner_id=user_id, title="Transient storage test", original_key=key)
            db.add(pin)
            db.commit()
            queue = Queue("default", connection=connection, serializer=JSONSerializer)
            job = enqueue_pin(db, queue, pin)
        deadline = monotonic() + 30
        while monotonic() < deadline:
            job.refresh()
            if job.retries_left < 3:
                break
            sleep(0.05)
        else:
            pytest.fail("Worker never attempted the missing-object job")
        storage.put_object(Bucket=settings.s3_bucket, Key=key, Body=png_bytes())
        wait_ready(client, pin_id, 45)
        job.refresh()
        assert job.return_value() == "ready"
    finally:
        connection.close()
        storage.close()
        engine.dispose()


def test_catalog_paginates_without_duplicates(clients):
    owner = clients()
    ids = []
    for index in range(3):
        response = owner.post(
            "/api/pins",
            data={"title": f"Pagination {index}"},
            files={"image": ("test.png", png_bytes(), "image/png")},
        )
        ids.append(response.json()["id"])
    for pin_id in ids:
        wait_ready(owner, pin_id)
    first = owner.get("/api/pins/mine?limit=2").json()
    second = owner.get("/api/pins/mine", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {p["id"] for p in first["items"] + second["items"]} == set(ids)
    assert second["next_cursor"] is None
    assert first["request_id"] != second["request_id"]


def test_hm_fixture_import_is_repeatable_and_keeps_purchases_separate(hm_folder, clients):
    plan = build_hm_plan(hm_folder, 42, datetime(2026, 10, 7, tzinfo=UTC), 10, 10)
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    client = clients(False)
    try:
        import_plan(plan, settings)
        for item in plan.articles:
            wait_ready(client, plan.entity_id("article", item))
        import_plan(plan, settings)
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count()).select_from(Pin).where(Pin.import_run_id == plan.run_id)
                )
                == 2
            )
            interactions = list(
                db.scalars(
                    select(ImportedInteraction).where(
                        ImportedInteraction.import_run_id == plan.run_id
                    )
                )
            )
            assert len(interactions) == 5
            assert all(p.label_provenance == "imported_purchase_proxy" for p in interactions)
            assert all(p.event_time == p.original_event_time for p in interactions)
            users = list(
                db.scalars(
                    select(User).where(
                        User.id.in_(
                            [plan.entity_id("customer", customer) for customer in plan.customers]
                        )
                    )
                )
            )
            assert all(u.password_hash is None and u.email is None for u in users)
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Save)
                    .where(
                        Save.pin_id.in_([plan.entity_id("article", item) for item in plan.articles])
                    )
                )
                == 0
            )
    finally:
        with Session(engine) as db:
            for item in plan.articles:
                delete_pin_objects(storage, settings.s3_bucket, plan.entity_id("article", item))
            db.execute(
                delete(ImportedInteraction).where(ImportedInteraction.import_run_id == plan.run_id)
            )
            db.execute(delete(Pin).where(Pin.import_run_id == plan.run_id))
            db.execute(
                delete(User).where(
                    User.id.in_(
                        [plan.entity_id("customer", customer) for customer in plan.customers]
                    )
                )
            )
            db.execute(delete(ImportRun).where(ImportRun.id == plan.run_id))
            db.commit()
        storage.close()
        engine.dispose()
