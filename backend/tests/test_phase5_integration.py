import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_phase4_integration import ready_pin

from app.config import Settings
from app.database import make_engine
from app.logging.models import Engagement, FeedRequest, Impression
from app.models import Pin, utcnow
from app.monetization.analytics import rebuild
from app.monetization.models import PinDailyRollup

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Real database"),
]
PRODUCT = {
    "price": "29.90",
    "currency": "CAD",
    "availability": "in_stock",
    "merchant_url": "https://shop.example.test/item",
}


def business(client):
    result = client.put(
        "/api/business/profile",
        json={"business_name": "Local studio", "website": "https://shop.example.test"},
    )
    assert result.status_code == 200, result.text


def attach(client, pin_id, **changes):
    result = client.put(f"/api/pins/{pin_id}/product", json=dict(PRODUCT, **changes))
    assert result.status_code == 200, result.text
    return result.json()


def test_business_conversion_product_ownership_and_public_fields(clients):
    owner, other, guest = clients(), clients(), clients(False)
    pin_id = ready_pin(owner, "Business fixture")
    assert owner.get("/api/auth/me").json()["is_business"] is False
    assert owner.put(f"/api/pins/{pin_id}/product", json=PRODUCT).status_code == 403
    assert guest.put("/api/business/profile", json={"business_name": "Guest"}).status_code == 401
    assert (
        owner.put(
            "/api/business/profile",
            json={"business_name": "Bad origin"},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    business(owner)
    business(other)
    me = owner.get("/api/auth/me").json()
    assert me["is_business"] and not me["is_moderator"]
    public = guest.get(f"/api/profiles/{me['id']}").json()
    assert public["business"]["name"] == "Local studio" and "email" not in public
    assert other.put(f"/api/pins/{pin_id}/product", json=PRODUCT).status_code == 404
    assert other.delete(f"/api/pins/{pin_id}/product").status_code == 404
    assert attach(owner, pin_id)["product"]["price"] == "29.90"
    assert guest.get(f"/api/pins/{pin_id}").json()["product"]["currency"] == "CAD"
    assert owner.get("/api/pins/mine").json()["items"][0]["product"]
    assert owner.delete(f"/api/pins/{pin_id}/product").status_code == 204
    assert owner.delete(f"/api/pins/{pin_id}/product").status_code == 204
    assert guest.get(f"/api/pins/{pin_id}").json()["product"] is None


def test_shop_filters_pagination_attribution_and_visibility(clients):
    owner, viewer, guest = clients(), clients(), clients(False)
    business(owner)
    word = "shopfixture" + uuid4().hex
    pins = {ready_pin(owner, word + " chair " + str(i)) for i in range(3)}
    for pin in pins:
        attach(owner, pin)
    unavailable = ready_pin(owner, word + " sold out")
    attach(owner, unavailable, availability="out_of_stock")
    future = ready_pin(owner, word + " future", future=True)
    attach(owner, future)
    ordinary = ready_pin(owner, word + " ordinary")
    usd = ready_pin(owner, word + " USD")
    attach(owner, usd, currency="USD")
    first = viewer.get("/api/shop/pins", params={"q": word, "currency": "CAD", "limit": 2}).json()
    assert first["attributed"] and first["next_cursor"]
    second = viewer.get(
        "/api/shop/pins",
        params={"q": word, "currency": "CAD", "limit": 2, "cursor": first["next_cursor"]},
    ).json()
    assert {p["id"] for p in first["items"] + second["items"]} == pins
    assert ordinary not in {p["id"] for p in first["items"] + second["items"]}
    assert (
        viewer.get(
            "/api/shop/pins", params={"q": word, "currency": "USD", "cursor": first["next_cursor"]}
        ).status_code
        == 422
    )
    assert (
        guest.get(
            "/api/shop/pins", params={"q": word, "currency": "CAD", "cursor": first["next_cursor"]}
        ).status_code
        == 422
    )
    assert not guest.get("/api/shop/pins", params={"q": word}).json()["attributed"]
    filtered = viewer.get("/api/search/pins", params={"q": word, "shop_only": True}).json()
    assert {p["id"] for p in filtered["items"]} == pins | {usd}
    assert (
        word + " sold out"
        not in viewer.get("/api/search/suggest", params={"q": word, "shop_only": True}).json()[
            "items"
        ]
    )
    owner_id = owner.get("/api/auth/me").json()["id"]
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            request = db.get(FeedRequest, first["request_id"])
            assert request.surface == "shop"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Impression)
                    .where(Impression.request_id == request.request_id)
                )
                == 0
            )
    finally:
        engine.dispose()
    hidden = next(iter(pins))
    viewer.put(f"/api/pins/{hidden}/hide")
    assert hidden not in {
        p["id"] for p in viewer.get("/api/shop/pins", params={"q": word}).json()["items"]
    }
    viewer.put(f"/api/social/users/{owner_id}/mute")
    assert viewer.get("/api/shop/pins", params={"q": word}).json()["items"] == []
    viewer.delete(f"/api/social/users/{owner_id}/mute")
    viewer.put(f"/api/social/users/{owner_id}/block")
    assert viewer.get("/api/shop/pins", params={"q": word}).json()["items"] == []


