"""Learning core for observed CTR; input parsing and manifest validation work separately."""

from datetime import datetime

from app.ctr.artifacts import CTRArtifact
from app.ctr.contracts import (
    CTRExample,
    CTRFeatureBuilder,
    CTRPredictor,
    DatasetManifest,
    Impression,
    News,
    TimeCutoffs,
)
from app.learning import LearningExercisePending


def split_impressions(
    impressions: list[Impression], cutoffs: TimeCutoffs
) -> dict[str, list[Impression]]:
    """Half-open chronological splits, whole groups, timestamp ties and stable ID ordering.

    Never randomly split candidate rows from the same impression. Public dev is a source
    partition, not automatically an untouched final test: record local cutoffs separately.
    """
    # TODO(phase3b-ctr-splits): chronological grouping and cutoffs before any fitted transform.
    raise LearningExercisePending("phase3b-ctr-splits", phase="3B")


class HistoryContentFeatures:
    version = "ctr:history-content:v1"

    def build(
        self, impression: Impression, news_id: str, news: dict[str, News], as_of: datetime
    ) -> dict[str, float]:
        """Use only source pre-impression history and that partition's news metadata.

        Define lowercase alphanumeric title tokens; title_length counts tokens, overlap is
        candidate-token fraction found in known history titles. Category fraction uses known
        history articles; empty denominators give zero. history_length counts source entries.
        Missing history metadata cannot be filled from later partitions. Ignore current
        labels and shuffled candidate order. Reject a context earlier than the impression.
        Source history has no event times, so do not manufacture time decay or live receipts.
        """
        # TODO(phase3b-ctr-features): leakage-safe content/history features and cold start.
        raise LearningExercisePending("phase3b-ctr-features", phase="3B")


def build_examples(
    impressions: list[Impression], news: dict[str, News], features: CTRFeatureBuilder
) -> list[CTRExample]:
    """One row per displayed source candidate; keep all labels and impression identity.

    Hidden/unlabeled groups cannot enter supervised examples: reject them explicitly,
    rather than treating missing labels as nonclicks. No sampled negatives or class balancing.
    """
    # TODO(phase3b-ctr-examples): preserve observed labels, build features, reject hidden groups.
    raise LearningExercisePending("phase3b-ctr-examples", phase="3B")


class ConstantClickRate:
    version = "ctr:constant-training-rate:v1"

    def __init__(self, probability: float):
        if not 0 <= probability <= 1:
            raise ValueError("Click probability must be in [0, 1]")
        self.probability = probability

    def predict(self, examples: list[CTRExample]) -> list[float]:
        return [self.probability] * len(examples)


class LogisticCTRPredictor:
    def __init__(self, artifact: CTRArtifact):
        self.artifact = artifact
        self.version = artifact.version

    def predict(self, examples: list[CTRExample]) -> list[float]:
        """Use artifact feature order and pinned train-only scaling, with stable sigmoid."""
        # TODO(phase3b-ctr-scoring): independent CTR scoring; preserve example order.
        raise LearningExercisePending("phase3b-ctr-scoring", phase="3B")


def fit_constant(examples: list[CTRExample]) -> ConstantClickRate:
    """Unweighted training click count / all displayed training candidates; reject empty input."""
    # TODO(phase3b-ctr-baseline): training-only observed rate, not held-out prevalence.
    raise LearningExercisePending("phase3b-ctr-baseline", phase="3B")


def fit_logistic(examples: list[CTRExample], manifest: DatasetManifest) -> CTRPredictor:
    """Train-only transform and logistic regression; verify rows are inside training cutoffs.

    Reject empty/single-class training, pin sklearn/runtime versions and random state,
    keep the natural observed class distribution. Validation chooses settings; final test
    remains untouched. A separate CTR artifact schema is required; never use the app's
    implicit-feedback artifact or activate a product model. Track manifest/baseline in MLflow.
    """
    # TODO(phase3b-ctr-training): pinned fitting, independent artifact and tracked run.
    raise LearningExercisePending("phase3b-ctr-training", phase="3B")
