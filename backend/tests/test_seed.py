import argparse
import csv
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image

from scripts.seed import build_demo_plan, build_hm_plan, parse_reference_time


@pytest.fixture
def hm_folder(tmp_path):
    def write_csv(name, fields, rows):
        with (tmp_path / name).open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)

    write_csv(
        "articles.csv",
        ["article_id", "prod_name", "detail_desc"],
        [
            [100001, "Shirt", "Green shirt"],
            [100002, "Trousers", "Soft trousers"],
            [100003, "No image", "Skipped"],
        ],
    )
    write_csv("customers.csv", ["customer_id"], [["a"], ["b"]])
    write_csv(
        "transactions_train.csv",
        ["t_dat", "customer_id", "article_id", "price"],
        [
            ["2020-09-01", "a", 100001, ".1"],
            ["2020-09-01", "b", 100001, ".1"],
            ["2020-09-02", "a", 100002, ".2"],
            ["2020-09-03", "a", 100001, ".1"],
            ["2020-09-04", "b", 100002, ".2"],
        ],
    )
    folder = tmp_path / "images" / "000"
    folder.mkdir(parents=True)
    for item in [100001, 100002]:
        Image.new("RGB", (40, 60), "green").save(folder / f"{item:010d}.jpg")
    return tmp_path


def test_manifest_is_reproducible_and_preserves_provenance_and_day_ties(hm_folder):
    reference = datetime(2026, 10, 7, tzinfo=UTC)
    first = build_hm_plan(hm_folder, 42, reference, 10, 10, True)
    second = build_hm_plan(hm_folder, 42, reference, 10, 10, True)
    assert first.manifest == second.manifest
    assert first.run_id == second.run_id
    assert first.manifest["counts"] == {
        "items": 2,
        "users": 2,
        "purchases": 5,
        "articles_missing_images": 1,
        "purchases_unknown_customers": 0,
    }
    assert first.manifest["label_provenance"] == "imported_purchase_proxy"
    offset = timedelta(seconds=first.manifest["time_offset_seconds"])
    assert max(p.original_time + offset for p in first.purchases) == reference
    assert first.purchases[0].original_time == first.purchases[1].original_time
    for purchase in first.purchases:
        assert first.availability[purchase.article_id] <= purchase.original_time + offset
    assert (
        first.manifest["cutoffs"]["train_end_exclusive"]
        < first.manifest["cutoffs"]["validation_end_exclusive"]
    )


def test_reference_time_excludes_future_transactions(hm_folder):
    plan = build_hm_plan(hm_folder, 42, datetime(2020, 9, 2, tzinfo=UTC), 10, 10)
    assert len(plan.purchases) == 3
    assert plan.manifest["time_offset_seconds"] == 0
    assert plan.manifest["cutoffs"]["status"] == "insufficient_unique_days"


def test_content_or_sampling_change_produces_new_run_id(hm_folder):
    reference = datetime(2026, 10, 7, tzinfo=UTC)
    first = build_hm_plan(hm_folder, 42, reference, 10, 10)
    assert first.run_id != build_hm_plan(hm_folder, 43, reference, 10, 10).run_id
    with (hm_folder / "customers.csv").open("a") as stream:
        stream.write("c\n")
    assert first.run_id != build_hm_plan(hm_folder, 42, reference, 10, 10).run_id


def test_bad_inputs_fail_before_any_service_writes(tmp_path):
    with pytest.raises(ValueError, match="Missing input"):
        build_hm_plan(tmp_path, 42, datetime.now(UTC), 10, 10)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_reference_time("2026-10-07")


def test_demo_is_explicitly_synthetic_and_reproducible():
    reference = datetime(2026, 10, 7, tzinfo=UTC)
    first = build_demo_plan(42, reference, 3)
    second = build_demo_plan(42, reference, 3)
    assert first.run_id == second.run_id
    assert first.manifest["dataset"] == "synthetic_demo"
    assert first.purchases == []
