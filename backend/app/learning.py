"""Make unfinished learning exercises explicit at service and HTTP boundaries."""


class LearningExercisePending(NotImplementedError):
    def __init__(self, exercise: str, *, phase: str = "2"):
        self.exercise = exercise
        self.phase = phase
        super().__init__(f"Phase {phase} exercise pending: {exercise}")
