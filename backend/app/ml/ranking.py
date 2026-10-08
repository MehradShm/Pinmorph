import math

from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.ml.artifacts import RankerArtifact
from app.ml.config import RerankingConfig
from app.ml.contracts import Embedding
from app.ml.embeddings import normalize_vector


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
        ranked = []
        for candidate in candidates:
            values = [candidate.features[name] for name in self.artifact.feature_names]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Scoring features must be finite")
            logit = self.artifact.intercept + sum(
                coefficient * ((value - mean) / scale)
                for value, coefficient, mean, scale in zip(
                    values,
                    self.artifact.coefficients,
                    self.artifact.means,
                    self.artifact.scales,
                    strict=True,
                )
            )
            if not math.isfinite(logit):
                raise ValueError("Scoring logit must be finite")
            score = sigmoid(logit)
            ranked.append(RankedCandidate(candidate, score, score))
        return sorted(ranked, key=lambda r: (-r.rank_score, r.candidate.pin.id))


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
        retained, seen, creators, vectors = [], set(), {}, []
        for row in candidates:
            pin = row.candidate.pin
            if pin.id in seen:
                continue
            seen.add(pin.id)
            if (
                pin.owner_id is not None
                and creators.get(pin.owner_id, 0) >= self.config.per_creator_cap
            ):
                continue
            vector = self.embeddings.get(pin.id)
            values = normalize_vector(vector.values) if vector else None
            if vector and any(
                version == vector.embedder_version
                and len(old) == len(values)
                and sum(a * b for a, b in zip(values, old, strict=True))
                >= self.config.duplicate_similarity
                for version, old in vectors
            ):
                continue
            retained.append(row)
            if vector:
                vectors.append((vector.embedder_version, values))
            if pin.owner_id is not None:
                creators[pin.owner_id] = creators.get(pin.owner_id, 0) + 1
        return retained


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)
