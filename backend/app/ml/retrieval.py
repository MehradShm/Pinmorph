from sqlalchemy.orm import Session

from app.feed.contracts import Candidate, FeedContext
from app.learning import LearningExercisePending
from app.ml.config import RetrievalConfig
from app.ml.contracts import Embedding, RetrievalHit, VectorItem


class ExactVectorRetriever:
    version = "retriever:exact-cosine:v1"

    def search(
        self, query: Embedding, items: list[VectorItem], context: FeedContext, k: int
    ) -> list[RetrievalHit]:
        """Correctness reference: eligible same-version vectors, cosine descending, pin ID ties.

        Filter item availability and known time <= as_of. Reject zero vectors or dimension
        mismatch in the selected version, exclude other versions, deduplicate pin IDs.
        k must be positive. This small exact implementation is the ANN comparison baseline.
        """
        # TODO(phase3a-exact-retrieval): eligibility, cosine similarity, stable top-k.
        raise LearningExercisePending("phase3a-exact-retrieval", phase="3A")


class PgvectorANNRetriever:
    version = "retriever:pgvector-hnsw:v1"

    def search(
        self, db: Session, query: Embedding, context: FeedContext, k: int
    ) -> list[RetrievalHit]:
        """Filter model/version/dimension and availability; use the latest known content revision.

        Create and query a per-version partial HNSW expression index with a fixed vector
        cast and cosine operator. Measure recall against exact results; do not claim ANN
        speed/accuracy from tiny fixtures or compare vectors from different model spaces.
        """
        # TODO(phase3a-ann-retrieval): version-specific index/query, backfill, recall comparison.
        raise LearningExercisePending("phase3a-ann-retrieval", phase="3A")


class BlendedCandidateSource:
    def __init__(self, config: RetrievalConfig):
        self.config = config
        self.version = config.version

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        """Build user context, blend ANN/popular/recent quotas, deduplicate and backfill.

        Preserve contributing source names, retrieval score and all scoring features.
        No-history users use the configured popularity/recency fallback. Requires the
        Phase 2 feature/history path; final display position is never a scoring feature.
        """
        # TODO(phase3a-candidate-blend): compose history, retrievers and Phase 2 baseline sources.
        raise LearningExercisePending("phase3a-candidate-blend", phase="3A")
