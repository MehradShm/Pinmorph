from sqlalchemy.orm import Session

from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.learning import LearningExercisePending


class CatalogCandidateSource:
    version = "candidate:catalog:v1"

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        """Eligible ready pins and point-in-time baseline features.

        features: age_hours (since available_at), observed_save_count, imported_purchase_count.
        Observed saves come from accepted save engagements, deduplicated by user/pin;
        imported purchases remain separate, deduplicated by user/pin. Both occurrence and
        receipt must be strictly before as_of. Mutable board membership is not history.
        Require status ready, available_at <= as_of, and created_at <= as_of; imported
        backdated availability must not make a pin known before it was actually imported.
        V1 retrieves all eligible items at the small demo scale; no premature top-N cutoff.
        """
        # TODO(phase2-candidates): query eligible pins and time-correct separate counts.
        raise LearningExercisePending("phase2-candidates")


class RecencyRanker:
    version = "ranker:recency:v1"

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]:
        """Score = -age_hours; sort descending score then ascending pin ID for ties."""
        # TODO(phase2-ranking): pure deterministic ranking; exclude display position.
        raise LearningExercisePending("phase2-ranking")


class PopularityRanker:
    version = "ranker:popularity:v1"

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]:
        """Score = observed_save_count + imported_purchase_count.

        Equal weight is an explicit proxy baseline, not CTR. Tie-break by newest item
        (smallest age_hours), then ascending pin ID; all-zero history falls back to recency.
        """
        # TODO(phase2-ranking): keep the separate provenance features in the snapshot.
        raise LearningExercisePending("phase2-ranking")


class IdentityReranker:
    version = "reranker:identity:v1"

    def rerank(
        self, candidates: list[RankedCandidate], context: FeedContext
    ) -> list[RankedCandidate]:
        return list(candidates)
