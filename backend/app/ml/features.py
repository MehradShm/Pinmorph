"""One point-in-time feature implementation for offline replay and online scoring."""

from datetime import datetime

from app.feed.contracts import FeedContext
from app.ml.config import UserEmbeddingConfig
from app.ml.contracts import Embedding, HistoryEntry, Interaction, VectorItem
from app.ml.embeddings import MeanUserEmbedder, eligible_history, normalize_vector


class PointInTimeFeatures:
    version = "features:personalized:v1"

    def __init__(
        self,
        catalog: list[VectorItem],
        interactions: list[Interaction],
        config: UserEmbeddingConfig | None = None,
    ):
        self.catalog = {item.pin_id: item for item in catalog}
        if len(self.catalog) != len(catalog):
            raise ValueError("Duplicate catalog pin identity")
        if len({e.event_id for e in interactions}) != len(interactions):
            raise ValueError("Duplicate interaction identity")
        self.interactions = interactions
        self.config = config or UserEmbeddingConfig()

    def history(self, user_id: str, as_of: datetime) -> list[HistoryEntry]:
        entries = []
        for event in self.interactions:
            item = self.catalog.get(event.pin_id)
            if (
                event.user_id == user_id
                and event.occurred_at < as_of
                and event.known_at < as_of
                and item
                and item.available_at <= as_of
                and item.known_at <= as_of
            ):
                entries.append(
                    HistoryEntry(
                        event_id=event.event_id,
                        user_id=user_id,
                        pin_id=event.pin_id,
                        occurred_at=event.occurred_at,
                        known_at=event.known_at,
                        provenance=event.provenance,
                        embedding=item.embedding,
                    )
                )
        return entries

    def user_embedding(self, user_id: str, as_of: datetime) -> Embedding | None:
        return MeanUserEmbedder(self.config).embed(
            self.history(user_id, as_of),
            FeedContext("offline", user_id, as_of, as_of),
        )

    def build(self, user_id: str, pin_id: str, as_of: datetime) -> dict[str, float]:
        item = self.catalog[pin_id]
        if item.available_at > as_of or item.known_at > as_of:
            raise ValueError("Pin content is not available at the feature cutoff")
        prior = [e for e in self.interactions if e.occurred_at < as_of and e.known_at < as_of]
        history = self.history(user_id, as_of)
        context = FeedContext("offline", user_id, as_of, as_of)
        user = MeanUserEmbedder(self.config).embed(history, context)
        similarity = 0.0
        if user:
            if user.embedder_version != item.embedding.embedder_version:
                raise ValueError("Features cannot mix embedding spaces")
            similarity = sum(
                a * b
                for a, b in zip(
                    user.values,
                    normalize_vector(item.embedding.values),
                    strict=True,
                )
            )
        return {
            "similarity": similarity,
            "age_hours": max(0.0, (as_of - item.available_at).total_seconds() / 3600),
            "observed_save_count": float(
                len({e.user_id for e in prior if e.pin_id == pin_id and e.action == "save"})
            ),
            "imported_purchase_count": float(
                len(
                    {
                        e.user_id
                        for e in prior
                        if e.pin_id == pin_id and e.action == "purchase_proxy"
                    }
                )
            ),
            "user_history_count": float(len(eligible_history(history, context, self.config))),
        }
