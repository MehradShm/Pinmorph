"""Static Phase 4 inventory. It does not validate deployment, ML quality or completion."""

import argparse
import json
from pathlib import Path

import app
from scripts.phase3_preflight import pending_exercises


def inventory() -> dict:
    exercises = pending_exercises(Path(app.__file__).parent)
    return {
        "phase": "4",
        "status": "started_first_product_modules",
        "check_type": "static_inventory",
        "declared_product_modules": [
            "keyword_search_and_typeahead",
            "public_profiles",
            "user_and_board_follows",
            "blocks_and_mutes",
            "secret_boards_and_sections",
            "in_app_follow_notifications",
        ],
        "pending_learning_exercises": [item for item in exercises if item["phase"] == "4"],
        "serving_dependencies": [item for item in exercises if item["phase"] in {"2", "3A"}],
        "catalog_search_attribution": "request_and_backend_version_only; phase2_core_pending",
        "remaining_product_modules": [
            "interest_onboarding",
            "url_import",
            "comments_reactions_hide_report",
            "email_digest",
            "moderation_queue_classifier_duplicate_gate",
        ],
        "unchecked_acceptance": [
            "attributed_following_and_related_serving",
            "pinned_crop_encoder",
            "real_exact_ann_report",
            "explain_back_results",
            "remaining_product_modules",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fail-on-pending", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(inventory(), indent=2))
    return 2 if arguments.fail_on_pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
