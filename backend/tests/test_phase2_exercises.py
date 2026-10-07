"""Executable learning targets. Opt in once implementing the marked core functions."""

from datetime import UTC, datetime

import pytest

from app.experiments.assignment import assign_arm
from app.experiments.config import Experiment
from app.feed.contracts import Candidate, FeedContext
from app.ml.baselines import PopularityRanker, RecencyRanker
from app.models import Pin

pytestmark = pytest.mark.phase2_exercise


@pytest.mark.parametrize(
    ("user_id", "arm"),
    [
        ("00000000-0000-4000-8000-000000000001", "recency"),  # golden bucket 1358
        ("00000000-0000-4000-8000-000000000002", "popularity"),  # golden bucket 6236
        ("seed-user-42", "recency"),  # golden bucket 4510
    ],
)
def test_assignment_matches_pinned_digest_vectors(user_id, arm):
    assert assign_arm(user_id, Experiment()).name == arm
    assert assign_arm(user_id, Experiment()).name == arm


def candidate(pin_id, age, saves=0, imported=0):
    return Candidate(
        pin=Pin(id=pin_id),
        sources=("candidate:catalog:v1",),
        features={
            "age_hours": age,
            "observed_save_count": saves,
            "imported_purchase_count": imported,
        },
    )


@pytest.mark.parametrize(
    ("ranker", "expected"),
    [
        (RecencyRanker(), ["b", "a", "c"]),
        (PopularityRanker(), ["a", "c", "b"]),
    ],
)
def test_baselines_compare_on_identical_known_candidates(ranker, expected):
    context = FeedContext("request", "user", datetime.now(UTC), datetime.now(UTC))
    items = [candidate("c", 20, imported=4), candidate("a", 10, saves=4), candidate("b", 1)]
    ranked = ranker.rank(items, context)
    assert [row.candidate.pin.id for row in ranked] == expected
    assert [item.pin.id for item in items] == ["c", "a", "b"]  # input order is untouched
    assert all("position" not in row.candidate.features for row in ranked)


def test_popularity_without_history_and_ties_falls_back_to_recency_then_id():
    context = FeedContext("request", "user", datetime.now(UTC), datetime.now(UTC))
    items = [candidate("c", 10), candidate("b", 1), candidate("a", 1)]
    assert [row.candidate.pin.id for row in PopularityRanker().rank(items, context)] == [
        "a",
        "b",
        "c",
    ]
