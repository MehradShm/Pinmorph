from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.models import Pin


@dataclass(frozen=True)
class FeedContext:
    request_id: str
    user_id: str
    as_of: datetime
    received_at: datetime
    limit: int = 30
    cursor: str | None = None
    surface: str = "home"


@dataclass(frozen=True)
class Candidate:
    pin: Pin
    sources: tuple[str, ...]
    # Already computed using information available strictly before context.as_of.
    features: dict[str, float]
    retrieval_score: float | None = None


@dataclass(frozen=True)
class RankedCandidate:
    candidate: Candidate
    rank_score: float
    final_score: float


class CandidateSource(Protocol):
    version: str

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]: ...


class Ranker(Protocol):
    version: str

    def rank(self, candidates: list[Candidate], context: FeedContext) -> list[RankedCandidate]: ...


class Reranker(Protocol):
    version: str

    def rerank(
        self, candidates: list[RankedCandidate], context: FeedContext
    ) -> list[RankedCandidate]: ...
