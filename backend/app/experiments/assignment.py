from app.experiments.config import Arm, Experiment
from app.learning import LearningExercisePending


def assign_arm(user_id: str, experiment: Experiment) -> Arm:
    """Stable SHA-256 bucketing; arm order defines contiguous half-open intervals.

    Exercise contract: UTF-8 encode compact JSON [user_id, name, salt, version], with
    ensure_ascii=False and separators=(",", ":"). Interpret the first eight digest bytes
    as an unsigned big-endian integer, then take modulo 10,000. Select the arm whose
    cumulative bucket interval contains that value. Never use Python's hash().
    """
    # TODO(phase2-assignment): implement the specified digest and interval mapping.
    raise LearningExercisePending("phase2-assignment")
