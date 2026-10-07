"""Known-answer Lens targets; no synthetic vectors are used in application serving."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.feed.contracts import FeedContext
from app.ml.contracts import Embedding, RetrievalHit, VectorItem
from app.ml.discovery import compare_lens_retrieval, eligible_lens_vectors

pytestmark = [
    pytest.mark.phase4_exercise,
    pytest.mark.skipif(os.getenv("RUN_PHASE4_EXERCISES") != "1", reason="Phase 4 learning core"),
]


def hit(pin_id):
    return RetrievalHit(pin_id=pin_id, similarity=0.5)


def test_exact_ann_overlap_is_not_user_relevance():
    assert compare_lens_retrieval([hit("a"), hit("b")], [hit("a"), hit("c")], 2) == 0.5
    assert compare_lens_retrieval([hit("a")], [hit("a"), hit("b")], 10) == 1
    assert compare_lens_retrieval([], [], 5) is None


@pytest.mark.parametrize("k", [0, -1])
def test_lens_comparison_rejects_invalid_k(k):
    with pytest.raises(ValueError):
        compare_lens_retrieval([], [], k)


def test_lens_comparison_rejects_duplicate_identity():
    with pytest.raises(ValueError):
        compare_lens_retrieval([hit("a"), hit("a")], [hit("a")], 2)


def test_lens_vectors_keep_only_available_known_compatible_items():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    context = FeedContext("request", "user", now, now)
    items = [
        VectorItem(
            pin_id=pin_id,
            available_at=available,
            known_at=known,
            embedding=Embedding(embedder_version=version, values=(1, 0)),
        )
        for pin_id, available, known, version in [
            ("ready", now, now, "fixture:v1"),
            ("future", now + timedelta(seconds=1), now, "fixture:v1"),
            ("late", now, now + timedelta(seconds=1), "fixture:v1"),
            ("other", now, now, "fixture:v2"),
        ]
    ]
    assert [row.pin_id for row in eligible_lens_vectors(items, "fixture:v1", context)] == ["ready"]


def test_lens_vectors_reject_duplicate_identity():
    now = datetime(2026, 10, 7, tzinfo=UTC)
    context = FeedContext("request", "user", now, now)
    item = VectorItem(
        pin_id="a",
        available_at=now,
        known_at=now,
        embedding=Embedding(embedder_version="fixture:v1", values=(1, 0)),
    )
    with pytest.raises(ValueError):
        eligible_lens_vectors([item, item], "fixture:v1", context)
