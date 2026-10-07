"""Opt-in known-answer ML targets; these do not imply a trained production model."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from test_phase3_scaffold import artifact, manifest

from app.feed.contracts import Candidate, FeedContext, RankedCandidate
from app.ml.config import FEATURE_NAMES, RerankingConfig, UserEmbeddingConfig
from app.ml.contracts import Embedding, HistoryEntry, Interaction, VectorItem
from app.ml.embeddings import MeanUserEmbedder, normalize_vector
from app.ml.evaluation import catalog_coverage, ndcg_at_k, recall_at_k
from app.ml.ranking import DiversityReranker, LogisticRegressionRanker
from app.ml.retrieval import ExactVectorRetriever
from app.ml.training import build_examples, fit_ranker, split_interactions
from app.models import Pin

pytestmark = [
    pytest.mark.phase3_exercise,
    pytest.mark.skipif(
        os.getenv("RUN_PHASE3_EXERCISES") != "1", reason="Phase 3A core learning targets"
    ),
]
NOW = datetime(2026, 2, 1, tzinfo=UTC)
CONTEXT = FeedContext("request", "user", NOW, NOW)


def embedding(values=(1, 0), version="embedder:fixture:v1"):
    return Embedding(embedder_version=version, values=values)


def test_normalization_known_vector():
    assert normalize_vector((3, 4)) == pytest.approx((0.6, 0.8))


@pytest.mark.parametrize("values", [(), (0, 0), (float("nan"), 1), (float("inf"), 1)])
def test_normalization_rejects_invalid_vectors(values):
    with pytest.raises(ValueError):
        normalize_vector(values)


def test_user_mean_excludes_future_late_and_other_user_history():
    entries = []
    for event, who, occurred, known, vec in [
        ("a", "user", NOW - timedelta(hours=1), NOW - timedelta(minutes=1), (1, 0)),
        ("b", "user", NOW, NOW, (0, 1)),
        ("c", "user", NOW - timedelta(hours=1), NOW + timedelta(seconds=1), (0, 1)),
        ("d", "other", NOW - timedelta(hours=1), NOW - timedelta(minutes=1), (0, 1)),
    ]:
        entries.append(
            HistoryEntry(
                event_id=event,
                user_id=who,
                pin_id=event,
                occurred_at=occurred,
                known_at=known,
                provenance="imported_purchase_proxy",
                embedding=embedding(vec),
            )
        )
    result = MeanUserEmbedder(UserEmbeddingConfig()).embed(entries, CONTEXT)
    assert result.values == pytest.approx((1, 0))


def test_empty_user_history_triggers_explicit_cold_start():
    assert MeanUserEmbedder(UserEmbeddingConfig()).embed([], CONTEXT) is None


def test_exact_retrieval_known_order_availability_and_model_versions():
    items = [
        VectorItem(
            pin_id=pin_id,
            available_at=available,
            known_at=NOW - timedelta(days=1),
            embedding=embedding(vec, version),
        )
        for pin_id, vec, available, version in [
            ("b", (0.6, 0.8), NOW, "embedder:fixture:v1"),
            ("a", (1, 0), NOW, "embedder:fixture:v1"),
            ("future", (1, 0), NOW + timedelta(seconds=1), "embedder:fixture:v1"),
            ("other_model", (1, 0), NOW, "embedder:fixture:v2"),
        ]
    ]
    hits = ExactVectorRetriever().search(embedding(), items, CONTEXT, 2)
    assert [hit.pin_id for hit in hits] == ["a", "b"]
    assert [hit.similarity for hit in hits] == pytest.approx([1, 0.6])


def test_time_split_keeps_boundary_ties_out_of_training():
    events = [
        Interaction(
            event_id=str(index),
            user_id="user",
            pin_id=str(index),
            occurred_at=time,
            known_at=time,
            provenance="imported_purchase_proxy",
        )
        for index, time in enumerate([NOW - timedelta(seconds=1), NOW, NOW])
    ]
    split = split_interactions(events, manifest().cutoffs)
    assert [row.event_id for row in split["train"]] == ["0"]
    assert [row.event_id for row in split["validation"]] == ["1", "2"]


def test_negative_sampling_does_not_consult_future_positives_or_future_catalog():
    early = NOW - timedelta(days=10)
    later = NOW - timedelta(days=5)
    interactions = [
        Interaction(
            event_id=pin,
            user_id="user",
            pin_id=pin,
            occurred_at=time,
            known_at=time,
            provenance="imported_purchase_proxy",
        )
        for pin, time in [("a", early), ("b", later)]
    ]
    catalog = [
        VectorItem(pin_id=pin, available_at=available, known_at=known, embedding=embedding())
        for pin, available, known in [
            ("a", early - timedelta(days=1), early - timedelta(days=1)),
            ("b", early - timedelta(days=1), early - timedelta(days=1)),
            ("future", NOW, early - timedelta(days=1)),
            ("late", early - timedelta(days=1), NOW),
        ]
    ]

    class FixtureFeatures:
        version = "features:personalized:v1"

        def build(self, user_id, pin_id, as_of):
            assert as_of in (early, later)
            return {name: 0 for name in FEATURE_NAMES}

    policy = manifest().model_copy(update={"negatives_per_positive": 1})
    examples = build_examples(interactions, catalog, FixtureFeatures(), policy)
    early_negatives = [row for row in examples if row.as_of == early and row.label == 0]
    assert [row.pin_id for row in early_negatives] == ["b"]
    assert all(row.label_provenance == "sampled_unobserved" for row in early_negatives)


def test_training_rejects_empty_data_without_fabricating_an_artifact():
    with pytest.raises(ValueError):
        fit_ranker([], manifest())


def test_logistic_scoring_uses_pinned_feature_order_and_scaling():
    model = artifact()
    candidates = [
        Candidate(
            pin=Pin(id=pin_id),
            sources=("fixture",),
            features={name: similarity if name == "similarity" else 0 for name in FEATURE_NAMES},
        )
        for pin_id, similarity in [("b", 0), ("a", 1)]
    ]
    result = LogisticRegressionRanker(model).rank(candidates, CONTEXT)
    assert [row.candidate.pin.id for row in result] == ["a", "b"]
    assert [row.rank_score for row in result] == pytest.approx([0.7310585786, 0.5])


def test_reranker_keeps_unknown_creators_separate_and_suppresses_near_duplicates():
    vectors = {"a": embedding((1, 0)), "b": embedding((1, 0)), "c": embedding((0, 1))}
    candidates = [
        RankedCandidate(Candidate(Pin(id=pin_id, owner_id=None), ("fixture",), {}), score, score)
        for pin_id, score in [("a", 3), ("b", 2), ("c", 1)]
    ]
    result = DiversityReranker(RerankingConfig(per_creator_cap=1), vectors).rerank(
        candidates, CONTEXT
    )
    assert [row.candidate.pin.id for row in result] == ["a", "c"]


def test_recall_known_targets_and_no_empty_target_average():
    assert recall_at_k(["a", "a", "b"], {"a", "b", "c"}, 2) == pytest.approx(1 / 3)
    assert recall_at_k([], set(), 2) is None


def test_ndcg_known_order():
    assert ndcg_at_k(["a", "c", "b"], {"a", "b"}, 3) == pytest.approx(0.9197207891)
    assert ndcg_at_k([], set(), 3) is None


def test_coverage_uses_declared_eligible_catalog():
    assert catalog_coverage([["a", "b"], ["b"]], {"a", "b", "c", "d"}) == 0.5
    assert catalog_coverage([], set()) is None
