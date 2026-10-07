"""Inspect supplied local MIND files; output inventory only, never a trained-model report."""

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from app.ctr.reader import inspect_partition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--partition", required=True)
    parser.add_argument(
        "--source-timezone", required=True, help="Explicit assumed IANA source zone"
    )
    parser.add_argument(
        "--provenance", choices=("mind_observed", "synthetic_fixture"), required=True
    )
    args = parser.parse_args()
    try:
        report = inspect_partition(args.dataset_dir, args.partition, args.source_timezone)
    except (ValueError, OSError, ZoneInfoNotFoundError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "schema_version": "mind-inventory:v1",
                "check_type": "input_inventory",
                "provenance": args.provenance,
                "source_timezone": args.source_timezone,
                "timestamp_policy": "naive_source_assumed_zone",
                "training_performed": False,
                "supervised_labels_available": report["counts"]["hidden_labels"] == 0
                and report["counts"]["displayed"] > 0,
                **report,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
