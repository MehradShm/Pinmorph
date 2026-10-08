from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.logging.models import Engagement, EventReceipt, Impression
from app.models import ImportedInteraction, Pin, User
from app.social.policy import visible_owner


class CatalogCandidateSource:
    version = "candidate:catalog:v1"

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        viewer = db.get(User, context.user_id)
        pins = db.scalars(
            select(Pin).where(
                Pin.status == "ready",
                Pin.available_at <= context.as_of,
                Pin.created_at <= context.as_of,
                visible_owner(Pin.owner_id, viewer, include_muted=True),
            )
        ).all()
        from app.product.models import HiddenPin

        hidden = set(
            db.scalars(select(HiddenPin.pin_id).where(HiddenPin.user_id == context.user_id))
        )

        def counts(model, extra=()):
            return dict(
                db.execute(
                    select(model.pin_id, func.count(func.distinct(model.user_id)))
                    .where(
                        model.event_time < context.as_of,
                        model.received_at < context.as_of,
                        *extra,
                    )
                    .group_by(model.pin_id)
                ).all()
            )

        saves = counts(
            Engagement,
            (
                Engagement.type == "save",
                Engagement.attribution_status != "pending",
                ~exists(
                    select(Impression.event_id).where(
                        Impression.event_id == Engagement.impression_event_id,
                        Impression.received_at >= context.as_of,
                    )
                ),
                ~exists(
                    select(EventReceipt.event_id).where(
                        EventReceipt.event_id == Engagement.referenced_impression_event_id,
                        EventReceipt.received_at >= context.as_of,
                    )
                ),
            ),
        )
        purchases = counts(ImportedInteraction)
        return [
            Candidate(
                pin,
                (self.version,),
                {
                    "age_hours": max(0, (context.as_of - pin.available_at).total_seconds() / 3600),
                    "observed_save_count": saves.get(pin.id, 0),
                    "imported_purchase_count": purchases.get(pin.id, 0),
                },
            )
            for pin in pins
            if pin.id not in hidden
        ]


class RecencyRanker:
    version = "ranker:recency:v1"

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]:
        ordered = sorted(candidates, key=lambda c: (c.features["age_hours"], c.pin.id))
        return [
            RankedCandidate(c, -c.features["age_hours"], -c.features["age_hours"]) for c in ordered
        ]


class PopularityRanker:
    version = "ranker:popularity:v1"

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]:
        def score(c):
            return c.features["observed_save_count"] + c.features["imported_purchase_count"]

        ordered = sorted(candidates, key=lambda c: (-score(c), c.features["age_hours"], c.pin.id))
        return [RankedCandidate(c, score(c), score(c)) for c in ordered]


class IdentityReranker:
    version = "reranker:identity:v1"

    def rerank(
        self, candidates: list[RankedCandidate], context: FeedContext
    ) -> list[RankedCandidate]:
        return list(candidates)
