from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.monetization.analytics import days_between
from app.monetization.schemas import AdsConfig, AnalyticsWindow, BusinessInput, ProductInput
from app.monetization.shopping import ShopQuery
from app.search.service import SearchQuery, decode_cursor, encode_cursor


@pytest.mark.parametrize(
    "patch",
    [
        {"price": "0"},
        {"price": "-1"},
        {"price": "12.345"},
        {"price": "10000000000"},
        {"price": "NaN"},
        {"currency": "XXX"},
        {"merchant_url": "javascript:alert(1)"},
        {"merchant_url": "https://user:pass@example.test/"},
        {"availability": "unknown"},
        {"owner_id": "someone-else"},
    ],
)
def test_product_rejects_invalid_prices_links_and_fields(patch):
    with pytest.raises(ValidationError):
        ProductInput(
            **dict(
                {"price": "19.99", "currency": "CAD", "merchant_url": "https://example.test/item"},
                **patch,
            )
        )


def test_business_and_product_normalization():
    assert BusinessInput(business_name="  Studio  ").business_name == "Studio"
    product = ProductInput(price="19.90", currency="CAD", merchant_url="https://example.test")
    assert product.model_dump(mode="json")["price"] == "19.90"
    with pytest.raises(ValidationError):
        BusinessInput(business_name="  ")


def test_shop_cursors_bind_filters_and_viewer():
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from uuid import uuid4

    query = ShopQuery(q="  GARDEN   Chair ", currency="CAD", viewer_id=str(uuid4()))
    assert query.q == "garden chair"
    pin = SimpleNamespace(id=str(uuid4()), created_at=datetime.now(UTC))
    cursor = encode_cursor(query, pin)
    assert decode_cursor(cursor, query)[1] == pin.id
    for replacement in (
        query.model_copy(update={"currency": "USD"}),
        ShopQuery(),
        query.model_copy(update={"viewer_id": str(uuid4())}),
        SearchQuery(q=query.q),
    ):
        with pytest.raises(ValueError):
            decode_cursor(cursor, replacement)


def test_rollup_and_analytics_windows_are_bounded():
    start = date(2026, 1, 1)
    assert len(days_between(start, start + timedelta(days=6))) == 7
    with pytest.raises(ValueError):
        days_between(start, start - timedelta(days=1))
    with pytest.raises(ValueError):
        days_between(start, start + timedelta(days=366))
    with pytest.raises(ValidationError):
        AnalyticsWindow(start=start, end=start + timedelta(days=90))
    with pytest.raises(ValidationError):
        AdsConfig(after_every=0)
    assert AdsConfig(enabled=False, max_slots=0).max_slots == 0
