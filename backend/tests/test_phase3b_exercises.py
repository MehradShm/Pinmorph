"""Opt-in known-answer targets; these intentionally fail while the CTR core is pending."""

import math
import os

import pytest
from test_phase3b_scaffold import FIXTURE, ctr_artifact, ctr_manifest

from app.ctr.contracts import FEATURE_NAMES, CTRExample, Prediction
from app.ctr.evaluation import evaluate
from app.ctr.pipeline import (
    HistoryContentFeatures,
    LogisticCTRPredictor,
    build_examples,
    fit_constant,
    fit_logistic,
    split_impressions,
)
from app.ctr.reader import read_behaviors, read_news

pytestmark = [
    pytest.mark.phase3b_exercise,
    pytest.mark.skipif(
        os.getenv("RUN_PHASE3B_EXERCISES") != "1", reason="CTR core learning target"
    ),
]


def records():
    return list(read_behaviors(FIXTURE / "behaviors.tsv", "train", "UTC"))


def example(label=0, history_length=0):
    return CTRExample(
        impression_id="train:1",
        news_id="N1",
        occurred_at=records()[0].occurred_at,
        label=label,
        features={
            name: float(history_length if name == "history_length" else 0) for name in FEATURE_NAMES
        },
    )


def test_group_splits_keep_tied_impressions_and_all_their_candidates_together():
    split = split_impressions(records(), ctr_manifest().cutoffs)
    assert {name: [item.impression_id for item in group] for name, group in split.items()} == {
        "train": ["train:1", "train:2"],
        "validation": ["train:3"],
        "test": ["train:4"],
    }


def test_history_content_features_have_known_values():
    record = records()[0]
    result = HistoryContentFeatures().build(
        record, "N3", read_news(FIXTURE / "news.tsv"), record.occurred_at
    )
    assert result == {
        "history_length": 2,
        "category_history_fraction": 0.5,
        "title_token_overlap": 0.5,
        "title_length": 2,
    }


def test_features_ignore_current_labels_and_candidate_order():
    record = records()[0]
    changed = record.model_copy(
        update={
            "displayed": tuple(
                item.model_copy(update={"clicked": 1 - item.clicked})
                for item in reversed(record.displayed)
            )
        }
    )
    builder, news = HistoryContentFeatures(), read_news(FIXTURE / "news.tsv")
    assert builder.build(record, "N3", news, record.occurred_at) == builder.build(
        changed, "N3", news, changed.occurred_at
    )


def test_cold_start_and_missing_history_metadata_are_explicit():
    record = records()[1]
    result = HistoryContentFeatures().build(
        record, "N1", read_news(FIXTURE / "news.tsv"), record.occurred_at
    )
    assert (
        result["history_length"]
        == result["category_history_fraction"]
        == result["title_token_overlap"]
        == 0
    )
    missing = records()[3]
    result = HistoryContentFeatures().build(
        missing, "N2", read_news(FIXTURE / "news.tsv"), missing.occurred_at
    )
    assert result["history_length"] == 1
    assert result["category_history_fraction"] == result["title_token_overlap"] == 0


def test_examples_preserve_every_displayed_observed_label():
    examples = build_examples(records(), read_news(FIXTURE / "news.tsv"), HistoryContentFeatures())
    assert len(examples) == 8 and sum(item.label for item in examples) == 3
    assert {item.impression_id for item in examples} == {
        f"train:{number}" for number in range(1, 5)
    }


def test_hidden_labels_are_rejected_in_supervised_examples():
    record = records()[0]
    hidden = record.model_copy(
        update={
            "displayed": tuple(
                item.model_copy(update={"clicked": None}) for item in record.displayed
            )
        }
    )
    with pytest.raises(ValueError, match="label"):
        build_examples([hidden], read_news(FIXTURE / "news.tsv"), HistoryContentFeatures())


def test_constant_baseline_uses_natural_training_prevalence():
    baseline = fit_constant([example(1), example(), example(), example()])
    assert baseline.predict([example(1), example(1)]) == [0.25, 0.25]


def test_constant_fit_rejects_empty_input():
    with pytest.raises(ValueError):
        fit_constant([])


def test_logistic_score_uses_its_own_ordered_artifact():
    scores = LogisticCTRPredictor(ctr_artifact()).predict([example(history_length=1), example()])
    assert scores == pytest.approx([1 / (1 + math.exp(-1)), 0.5])


def test_fitting_rejects_held_out_rows_before_training():
    held_out = example().model_copy(update={"occurred_at": records()[3].occurred_at})
    with pytest.raises(ValueError, match="train"):
        fit_logistic([example(1), held_out], ctr_manifest())


def test_ctr_and_grouped_ranking_metrics_have_known_values():
    values = [
        Prediction(
            impression_id=f"g{index // 2}", news_id=f"N{index}", label=label, probability=prob
        )
        for index, (label, prob) in enumerate([(0, 0.1), (1, 0.9), (0, 0.2), (1, 0.8)])
    ]
    metrics = evaluate(values, k=2, bins=2)
    assert metrics.pooled_auc == metrics.macro_group_auc == metrics.macro_ndcg == 1
    assert metrics.log_loss == pytest.approx(-(math.log(0.9) + math.log(0.8)) / 2)
    assert metrics.brier_score == pytest.approx(0.025)
    assert metrics.ece == pytest.approx(0.15)
    assert metrics.auc_eligible_groups == metrics.ranking_eligible_groups == 2


def test_equal_scores_get_half_auc_and_deterministic_group_ranking():
    values = [
        Prediction(impression_id="g", news_id="N1", label=0, probability=0.5),
        Prediction(impression_id="g", news_id="N2", label=1, probability=0.5),
    ]
    metrics = evaluate(values, k=2, bins=2)
    assert metrics.pooled_auc == 0.5
    assert metrics.log_loss == pytest.approx(math.log(2))
    assert metrics.brier_score == 0.25 and metrics.ece == 0
    assert metrics.macro_ndcg == pytest.approx(1 / math.log2(3))


def test_single_class_groups_have_undefined_auc_and_explicit_denominators():
    values = [Prediction(impression_id="g", news_id="N1", label=0, probability=0.5)]
    metrics = evaluate(values)
    assert metrics.pooled_auc is metrics.macro_group_auc is metrics.macro_ndcg is None
    assert metrics.auc_eligible_groups == metrics.ranking_eligible_groups == 0


def test_evaluation_rejects_duplicate_candidate_identity():
    value = Prediction(impression_id="g", news_id="N1", label=0, probability=0.5)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate([value, value])


def test_empty_evaluation_is_undefined_not_zero():
    metrics = evaluate([])
    assert metrics.candidate_count == metrics.impression_count == 0
    assert all(
        value is None
        for name, value in metrics.model_dump().items()
        if name
        not in {
            "candidate_count",
            "impression_count",
            "auc_eligible_groups",
            "ranking_eligible_groups",
        }
    )
