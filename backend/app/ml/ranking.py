from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.learning import LearningExercisePending
from app.ml.artifacts import RankerArtifact
from app.ml.config import RerankingConfig
from app.ml.contracts import Embedding


class LogisticRegressionRanker:
    def __init__(self, artifact: RankerArtifact):
        self.artifact = artifact
        self.version = artifact.version

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]:
        """Apply artifact feature order/scaling and sigmoid score; tie-break by pin ID.

        Require every declared finite feature, snapshot the original feature values, and
        report the actual artifact version. Scores trained on sampled implicit negatives
        are engagement scores, not measured CTR. Never fit/standardize on serving data.
        """
        # TODO(phase3a-ranking): ordered features, pinned scaling, stable logistic scoring and sort.
        raise LearningExercisePending("phase3a-ranking", phase="3A")


class DiversityReranker:
    def __init__(self, config: RerankingConfig, embeddings: dict[str, Embedding]):
        self.config = config
        self.embeddings = embeddings
        self.version = config.version

    def rerank(
        self, candidates: list[RankedCandidate], context: FeedContext
    ) -> list[RankedCandidate]:
        """Greedily retain ranked order, suppress duplicates, enforce known-creator caps.

        Compare only same-version embeddings. Exact pin IDs are always deduplicated;
        cosine >= threshold is near-duplicate. Missing owner IDs do not share one creator
        bucket (the imported catalog has no creators). Missing embeddings keep an item
        eligible for the creator cap. Preserve scores; serving later assigns positions.
        """
        # TODO(phase3a-reranking): ranked-order duplicate suppression and per-creator limits.
        raise LearningExercisePending("phase3a-reranking", phase="3A")
