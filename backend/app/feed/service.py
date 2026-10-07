from sqlalchemy.orm import Session

from app.experiments.config import FeedConfig
from app.feed.contracts import CandidateSource, FeedContext, Ranker, Reranker
from app.feed.registry import Registry
from app.feed.schemas import FeedPage
from app.learning import LearningExercisePending
from app.ml.baselines import (
    CatalogCandidateSource,
    IdentityReranker,
    PopularityRanker,
    RecencyRanker,
)


class FeedService:
    def __init__(self, config: FeedConfig):
        self.config = config
        self.sources: Registry[CandidateSource] = Registry()
        self.rankers: Registry[Ranker] = Registry()
        self.rerankers: Registry[Reranker] = Registry()
        self.sources.register(CatalogCandidateSource.version, CatalogCandidateSource())
        self.rankers.register(RecencyRanker.version, RecencyRanker())
        self.rankers.register(PopularityRanker.version, PopularityRanker())
        self.rerankers.register(IdentityReranker.version, IdentityReranker())
        self.sources.resolve(config.candidate_source)
        self.rerankers.resolve(config.reranker)
        for arm in config.experiment.arms:
            self.rankers.resolve(arm.ranker)

    def serve(self, db: Session, context: FeedContext) -> FeedPage:
        """Assign → retrieve → deduplicate → rank → rerank → page → atomically record.

        Use the selected components' actual versions. Each page has a fresh request ID
        and positions starting at zero. Do not return until the request, served list, and
        full feature snapshots commit together. Serving must never insert impressions.
        Cursor exercise: carry user, config, arm and offset; reject mismatched config/arm/user.
        Keep server UTC authoritative. V1 refreshes live features between pages and documents
        that activity/catalog changes can move items; frozen session snapshots are a revisit.
        """
        # TODO(phase2-feed): orchestrate components and persist attribution before returning.
        raise LearningExercisePending("phase2-feed")
