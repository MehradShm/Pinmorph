"""Independent Phase 4 algorithms; infrastructure does not stand in for their acceptance."""

from typing import Protocol

from sqlalchemy.orm import Session

from app.discovery.crop import PreparedCrop
from app.feed.contracts import Candidate, FeedContext
from app.learning import LearningExercisePending
from app.ml.contracts import Embedding, RetrievalHit, VectorItem


class CropEmbedder(Protocol):
    version: str

    def embed_crop(self, crop: PreparedCrop) -> Embedding: ...


class RelatedSource(Protocol):
    version: str

    def retrieve(
        self, db: Session, context: FeedContext, context_pin_id: str
    ) -> list[Candidate]: ...


class LensSearch(Protocol):
    version: str

    def search(self, db: Session, context: FeedContext, crop: PreparedCrop) -> list[Candidate]: ...


class FollowingCandidateSource:
    version = "candidate:following-read:v1"

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        """Union ready pins from followed creators and followed public boards, deduplicated.

        Apply follow/save existence at as_of, pin availability and block/mute policy.
        Secret boards must never contribute, including boards made secret after following.
        Preserve all contributing sources and point-in-time scoring features. Serve through
        the shared FeedService/request-item persistence, not a second logging implementation.
        Baseline is a timestamp/ID ordered union; revisit fan-out on write at higher traffic.
        """
        # TODO(phase4-following): eligible social candidates and shared serving integration.
        raise LearningExercisePending("phase4-following", phase="4")


class RelatedPinSource:
    version = "candidate:related-public-boards:v1"

    def retrieve(self, db: Session, context: FeedContext, context_pin_id: str) -> list[Candidate]:
        """Count shared public boards containing the context pin; never inspect secret boards.

        Exclude context pin, future saves/items, blocked/muted creators and duplicate results.
        Backfill from same-version eligible embedding similarity when shared-board evidence
        is absent. Compare fixed candidates with similarity alone. Integrate attribution with
        FeedService (surface=related, context pin), including model/config/source versions.
        """
        # TODO(phase4-related): co-board candidates, explicit similarity fallback and serving.
        raise LearningExercisePending("phase4-related", phase="4")


class ClipCropEmbedder:
    version = "embedder:clip-image-crop:v1"

    def embed_crop(self, crop: PreparedCrop) -> Embedding:
        """Pinned local CLIP image inference, normalized; title-free crop query.

        Reuse Phase 3A checkpoint/preprocessing. Image-only queries must be evaluated against
        a declared compatible catalog recipe: image-title fusion can change retrieval quality.
        Record actual model version/weights, crop hash/policy and runtime in experiment output.
        Never download weights implicitly or fabricate vectors when the runtime is absent.
        """
        # TODO(phase4-lens-embedding): pinned image-only encoding with compatible catalog recipe.
        raise LearningExercisePending("phase4-lens-embedding", phase="4")


def compare_lens_retrieval(
    exact: list[RetrievalHit],
    approximate: list[RetrievalHit],
    k: int,
) -> float | None:
    """Top-k overlap / size of exact top-k, not user relevance; empty reference is None.

    Reject nonpositive k and duplicate IDs; the separate evaluation report records eligible
    corpus/version and measured latency with an elapsed clock. Never call overlap accuracy.
    """
    # TODO(phase4-lens-evaluation): exact/ANN agreement and reproducible latency comparison.
    raise LearningExercisePending("phase4-lens-evaluation", phase="4")


class LensService:
    version = "surface:lens:v1"

    def __init__(self, crop_embedder: CropEmbedder):
        self.crop_embedder = crop_embedder

    def search(self, db: Session, context: FeedContext, crop: PreparedCrop) -> list[Candidate]:
        """Encode crop, compare exact/ANN retrieval and serve eligible versioned results.

        Use the same privacy/availability filter and shared served-item logging as other
        surfaces. Do not persist an impression merely because a match was returned.
        Bind any pagination to crop/config/model versions and carry request ID on the response.
        """
        # TODO(phase4-lens-serving): crop embedder/retrievers and attributed response composition.
        raise LearningExercisePending("phase4-lens-serving", phase="4")


def eligible_lens_vectors(
    items: list[VectorItem],
    embedder_version: str,
    context: FeedContext,
) -> list[VectorItem]:
    """Only matching-version items with available_at/known_at <= context.as_of, deduplicated."""
    # TODO(phase4-lens-serving): duplicate rejection, version and temporal eligibility.
    raise LearningExercisePending("phase4-lens-serving", phase="4")
