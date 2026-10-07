from app.learning import LearningExercisePending
from app.ml.artifacts import RankerArtifact
from app.ml.config import SplitCutoffs, TrainingManifest
from app.ml.contracts import FeatureBuilder, Interaction, TrainingExample, VectorItem


def split_interactions(
    interactions: list[Interaction], cutoffs: SplitCutoffs
) -> dict[str, list[Interaction]]:
    """Half-open chronological splits; exclude outside range and keep occurrence ties together."""
    # TODO(phase3a-splits): train/validation/test assignment without random shuffling.
    raise LearningExercisePending("phase3a-splits", phase="3A")


def build_examples(
    interactions: list[Interaction],
    catalog: list[VectorItem],
    features: FeatureBuilder,
    manifest: TrainingManifest,
) -> list[TrainingExample]:
    """Eligible point-in-time positives and seeded sampled-unobserved negatives.

    Target positives follow the manifest: imported purchases and observed/simulated saves;
    closeups/source clicks may inform history but are not this dataset's positive target.
    Only declared source weights participate. Build history strictly before each example;
    use the manifest's explicit availability policy. In historical_import_replay, an
    adapter maps imported source chronology to known times while preserving raw receipt;
    never apply that policy to delayed observed/simulator events. Never filter a negative
    using future interactions. Record candidate universe, seed and shortfalls. No labels
    for unseen served items, unresolved actions, or open impression windows.
    """
    # TODO(phase3a-examples): chronology-safe feature builds, provenance and negative sampling.
    raise LearningExercisePending("phase3a-examples", phase="3A")


def fit_ranker(examples: list[TrainingExample], manifest: TrainingManifest) -> RankerArtifact:
    """Fit train-only scaling and weighted logistic regression; reject empty/single-class data.

    Hyperparameters use validation only, final test stays separate. Export ordered features,
    scaling and coefficients to JSON, record sklearn/runtime versions, and track the run in
    MLflow with the full manifest. Fitting does not activate a model or replace a feed config.
    """
    # TODO(phase3a-training): reproducible fitting, manifest-bound artifact and MLflow tracking.
    raise LearningExercisePending("phase3a-training", phase="3A")
