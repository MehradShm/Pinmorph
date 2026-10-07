"""Static inventory; run tests and evaluate_lens for acceptance evidence."""

import argparse
import json
from pathlib import Path

import app
from scripts.phase3_preflight import pending_exercises


def inventory():
    exercises = pending_exercises(Path(app.__file__).parent)
    required = [item for item in exercises if item["phase"] in {"2", "4"}]
    report_path = Path("docs/reports/phase4-lens.json")
    return {
        "phase": "4",
        "status": "implemented" if not required else "pending",
        "check_type": "static_inventory",
        "pending_learning_exercises": required,
        "declared_product_modules": [
            "search",
            "profiles",
            "follows",
            "following_feed",
            "related_pins",
            "lens_crop_search",
            "interest_onboarding",
            "secret_boards_sections",
            "url_image_import",
            "comments_reactions_share_hide_report",
            "in_app_activity",
            "local_smtp_digest",
            "moderation_queue",
            "upload_classifier",
            "duplicate_detection",
        ],
        "lens_report_exists": report_path.is_file(),
        "other_phase_exercises": [item for item in exercises if item not in required],
        "learning_discussion": (
            "Explain-back questions in PHASE4_WALKTHROUGH.md; awaiting discussion."
        ),
        "runtime_acceptance": "Run make integration, make browser-check and make lens-evaluate.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fail-on-pending", action="store_true")
    args = parser.parse_args()
    report = inventory()
    print(json.dumps(report, indent=2))
    return 2 if args.fail_on_pending and report["pending_learning_exercises"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
