from pydantic import Field, FiniteFloat

from app.ctr.contracts import Prediction, Record
from app.learning import LearningExercisePending


class Metrics(Record):
    candidate_count: int = Field(ge=0)
    impression_count: int = Field(ge=0)
    pooled_auc: FiniteFloat | None = Field(ge=0, le=1)
    macro_group_auc: FiniteFloat | None = Field(ge=0, le=1)
    auc_eligible_groups: int = Field(ge=0)
    log_loss: FiniteFloat | None = Field(ge=0)
    brier_score: FiniteFloat | None = Field(ge=0, le=1)
    ece: FiniteFloat | None = Field(ge=0, le=1)
    macro_ndcg: FiniteFloat | None = Field(ge=0, le=1)
    ranking_eligible_groups: int = Field(ge=0)


def evaluate(predictions: list[Prediction], *, k: int = 10, bins: int = 10) -> Metrics:
    """Known-answer CTR and per-impression ranking metrics on all held-out source labels.

    Reject duplicate (impression,news) identities; k/bins must be positive. AUC gives ties
    half credit; single-class AUC is undefined. Macro group AUC excludes single-class groups.
    NDCG excludes no-positive groups, ranks by score then news ID, binary gains/log2 discount.
    Log loss clips probabilities to [1e-15,1-1e-15]; Brier uses raw probabilities. ECE uses
    equal-width [left,right) bins with 1 in the last bin, weighted by candidate count.
    Empty input gives None metrics, not zero observations. Report eligible denominators.
    """
    # TODO(phase3b-ctr-evaluation): AUC/log-loss/Brier/calibration/grouped ranking.
    raise LearningExercisePending("phase3b-ctr-evaluation", phase="3B")
