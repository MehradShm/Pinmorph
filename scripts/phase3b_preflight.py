"""Static CTR/adapter prerequisite inventory, never a completion or quality certificate."""

import argparse
import json
from pathlib import Path

import app
from scripts.phase3_preflight import pending_exercises, runtime_inventory


def inventory() -> dict:
    core = [item for item in pending_exercises(Path(app.__file__).parent) if item["phase"] == "3B"]
    runtime = {
        key: value
        for key, value in runtime_inventory().items()
        if key in {"scikit-learn", "mlflow"}
    }
    return {
        "phase": "3B",
        "status": "prerequisites_pending",
        "check_type": "static_inventory",
        "pending_ctr_exercises": core,
        "runtime": runtime,
        "missing_runtime": [key for key, value in runtime.items() if value is None],
        "mind_input": "not_checked",
        "minimum_simulator_adapter": "pending",
        "unchecked": [
            "real_mind_input",
            "fitted_ctr_model",
            "baseline_quality_comparison",
            "run_attribution",
            "quiescent_reset",
            "simulator_workloads",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fail-on-pending", action="store_true")
    args = parser.parse_args()
    print(json.dumps(inventory(), indent=2))
    return 2 if args.fail_on_pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
