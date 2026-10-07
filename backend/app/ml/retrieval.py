from pgvector.sqlalchemy import VECTOR
from sqlalchemy import cast, exists, literal, select, text
from sqlalchemy.orm import Session, aliased

from app.feed.contracts import Candidate, FeedContext
from app.learning import LearningExercisePending
from app.ml.config import RetrievalConfig
from app.ml.contracts import Embedding, RetrievalHit, VectorItem
from app.ml.embeddings import normalize_vector
from app.ml.models import PinEmbedding
from app.models import Pin, User
from app.product.models import HiddenPin
from app.social.policy import visible_owner


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
        if k <= 0:
            raise ValueError("k must be positive")
        normalized = normalize_vector(query.values)
        seen = set()
        hits = []
        for item in items:
            if item.pin_id in seen:
                raise ValueError("Duplicate pin identity")
            seen.add(item.pin_id)
            if (
                item.embedding.embedder_version != query.embedder_version
                or item.available_at > context.as_of
                or item.known_at > context.as_of
            ):
                continue
            if item.embedding.dimension != query.dimension:
                raise ValueError("Vector dimensions do not match")
            values = normalize_vector(item.embedding.values)
            hits.append(
                RetrievalHit(
                    pin_id=item.pin_id,
                    similarity=sum(a * b for a, b in zip(normalized, values, strict=True)),
                )
            )
        return sorted(hits, key=lambda hit: (-hit.similarity, hit.pin_id))[:k]


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
        if k <= 0:
            raise ValueError("k must be positive")
        values = normalize_vector(query.values)
        viewer = db.get(User, context.user_id)
        newer = aliased(PinEmbedding)
        latest = ~exists(
            select(newer.pin_id).where(
                newer.pin_id == PinEmbedding.pin_id,
                newer.embedder_version == PinEmbedding.embedder_version,
                newer.known_at <= context.as_of,
                (newer.known_at > PinEmbedding.known_at)
                | (
                    (newer.known_at == PinEmbedding.known_at)
                    & (newer.content_hash > PinEmbedding.content_hash)
                ),
            )
        )
        distance = cast(PinEmbedding.embedding, VECTOR(query.dimension)).cosine_distance(
            list(values)
        )
        statement = (
            select(PinEmbedding.pin_id, distance.label("distance"))
            .join(Pin, Pin.id == PinEmbedding.pin_id)
            .where(
                PinEmbedding.embedder_version
                == literal(query.embedder_version, literal_execute=True),
                PinEmbedding.dimension == query.dimension,
                PinEmbedding.known_at <= context.as_of,
                Pin.status == "ready",
                Pin.available_at <= context.as_of,
                Pin.created_at <= context.as_of,
                visible_owner(Pin.owner_id, viewer, include_muted=True),
                Pin.id.not_in(select(HiddenPin.pin_id).where(HiddenPin.user_id == context.user_id)),
                latest,
            )
            .order_by(distance)
            .limit(k)
        )
        db.execute(text("SET LOCAL hnsw.ef_search = 100"))
        db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        rows = db.execute(statement).all()
        return sorted(
            [RetrievalHit(pin_id=pin_id, similarity=1 - float(d)) for pin_id, d in rows],
            key=lambda hit: (-hit.similarity, hit.pin_id),
        )


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
