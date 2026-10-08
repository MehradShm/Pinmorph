import math
from dataclasses import replace

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import cast, exists, literal, select, text
from sqlalchemy.orm import Session, aliased

from app.feed.contracts import Candidate, FeedContext
from app.ml.config import PersonalizationConfig, RetrievalConfig
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
    def __init__(
        self, config: RetrievalConfig, personalization: PersonalizationConfig | None = None
    ):
        self.config = config
        self.version = config.version
        self.personalization = personalization or PersonalizationConfig(retrieval=config)

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        """Build user context, blend ANN/popular/recent quotas, deduplicate and backfill.

        Preserve contributing source names, retrieval score and all scoring features.
        No-history users use the configured popularity/recency fallback. Requires the
        Phase 2 feature/history path; final display position is never a scoring feature.
        """
        from app.ml.baselines import CatalogCandidateSource, PopularityRanker, RecencyRanker
        from app.ml.data import online_inputs

        inputs = online_inputs(db, context, self.personalization)
        query = inputs.features.user_embedding(context.user_id, context.as_of)
        base = CatalogCandidateSource().retrieve(db, context)
        candidates = []
        vector_ids = {item.pin_id for item in inputs.catalog}
        for candidate in base:
            if candidate.pin.id in vector_ids:
                features = inputs.features.build(context.user_id, candidate.pin.id, context.as_of)
            else:
                features = dict(candidate.features, similarity=0.0, user_history_count=0.0)
            candidates.append(replace(candidate, features=features))
        popular = [
            replace(r.candidate, sources=(PopularityRanker.version,))
            for r in PopularityRanker().rank(candidates, context)
        ]
        recent = [
            replace(r.candidate, sources=(RecencyRanker.version,))
            for r in RecencyRanker().rank(candidates, context)
        ]
        if query is None:
            fallback = (
                popular if self.config.fallback_ranker == PopularityRanker.version else recent
            )
            return [
                replace(c, sources=(self.version, "fallback:cold-start:v1", *c.sources))
                for c in fallback[: self.config.pool_size]
            ]
        by_id = {c.pin.id: c for c in candidates}
        hits = PgvectorANNRetriever().search(db, query, context, self.config.pool_size)
        ann = [
            replace(
                by_id[h.pin_id],
                sources=(PgvectorANNRetriever.version,),
                retrieval_score=h.similarity,
            )
            for h in hits
            if h.pin_id in by_id
        ]
        return [
            replace(c, sources=(self.version, *c.sources))
            for c in blend_candidates(
                ann,
                popular,
                recent,
                self.config,
            )
        ]


def blend_candidates(ann, popular, recent, config):
    lists = (ann, popular, recent)
    shares = (config.ann_share, config.popularity_share, config.recency_share)
    exact = [config.pool_size * share for share in shares]
    quotas = [math.floor(value) for value in exact]
    for index in sorted(range(3), key=lambda i: (-(exact[i] - quotas[i]), i))[
        : config.pool_size - sum(quotas)
    ]:
        quotas[index] += 1
    selected = {}

    def add(candidate):
        old = selected.get(candidate.pin.id)
        if old:
            selected[candidate.pin.id] = replace(
                old,
                sources=tuple(
                    dict.fromkeys(
                        (*old.sources, *candidate.sources),
                    )
                ),
            )
            return False
        if len(selected) < config.pool_size:
            selected[candidate.pin.id] = candidate
            return True
        return False

    for rows, quota in zip(lists, quotas, strict=True):
        count = 0
        for candidate in rows:
            if count >= quota:
                break
            count += add(candidate)
    for rows in lists:
        for candidate in rows:
            if len(selected) >= config.pool_size:
                break
            add(candidate)
    return list(selected.values())
