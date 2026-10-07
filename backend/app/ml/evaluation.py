from app.learning import LearningExercisePending


def recall_at_k(predicted: list[str], relevant: set[str], k: int) -> float | None:
    """Unique predictions in first k; hits/all relevant. Empty targets return None; k > 0."""
    # TODO(phase3a-evaluation): recall under an explicitly fixed eligible target definition.
    raise LearningExercisePending("phase3a-evaluation", phase="3A")


def ndcg_at_k(predicted: list[str], relevant: set[str], k: int) -> float | None:
    """Binary gain, log2(rank+1) discount, ideal min(k, relevant count); duplicate gain once."""
    # TODO(phase3a-evaluation): DCG/IDCG; preserve actual positions for duplicate predictions.
    raise LearningExercisePending("phase3a-evaluation", phase="3A")


def catalog_coverage(predicted: list[list[str]], eligible_catalog: set[str]) -> float | None:
    """Unique eligible recommended pins / eligible catalog size; empty catalog returns None."""
    # TODO(phase3a-evaluation): coverage; reject predictions outside the declared catalog.
    raise LearningExercisePending("phase3a-evaluation", phase="3A")
