import math

import httpx

from app.feed.contracts import FeedContext
from app.ml.config import EmbeddingConfig, UserEmbeddingConfig
from app.ml.contracts import Embedding, HistoryEntry, PinContent


def normalize_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    """Return a unit vector; reject empty, nonfinite, or zero-norm inputs."""
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError("Vector must be nonempty and finite")
    norm = math.hypot(*values)
    if not norm or not math.isfinite(norm):
        raise ValueError("Vector norm must be positive and finite")
    return tuple(x / norm for x in values)


class ClipPinEmbedder:
    def __init__(self, config: EmbeddingConfig, endpoint: str = "http://127.0.0.1:8090"):
        self.config = config
        self.version = config.version
        self.endpoint = endpoint

    def metadata(self) -> dict:
        with httpx.Client(timeout=90, trust_env=False) as client:
            response = client.get(self.endpoint + "/health")
            response.raise_for_status()
        info = response.json()["personalization"]
        for name in (
            "version",
            "architecture",
            "checkpoint",
            "weights_sha256",
            "dimension",
            "image_weight",
            "preprocess_version",
            "text_policy",
        ):
            if info[name] != getattr(self.config, name):
                raise ValueError(f"Pinned embedding recipe mismatch: {name}")
        return info

    def embed(self, pins: list[PinContent]) -> list[Embedding]:
        """Encode image and title, fuse normalized outputs, then normalize again.

        The isolated CPU runtime verifies local weights at startup and uses eval/inference
        mode with evaluation preprocessing. Preserve batch order and verify the complete
        recipe before inference; canonical pixel preparation belongs to the media job.
        """
        if not pins:
            return []
        self.metadata()
        result = []
        with httpx.Client(timeout=90, trust_env=False) as client:
            for pin in pins:
                response = client.post(
                    self.endpoint + "/encode-content",
                    files={"image": ("content.png", pin.image_bytes, "image/png")},
                    data={"title": pin.title},
                )
                response.raise_for_status()
                vector = Embedding.model_validate(response.json())
                if (
                    vector.embedder_version != self.version
                    or vector.dimension != self.config.dimension
                ):
                    raise ValueError("Incompatible content encoder output")
                result.append(vector.model_copy(update={"values": normalize_vector(vector.values)}))
        return result


class MeanUserEmbedder:
    def __init__(self, config: UserEmbeddingConfig):
        self.config = config
        self.version = config.version

    def embed(self, history: list[HistoryEntry], context: FeedContext) -> Embedding | None:
        """Prior known history, most recent N, time-decayed weighted mean, normalized.

        Require matching user, occurred_at < as_of AND known_at < as_of; group tied times
        rather than treating tied outcomes as prior information. Require one embedding
        version/dimension. N is a soft cap: retain the complete boundary occurrence-time
        group. Weight = 2 ** (-age_hours / half_life_hours). Return None for
        empty or canceling history so retrieval deliberately uses its cold-start fallback.
        """
        entries = eligible_history(history, context, self.config)
        if not entries:
            return None
        version = entries[0].embedding.embedder_version
        dimension = entries[0].embedding.dimension
        if any(
            e.embedding.embedder_version != version or e.embedding.dimension != dimension
            for e in entries
        ):
            raise ValueError("User history must use one embedding version and dimension")
        # Relative ages avoid underflow when the entire history is old; normalization
        # makes removing the common decay factor algebraically equivalent.
        latest = entries[0].occurred_at
        total = [0.0] * dimension
        for entry in entries:
            hours = (latest - entry.occurred_at).total_seconds() / 3600
            weight = 2 ** (-hours / self.config.half_life_hours)
            for i, value in enumerate(normalize_vector(entry.embedding.values)):
                total[i] += weight * value
        if math.hypot(*total) < 1e-12:
            return None
        return Embedding(embedder_version=version, values=normalize_vector(tuple(total)))


def eligible_history(history, context, config):
    entries = sorted(
        (
            e
            for e in history
            if e.user_id == context.user_id
            and e.occurred_at < context.as_of
            and e.known_at < context.as_of
        ),
        key=lambda e: (e.occurred_at, e.event_id),
        reverse=True,
    )
    if len({e.event_id for e in entries}) != len(entries):
        raise ValueError("Duplicate history event identity")
    if len(entries) > config.history_limit:
        boundary = entries[config.history_limit - 1].occurred_at
        entries = [e for e in entries if e.occurred_at >= boundary]
    return entries
