from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select

from app.api import pin_out
from app.auth import DB, CurrentUser, OptionalUser, check_origin
from app.models import Pin, User, utcnow
from app.monetization.analytics import rebuild, report
from app.monetization.models import PinProduct
from app.monetization.schemas import AnalyticsWindow, BusinessInput, Currency, ProductInput, Traffic
from app.monetization.shopping import ShopQuery
from app.schemas import PinOut, PinPage
from app.search.service import SearchQuery, decode_cursor, eligible, encode_cursor

router = APIRouter(prefix="/api")
mutations = [Depends(check_origin)]


def business_user(user):
    if not user.is_business:
        raise HTTPException(403, "Enable a business account first")


def business_out(user):
    return {
        "is_business": user.is_business,
        "business_name": user.business_name,
        "website": user.business_website,
    }


@router.get("/business/profile")
def get_business(user: CurrentUser):
    return business_out(user)


@router.put("/business/profile", dependencies=mutations)
def put_business(body: BusinessInput, user: CurrentUser, db: DB):
    user = db.scalar(select(User).where(User.id == user.id).with_for_update())
    user.is_business = True
    user.business_name = body.business_name
    user.business_website = str(body.website) if body.website else None
    db.commit()
    return business_out(user)


def owned_pin(db, user, pin_id):
    business_user(user)
    pin = db.scalar(select(Pin).where(Pin.id == pin_id, Pin.owner_id == user.id).with_for_update())
    if pin is None:
        raise HTTPException(404, "Your pin was not found")
    return pin


@router.put("/pins/{pin_id}/product", response_model=PinOut, dependencies=mutations)
def put_product(pin_id: UUID, body: ProductInput, user: CurrentUser, db: DB):
    pin = owned_pin(db, user, str(pin_id))
    product = pin.product
    if product is None:
        product = PinProduct(pin_id=pin.id)
        db.add(product)
    product.price = body.price
    product.currency = body.currency
    product.availability = body.availability
    product.merchant_url = str(body.merchant_url)
    product.updated_at = utcnow()
    db.commit()
    return pin_out(pin)


@router.delete("/pins/{pin_id}/product", status_code=204, dependencies=mutations)
def delete_product(pin_id: UUID, user: CurrentUser, db: DB):
    pin = owned_pin(db, user, str(pin_id))
    if pin.product:
        db.delete(pin.product)
        db.commit()


class ShopPage(PinPage):
    attributed: bool
    model_versions: dict[str, str]


@router.get("/shop/pins", response_model=ShopPage)
def shop_pins(
    request: Request,
    db: DB,
    user: OptionalUser,
    q: Annotated[str, Query(max_length=200)] = "",
    currency: Currency | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=600)] = None,
):
    try:
        query = ShopQuery(q=q, currency=currency, viewer_id=user.id if user else None)
    except ValidationError as exc:
        raise HTTPException(422, "Use at least two characters for product search") from exc
    now = utcnow()
    # Search eligibility supplies ready/time/block/mute/hide policy for both paths.
    statement = eligible(SearchQuery(q=query.q or "shop", shop_only=True), user, now)
    if query.q:
        statement = statement.where(
            Pin.search_document.op("@@")(func.plainto_tsquery("english", query.q))
        )
    if query.currency:
        statement = statement.where(Pin.product.has(PinProduct.currency == query.currency))
    if cursor:
        try:
            timestamp, pin_id = decode_cursor(cursor, query)
        except ValueError as exc:
            raise HTTPException(422, "Invalid cursor for these Shop filters") from exc
        statement = statement.where(
            or_(Pin.created_at < timestamp, and_(Pin.created_at == timestamp, Pin.id < pin_id))
        )
    pins = list(
        db.scalars(statement.order_by(Pin.created_at.desc(), Pin.id.desc()).limit(limit + 1))
    )
    next_cursor = encode_cursor(query, pins[limit - 1]) if len(pins) > limit else None
    pins = pins[:limit]
    versions = {"shop": "shop:postgres-products-recency:v1"}
    if user:
        from app.feed.contracts import Candidate, FeedContext, RankedCandidate
        from app.feed.persistence import record_page

        rows = [RankedCandidate(Candidate(pin, (versions["shop"],), {}), 0, 0) for pin in pins]
        record_page(
            db,
            FeedContext(request.state.request_id, user.id, now, now, surface="shop"),
            rows,
            versions=versions,
            config_version="shop-config:v1",
            details={"query_fingerprint": query.fingerprint()},
            next_cursor=next_cursor,
            feature_schema="features:shop:v1",
        )
    return ShopPage(
        items=[pin_out(pin) for pin in pins],
        next_cursor=next_cursor,
        request_id=request.state.request_id,
        attributed=bool(user),
        model_versions=versions,
    )


@router.get("/ads/layout")
def ad_layout(request: Request):
    # These are empty UI placements. They create no ad or recommendation exposure events.
    return request.app.state.settings.ads_config


def analytics_window(start, end):
    today = utcnow().date()
    try:
        window = AnalyticsWindow(start=start or today - timedelta(days=6), end=end or today)
        if window.end > today:
            raise ValueError("Future days cannot be requested")
    except ValueError as exc:
        raise HTTPException(422, "Choose a past/current UTC range of at most 90 days") from exc
    return window


@router.get("/business/analytics")
def get_analytics(
    db: DB,
    user: CurrentUser,
    start: date | None = None,
    end: date | None = None,
    traffic: Traffic = "app",
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: UUID | None = None,
):
    business_user(user)
    window = analytics_window(start, end)
    return report(
        db, user.id, window.start, window.end, traffic, limit, str(cursor) if cursor else None
    )


@router.post("/business/analytics/refresh", dependencies=mutations)
def refresh_analytics(
    db: DB,
    user: CurrentUser,
    start: date | None = None,
    end: date | None = None,
):
    business_user(user)
    window = analytics_window(start, end)
    return rebuild(db, window.start, window.end, owner_id=user.id)
