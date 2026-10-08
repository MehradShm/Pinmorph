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
from app.ml.artifacts import load_artifact
from app.ml.config import EmbeddingConfig
from app.ml.embeddings import ClipPinEmbedder
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
            packages[package] = version("mlflow-skinny" if package == "mlflow" else package)
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
    counts["personalized_vectors"] = db.scalar(
        select(func.count())
        .select_from(PinEmbedding)
        .where(
            PinEmbedding.embedder_version == EmbeddingConfig().version,
        )
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
    parser.add_argument("--encoder", action="store_true", help="Validate the isolated CPU recipe")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--evaluation", type=Path)
    arguments = parser.parse_args()
    # Phase 3B is a later independent track and must not block Phase 3A acceptance.
    exercises = [
        item
        for item in pending_exercises(Path(app.__file__).parent)
        if item["phase"] in {"2", "3A"}
    ]
    runtimes = runtime_inventory()
    blockers = ["core_exercises_pending"] if exercises else []
    missing = [name for name in ("scikit-learn", "mlflow") if not runtimes[name]]
    if missing:
        blockers.append("ml_runtime_not_installed")
    counts = None
    artifact = None
    evaluation = None
    encoder = None
    unchecked = ["runtime_acceptance_tests"]
    if arguments.artifact:
        if not arguments.sha256:
            parser.error("--artifact requires --sha256")
        artifact = load_artifact(arguments.artifact, arguments.sha256)
    else:
        unchecked.append("trained_artifact")
    if arguments.evaluation:
        evaluation = json.loads(arguments.evaluation.read_text())
        if (
            not artifact
            or evaluation.get("model_version") != artifact.version
            or evaluation.get("artifact_sha256") != arguments.sha256
            or evaluation.get("query_count", 0) <= 0
        ):
            raise ValueError("Evaluation does not match the selected artifact")
    else:
        unchecked.append("evaluation_report")
    if arguments.encoder:
        encoder = ClipPinEmbedder(EmbeddingConfig(), Settings().lens_endpoint).metadata()
    else:
        unchecked.append("isolated_encoder_runtime")
    if arguments.database:
        engine = make_engine(Settings())
        try:
            with Session(engine) as db:
                counts = database_inventory(db)
        finally:
            engine.dispose()
        if not counts["imported_interactions"] and not counts["engagements"] and not artifact:
            blockers.append("no_training_interactions")
        if not counts["personalized_vectors"]:
            blockers.append("no_persisted_embeddings")
    else:
        blockers.append("database_not_checked")
    print(
        json.dumps(
            {
                "phase": "3A",
                "status": "prerequisites_pending" if blockers else "inventory_clear",
                "check_type": "static_inventory_not_acceptance",
                "unchecked": unchecked,
                "pending_exercises": exercises,
                "runtime": runtimes,
                "missing_ml_runtime": missing,
                "database": counts,
                "encoder": encoder,
                "artifact_version": artifact.version if artifact else None,
                "evaluation_provenance": evaluation.get("data_provenance") if evaluation else None,
                "blockers": blockers,
            },
            indent=2,
        )
    )
    return 2 if arguments.fail_on_pending and blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
