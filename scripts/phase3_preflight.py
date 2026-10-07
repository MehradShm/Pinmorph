"""Read-only Phase 3A inventory; no inference, training, model download, or activation."""

import argparse
import ast
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app
from app.config import Settings
from app.database import make_engine
from app.logging.models import Engagement, FeedRequest, Impression
from app.ml.models import EmbeddingModel, PinEmbedding
from app.models import ImportedInteraction, Pin


def pending_exercises(root: Path) -> list[dict]:
    """Static inventory of explicit pending raises; successful tests remain the acceptance gate."""
    records = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            if (
                not isinstance(node.exc.func, ast.Name)
                or node.exc.func.id != "LearningExercisePending"
            ):
                continue
            if not node.exc.args or not isinstance(node.exc.args[0], ast.Constant):
                continue
            exercise = node.exc.args[0].value
            if not isinstance(exercise, str):
                continue
            phase = next(
                (
                    kw.value.value
                    for kw in node.exc.keywords
                    if kw.arg == "phase" and isinstance(kw.value, ast.Constant)
                ),
                "2",
            )
            record = records.setdefault(
                exercise, {"exercise": exercise, "phase": phase, "locations": []}
            )
            record["locations"].append(f"{path.relative_to(root)}:{node.lineno}")
    return [records[key] for key in sorted(records)]


def runtime_inventory() -> dict[str, str | None]:
    packages = {}
    for package in ("pgvector", "numpy", "torch", "open_clip_torch", "scikit-learn", "mlflow"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return packages


def database_inventory(db: Session) -> dict[str, int]:
    tables = {
        "feed_requests": FeedRequest,
        "impressions": Impression,
        "engagements": Engagement,
        "imported_interactions": ImportedInteraction,
        "embedding_models": EmbeddingModel,
        "pin_embeddings": PinEmbedding,
    }
    counts = {
        name: db.scalar(select(func.count()).select_from(model)) for name, model in tables.items()
    }
    counts["ready_pins"] = db.scalar(
        select(func.count()).select_from(Pin).where(Pin.status == "ready")
    )
    counts["demo_pins"] = db.scalar(
        select(func.count()).select_from(Pin).where(Pin.provenance == "synthetic_demo")
    )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", action="store_true", help="Also query the configured local DB"
    )
    parser.add_argument(
        "--fail-on-pending", action="store_true", help="Exit 2 for known missing prerequisites"
    )
    arguments = parser.parse_args()
    exercises = pending_exercises(Path(app.__file__).parent)
    runtimes = runtime_inventory()
    blockers = ["core_exercises_pending"] if exercises else []
    missing = [
        name
        for name in ("torch", "open_clip_torch", "scikit-learn", "mlflow")
        if not runtimes[name]
    ]
    if missing:
        blockers.append("ml_runtime_not_installed")
    counts = None
    if arguments.database:
        engine = make_engine(Settings())
        try:
            with Session(engine) as db:
                counts = database_inventory(db)
        finally:
            engine.dispose()
        if not counts["imported_interactions"] and not counts["engagements"]:
            blockers.append("no_training_interactions")
        if not counts["pin_embeddings"]:
            blockers.append("no_persisted_embeddings")
    else:
        blockers.append("database_not_checked")
    print(
        json.dumps(
            {
                "phase": "3A",
                "status": "prerequisites_pending" if blockers else "inventory_clear",
                "check_type": "static_inventory_not_acceptance",
                "unchecked": ["trained_artifact", "evaluation_report", "runtime_acceptance"],
                "pending_exercises": exercises,
                "runtime": runtimes,
                "missing_ml_runtime": missing,
                "database": counts,
                "blockers": blockers,
            },
            indent=2,
        )
    )
    return 2 if arguments.fail_on_pending and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
