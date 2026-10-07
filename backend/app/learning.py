"""Make unfinished learning exercises explicit at service and HTTP boundaries."""


class LearningExercisePending(NotImplementedError):
    def __init__(self, exercise: str):
        self.exercise = exercise
        super().__init__(f"Phase 2 exercise pending: {exercise}")