def test_shop_removal_and_owner_deletion_never_leave_active_products(clients):
    owner, guest = clients(), clients(False)
    business(owner)
    word = "removedshop" + uuid4().hex
    pin_id = ready_pin(owner, word)
    attach(owner, pin_id)
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            pin = db.get(Pin, pin_id)
            pin.status = "quarantined"
            db.commit()
        assert guest.get("/api/shop/pins", params={"q": word}).json()["items"] == []
        with Session(engine) as db:
            pin = db.get(Pin, pin_id)
            pin.status, pin.owner_id = "ready", None
            db.commit()
        assert guest.get("/api/shop/pins", params={"q": word}).json()["items"] == []
        assert guest.get(f"/api/pins/{pin_id}").json()["product"] is None
    finally:
        # This fixture deliberately detached its pin; remove that exact row here.
        with Session(engine) as db:
            db.execute(text("DELETE FROM pins WHERE id = :id"), {"id": pin_id})
            db.commit()
        engine.dispose()


def test_daily_rollups_deduplicate_views_and_split_simulator_traffic(clients):
    owner, viewer, other = clients(), clients(), clients()
    business(owner)
    business(other)
    word = "analytics" + uuid4().hex
    pin_id = ready_pin(owner, word)
    zero = ready_pin(owner, "Zero activity")
    page = viewer.get("/api/search/pins", params={"q": word}).json()
    impression = {
        "kind": "impression",
        "event_id": str(uuid4()),
        "pin_id": pin_id,
        "request_id": page["request_id"],
        "position": 0,
        "view_rule_version": "viewport:50pct:1000ms:v1",
    }
    assert viewer.post("/api/events", json=impression).json()["outcome"] == "accepted"
    assert viewer.post("/api/events", json=impression).json()["outcome"] == "duplicate"
    assert (
        viewer.post("/api/events", json=dict(impression, event_id=str(uuid4()))).json()["outcome"]
        == "duplicate_view"
    )
    for action in ("save", "closeup", "outbound_click"):
        event = {
            "kind": "engagement",
            "event_id": str(uuid4()),
            "pin_id": pin_id,
            "type": action,
            "request_id": page["request_id"],
            "position": 0,
            "impression_event_id": impression["event_id"],
        }
        assert viewer.post("/api/events", json=event).json()["outcome"] == "accepted"
        assert viewer.post("/api/events", json=event).json()["outcome"] == "duplicate"
    # Ordinary board state is not a second source of analytics save counts.
    board = viewer.post("/api/boards", json={"name": "Secret board"}).json()
    viewer.post(f"/api/boards/{board['id']}/pins/{pin_id}")
    simulated_page = viewer.get("/api/search/pins", params={"q": word}).json()
    simulated_view = dict(
        impression, event_id=str(uuid4()), request_id=simulated_page["request_id"]
    )
    viewer.post("/api/events", json=simulated_view)
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            run_id = str(uuid4())
            db.get(FeedRequest, simulated_page["request_id"]).sim_run_id = run_id
            db.get(Impression, simulated_view["event_id"]).sim_run_id = run_id
            db.commit()
        assert owner.post("/api/business/analytics/refresh").status_code == 200
        result = owner.get("/api/business/analytics").json()
        assert result["totals"] == {
            "served": 1,
            "impressions": 1,
            "closeups": 1,
            "saves": 1,
            "outbound_clicks": 1,
        }
        assert any(row["pin_id"] == zero and row["impressions"] == 0 for row in result["items"])
        owner.post("/api/business/analytics/refresh")
        assert owner.get("/api/business/analytics").json()["totals"] == result["totals"]
        sim = owner.get("/api/business/analytics?traffic=simulator").json()
        assert sim["totals"]["impressions"] == sim["totals"]["served"] == 1
        assert sim["totals"]["saves"] == 0
        assert other.get("/api/business/analytics").json()["totals"]["impressions"] == 0
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(PinDailyRollup)
                    .where(PinDailyRollup.pin_id == pin_id)
                )
                == 14
            )
    finally:
        engine.dispose()


def test_rollup_rebuild_repairs_late_receipts_on_the_original_utc_day(clients):
    owner, viewer = clients(), clients()
    business(owner)
    pin_id = ready_pin(owner, "Late receipt")
    event_id = str(uuid4())
    viewer.post(
        "/api/events",
        json={"kind": "engagement", "type": "closeup", "pin_id": pin_id, "event_id": event_id},
    )
    now = utcnow()
    yesterday = now.date() - timedelta(days=1)
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            event = db.get(Engagement, event_id)
            event.event_time = now - timedelta(days=1)
            event.received_at = now - timedelta(seconds=1)
            db.commit()
            rebuild(
                db,
                yesterday,
                yesterday,
                owner_id=owner.get("/api/auth/me").json()["id"],
                cutoff=now - timedelta(seconds=2),
            )
            row = db.get(PinDailyRollup, (pin_id, yesterday, "app"))
            assert row.closeups == 0
            rebuild(
                db,
                yesterday,
                yesterday,
                owner_id=owner.get("/api/auth/me").json()["id"],
                cutoff=now,
            )
            db.refresh(row)
            assert row.closeups == 1
    finally:
        engine.dispose()


def test_analytics_permissions_ranges_and_ad_configuration(clients):
    personal, guest = clients(), clients(False)
    assert guest.get("/api/business/analytics").status_code == 401
    assert personal.get("/api/business/analytics").status_code == 403
    assert personal.post("/api/business/analytics/refresh").status_code == 403
    business(personal)
    assert (
        personal.get("/api/business/analytics?start=2026-01-01&end=2026-12-31").status_code == 422
    )
    assert personal.get("/api/business/analytics?traffic=combined").status_code == 422
    layout = guest.get("/api/ads/layout").json()
    assert layout["version"] == "ads:placeholders:v1"
    assert layout["after_every"] == 8 and layout["max_slots"] == 2
