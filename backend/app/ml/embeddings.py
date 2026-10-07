from app.feed.contracts import FeedContext
from app.learning import LearningExercisePending
from app.ml.config import EmbeddingConfig, UserEmbeddingConfig
from app.ml.contracts import Embedding, HistoryEntry, PinContent


def normalize_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    """Return a unit vector; reject empty, nonfinite, or zero-norm inputs."""
    # TODO(phase3a-normalization): L2 normalization with explicit invalid-input handling.
    raise LearningExercisePending("phase3a-normalization", phase="3A")


class ClipPinEmbedder:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.version = config.version

    def embed(self, pins: list[PinContent]) -> list[Embedding]:
        """Encode image and title, fuse normalized outputs, then normalize again.

        Load pinned local weights lazily, use eval/inference mode and the evaluation image
        preprocessing, and preserve batch order. Record weight hash, library/preprocess/text
        versions, dimension and image weight. Never use a random vector as a CLIP fallback.
        """
        # TODO(phase3a-pin-embeddings): implement CLIP inference and immutable persistence/job path.
        raise LearningExercisePending("phase3a-pin-embeddings", phase="3A")


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
        # TODO(phase3a-user-embeddings): eligibility, deterministic history limit, decay and mean.
        raise LearningExercisePending("phase3a-user-embeddings", phase="3A")
