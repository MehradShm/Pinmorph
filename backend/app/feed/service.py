import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.experiments.assignment import assign_arm
from app.experiments.config import FeedConfig
from app.feed.contracts import CandidateSource, FeedContext, Ranker, Reranker
from app.feed.persistence import record_page
from app.feed.registry import Registry
from app.feed.schemas import FeedPage
from app.ml.baselines import (
    CatalogCandidateSource,
    IdentityReranker,
    PopularityRanker,
    RecencyRanker,
)
from app.product.models import UserSettings


def page_candidates(
    db,
    context,
    ranked,
    versions,
    config_version,
    *,
    details=None,
    arms=None,
    feature_schema="features:baseline:v1",
):
    binding = {
        "user": context.user_id,
        "surface": context.surface,
        "versions": versions,
        "config": config_version,
        "details": details or {},
        "arms": arms or {},
    }
    fingerprint = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    unique = []
    seen_images = set()
    for row in ranked:
        identity = row.candidate.pin.pixel_hash or row.candidate.pin.id
        if identity not in seen_images:
            seen_images.add(identity)
            unique.append(row)
    ranked = unique
    offset = 0
    if context.cursor:
        try:
            saved, offset = json.loads(base64.urlsafe_b64decode(context.cursor))
            if saved != fingerprint or type(offset) is not int or not 0 <= offset <= 1_000_000:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError) as exc:
            raise HTTPException(
                422, "Cursor does not match this user, surface or configuration"
            ) from exc
    next_cursor = None
    if offset + context.limit < len(ranked):
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([fingerprint, offset + context.limit]).encode()
        ).decode()
    return record_page(
        db,
        context,
        ranked[offset : offset + context.limit],
        versions=versions,
        config_version=config_version,
        arms=arms,
        details=details,
        next_cursor=next_cursor,
        feature_schema=feature_schema,
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
        if config.personalization:
            from app.ml.artifacts import load_artifact
            from app.ml.ranking import DiversityReranker, LogisticRegressionRanker
            from app.ml.retrieval import BlendedCandidateSource

            artifact = load_artifact(
                Path(config.ranker_artifact_path), config.ranker_artifact_sha256
            )
            policy = config.personalization
            if (
                artifact.training.embedding_version != policy.embedding.version
                or artifact.training.feature_schema_version != policy.feature_schema_version
                or artifact.version != policy.ranker_version
                or policy.embedding.dimension != 512
                or artifact.training.user_embedding != policy.user_embedding
            ):
                raise ValueError("Artifact and personalized serving versions are incompatible")
            self.sources.register(
                policy.retrieval.version,
                BlendedCandidateSource(
                    policy.retrieval,
                    policy,
                ),
            )
            self.rankers.register(artifact.version, LogisticRegressionRanker(artifact))
            self.rerankers.register(
                policy.reranking.version, DiversityReranker(policy.reranking, {})
            )
        self.sources.resolve(config.candidate_source)
        self.rerankers.resolve(config.reranker)
        for arm in config.experiment.arms:
            self.rankers.resolve(arm.ranker)

    def serve(self, db: Session, context: FeedContext) -> FeedPage:
        if self.config.personalization:
            from app.ml.models import EmbeddingModel

            recipe = self.config.personalization.embedding
            stored = db.get(EmbeddingModel, recipe.version)
            if stored is None or any(
                getattr(stored, name) != getattr(recipe, name)
                for name in (
                    "dimension",
                    "weights_sha256",
                    "preprocess_version",
                    "text_policy",
                    "image_weight",
                )
            ):
                raise ValueError("Registered embedding model does not match serving recipe")
        arm = assign_arm(context.user_id, self.config.experiment)
        source = self.sources.resolve(self.config.candidate_source)
        ranker = self.rankers.resolve(arm.ranker)
        reranker = self.rerankers.resolve(self.config.reranker)
        merged = {}
        for candidate in source.retrieve(db, context):
            if candidate.pin.id in merged:
                old = merged[candidate.pin.id]
                candidate = replace(
                    old, sources=tuple(sorted(set(old.sources + candidate.sources)))
                )
            merged[candidate.pin.id] = candidate
        details = {}
        policy = self.config.personalization
        if policy:
            from app.ml.ranking import DiversityReranker
            from app.ml.vector_store import catalog_vectors

            if merged and all("fallback:cold-start:v1" in c.sources for c in merged.values()):
                ranker = self.rankers.resolve(policy.retrieval.fallback_ranker)
                details["fallback_reason"] = "no_eligible_user_embedding"
            if self.config.reranker == policy.reranking.version:
                reranker = DiversityReranker(
                    policy.reranking,
                    {
                        item.pin_id: item.embedding
                        for item in catalog_vectors(
                            db,
                            policy.embedding.version,
                            context,
                        )
                    },
                )
        ranked = reranker.rerank(ranker.rank(list(merged.values()), context), context)
        preferences = db.get(UserSettings, context.user_id)
        interests = preferences.interests if preferences else []
        if interests:
            updated = []
            for row in ranked:
                words = (row.candidate.pin.title + " " + row.candidate.pin.description).lower()
                matches = sum(1 for term in interests if term in words)
                features = dict(row.candidate.features, interest_matches=float(matches))
                updated.append(
                    replace(
                        row,
                        candidate=replace(row.candidate, features=features),
                        final_score=row.rank_score + matches * self.config.interest_boost,
                    )
                )
            ranked = sorted(updated, key=lambda row: (-row.final_score, row.candidate.pin.id))
        versions = {
            "candidate_source": source.version,
            "ranker": ranker.version,
            "reranker": reranker.version,
            "interest_policy": "interest:keyword-boost:v1",
        }
        if policy:
            versions.update(
                {
                    "pin_embedder": policy.embedding.version,
                    "user_embedder": policy.user_embedding.version,
                    "feature_schema": policy.feature_schema_version,
                }
            )
            if ranker.version == policy.ranker_version:
                versions["ranker_sha256"] = self.config.ranker_artifact_sha256
            details["configured_ranker"] = policy.ranker_version
        arms = {f"{self.config.experiment.name}:{self.config.experiment.version}": arm.name}
        return page_candidates(
            db,
            context,
            ranked,
            versions,
            self.config.version,
            details=dict(details, interests=interests, interest_boost=self.config.interest_boost),
            arms=arms,
            feature_schema=self.config.feature_schema_version,
        )
