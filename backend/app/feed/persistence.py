"""Every ranked surface uses the same atomic request/item/feature writer."""

from sqlalchemy.orm import Session

from app.feed.contracts import FeedContext, RankedCandidate
from app.feed.schemas import FeedItem, FeedPage
from app.logging.models import FeedRequest, ServedFeature, ServedItem
from app.models import utcnow


def record_page(
    db: Session,
    context: FeedContext,
    rows: list[RankedCandidate],
    *,
    versions: dict[str, str],
    config_version: str,
    arms: dict[str, str] | None = None,
    details: dict | None = None,
    next_cursor: str | None = None,
    feature_schema: str = "features:baseline:v1",
) -> FeedPage:
    from app.api import pin_out

    served_at = utcnow()
    db.add(
        FeedRequest(
            request_id=context.request_id,
            user_id=context.user_id,
            surface=context.surface,
            context=details or {},
            experiment_arms=arms or {},
            model_versions=versions,
            config_version=config_version,
            latency_ms=max(0, (served_at - context.received_at).total_seconds() * 1000),
            served_at=served_at,
            received_at=context.received_at,
        )
    )
    db.flush()
    for position, row in enumerate(rows):
        candidate = row.candidate
        db.add(
            ServedItem(
                request_id=context.request_id,
                pin_id=candidate.pin.id,
                position=position,
                candidate_sources=list(candidate.sources),
                retrieval_score=candidate.retrieval_score,
                rank_score=row.rank_score,
                final_score=row.final_score,
            )
        )
    db.flush()
    for row in rows:
        db.add(
            ServedFeature(
                request_id=context.request_id,
                pin_id=row.candidate.pin.id,
                features=row.candidate.features,
                feature_schema_version=feature_schema,
                feature_as_of=context.as_of,
            )
        )
    db.commit()
    return FeedPage(
        request_id=context.request_id,
        items=[FeedItem(pin=pin_out(row.candidate.pin), position=i) for i, row in enumerate(rows)],
        next_cursor=next_cursor,
        model_versions=versions,
        config_version=config_version,
        experiment_arms=arms or {},
    )
