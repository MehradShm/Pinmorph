"""Generate private, immutable setup files for a separate disposable simulation stack."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path
from tempfile import mkdtemp

from app.experiments.config import FeedConfig
from app.operations.contracts import BaselineManifest
from scripts.seed import parse_reference_time


def generate_environment(directory: Path, baseline: BaselineManifest) -> dict:
    """Stage both files then rename; an existing baseline is verified and never replaced."""
    payload = baseline.model_dump_json(indent=2).encode() + b"\n"
    checksum = hashlib.sha256(payload).hexdigest()
    if directory.exists():
        if not directory.is_dir() or (directory / "baseline.json").read_bytes() != payload:
            raise ValueError("Environment directory already exists with a different baseline")
        if not (directory / "simulation.env").is_file():
            raise ValueError("Environment is missing its private configuration")
        return {
            "environment_id": baseline.environment_id,
            "baseline_sha256": checksum,
            "directory": str(directory.resolve()),
            "created": False,
            "supports_reset": False,
        }
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(mkdtemp(prefix=".sim-environment-", dir=directory.parent))
    try:
        os.chmod(temporary, 0o700)
        (temporary / "baseline.json").write_bytes(payload)
        env = {
            "POSTGRES_USER": "pinmorph",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "POSTGRES_DB": "pinmorph_sim",
            "POSTGRES_PORT": "16432",
            "REDIS_PORT": "17379",
            "MINIO_ROOT_USER": "pinmorph-sim",
            "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(32),
            "MINIO_PORT": "9100",
            "MINIO_CONSOLE_PORT": "9101",
            "API_PORT": "8002",
            "WEB_PORT": "8082",
            "APP_IMAGE": "pinmorph-sim-app:local",
            "WEB_IMAGE": "pinmorph-sim-web:local",
            "CHECKS_IMAGE": "pinmorph-sim-checks:local",
            "S3_BUCKET": "pinmorph-sim-media",
            "SIM_MODE": "true",
            "SIM_DISPOSABLE": "true",
            "SIM_ENVIRONMENT_ID": baseline.environment_id,
            "SIM_CONTROL_TOKEN": secrets.token_urlsafe(32),
            "SIM_CONTROL_DIR": str(directory.resolve()),
            "FEED_CONFIG": json.dumps(baseline.feed_config, separators=(",", ":")),
            "TRUSTED_ORIGINS": '["http://localhost:8082","http://127.0.0.1:8082"]',
        }
        env_path = temporary / "simulation.env"
        env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
        os.chmod(env_path, 0o600)
        os.rename(temporary, directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "environment_id": baseline.environment_id,
        "baseline_sha256": checksum,
        "directory": str(directory.resolve()),
        "created": True,
        "supports_reset": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--reference-time", type=parse_reference_time, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--catalog-size", type=int, default=32)
    args = parser.parse_args()
    try:
        baseline = BaselineManifest(
            environment_id=args.environment_id,
            reference_time=args.reference_time,
            seed=args.seed,
            catalog_size=args.catalog_size,
            feed_config=FeedConfig().model_dump(mode="json"),
        )
        result = generate_environment(args.directory, baseline)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
