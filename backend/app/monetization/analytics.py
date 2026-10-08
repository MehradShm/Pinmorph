"""Rebuildable UTC-day aggregates from canonical accepted app event tables."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Date, case, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.logging.models import Engagement, FeedRequest, Impression, ServedItem
from app.models import Pin, User, utcnow
from app.monetization.models import PinDailyRollup

VERSION = "analytics:utc-day-canonical-events:v1"
METRICS = ("served", "impressions", "closeups", "saves", "outbound_clicks")


def days_between(start: date, end: date):
    if end < start or (end - start).days >= 366:
        raise ValueError("Choose an ordered range of at most 366 days")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def rebuild(db, start: date, end: date, *, owner_id=None, cutoff=None):
    days = days_between(start, end)
    cutoff = cutoff or utcnow()
    if cutoff.utcoffset() is None:
        raise ValueError("Receipt cutoff must be timezone aware")
    if end > cutoff.astimezone(UTC).date():
        raise ValueError("Future days cannot be aggregated")
    # Rebuilds can overlap. Serialize them; replacing counts makes replay retry-safe.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('analytics:daily:v1'))"))
    owned = select(Pin.id).join(User, User.id == Pin.owner_id).where(User.is_business.is_(True))
    if owner_id:
        owned = owned.where(Pin.owner_id == owner_id)
    pin_ids = list(db.scalars(owned))
    start_time = datetime.combine(start, time.min, UTC)
    end_time = datetime.combine(end + timedelta(days=1), time.min, UTC)
    counts = defaultdict(lambda: dict.fromkeys(METRICS, 0))

    def aggregate(statement, pin_column, event_time, receipt_time, sim_run_id, metric):
        day = func.timezone("UTC", event_time).cast(Date)
        traffic = case((sim_run_id.is_(None), "app"), else_="simulator")
        rows = db.execute(
            statement.with_only_columns(pin_column, day, traffic, func.count())
            .where(
                pin_column.in_(owned),
                event_time >= start_time,
                event_time < end_time,
                event_time <= cutoff,
                receipt_time <= cutoff,
            )
            .group_by(pin_column, day, traffic)
        )
        for pin_id, event_day, source, count in rows:
            counts[(pin_id, event_day, source)][metric] = count

    aggregate(
        select(ServedItem).join(FeedRequest, FeedRequest.request_id == ServedItem.request_id),
        ServedItem.pin_id,
        FeedRequest.served_at,
        FeedRequest.received_at,
        FeedRequest.sim_run_id,
        "served",
    )
    aggregate(
        select(Impression),
        Impression.pin_id,
        Impression.event_time,
        Impression.received_at,
        Impression.sim_run_id,
        "impressions",
    )
    for action, metric in (
        ("closeup", "closeups"),
        ("save", "saves"),
        ("outbound_click", "outbound_clicks"),
    ):
        aggregate(
            select(Engagement).where(Engagement.type == action),
            Engagement.pin_id,
            Engagement.event_time,
            Engagement.received_at,
            Engagement.sim_run_id,
            metric,
        )
    computed_at = utcnow()
    batch = []

    def flush():
        if batch:
            statement = insert(PinDailyRollup).values(batch)
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["pin_id", "day", "traffic"],
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in (*METRICS, "receipt_cutoff", "computed_at", "version")
                    },
                )
            )
            batch.clear()

    for pin_id in pin_ids:
        for day in days:
            for source in ("app", "simulator"):
                batch.append(
                    dict(
                        pin_id=pin_id,
                        day=day,
                        traffic=source,
                        **counts[(pin_id, day, source)],
                        receipt_cutoff=cutoff,
                        computed_at=computed_at,
                        version=VERSION,
                    )
                )
                if len(batch) == 500:
                    flush()
    flush()
    db.commit()
    return {"pin_count": len(pin_ids), "day_count": len(days), "computed_at": computed_at}


def report(db, owner_id, start, end, traffic, limit, cursor=None):
    rollup = PinDailyRollup
    window = (rollup.day >= start, rollup.day <= end, rollup.traffic == traffic)
    totals = db.execute(
        select(
            *[func.coalesce(func.sum(getattr(rollup, name)), 0) for name in METRICS],
            func.max(rollup.computed_at),
        )
        .join(Pin, Pin.id == rollup.pin_id)
        .where(Pin.owner_id == owner_id, *window)
    ).one()
    daily = db.execute(
        select(rollup.day, *[func.sum(getattr(rollup, name)) for name in METRICS], func.count())
        .join(Pin, Pin.id == rollup.pin_id)
        .where(Pin.owner_id == owner_id, *window)
        .group_by(rollup.day)
        .order_by(rollup.day)
    ).all()
    pin_count = db.scalar(select(func.count()).select_from(Pin).where(Pin.owner_id == owner_id))
    covered = {row[0] for row in daily if row[-1] == pin_count}
    missing_days = [day for day in days_between(start, end) if pin_count and day not in covered]
    statement = (
        select(
            Pin.id,
            Pin.title,
            *[func.coalesce(func.sum(getattr(rollup, name)), 0) for name in METRICS],
        )
        .outerjoin(rollup, (rollup.pin_id == Pin.id) & window[0] & window[1] & window[2])
        .where(Pin.owner_id == owner_id)
        .group_by(Pin.id, Pin.title)
        .order_by(Pin.id)
    )
    if cursor:
        statement = statement.where(Pin.id > cursor)
    items = db.execute(statement.limit(limit + 1)).all()
    return {
        "start": start,
        "end": end,
        "traffic": traffic,
        "version": VERSION,
        "latest_rollup_at": totals[-1],
        "totals": dict(zip(METRICS, totals[:-1], strict=True)),
        "missing_days": missing_days,
        "daily": [dict(day=row[0], **dict(zip(METRICS, row[1:-1], strict=True))) for row in daily],
        "items": [
            dict(pin_id=row[0], title=row[1], **dict(zip(METRICS, row[2:], strict=True)))
            for row in items[:limit]
        ],
        "next_cursor": items[limit - 1][0] if len(items) > limit else None,
    }
