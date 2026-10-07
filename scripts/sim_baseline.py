"""Initial seed of a declared disposable stack through the existing media/import services.

This is not a reset: no data is removed, jobs are not canceled, and runs are not closed.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from app.config import Settings
from app.operations.contracts import BaselineManifest
from scripts.seed import build_demo_plan, import_plan, wait_for_media


def load_baseline(path: Path, expected_sha256: str, settings: Settings) -> BaselineManifest:
    if not settings.sim_mode or not settings.sim_disposable:
        raise ValueError(
            "Baseline initialization requires the declared disposable simulation stack"
        )
    database = make_url(settings.database_url.get_secret_value())
    redis = urlsplit(settings.redis_url.get_secret_value())
    if (
        database.host != "postgres"
        or database.database != "pinmorph_sim"
        or redis.hostname != "redis"
        or redis.port != 6379
        or redis.path != "/0"
        or settings.s3_endpoint_url != "http://minio:9000"
        or settings.s3_bucket != "pinmorph-sim-media"
    ):
        raise ValueError(
            "Initial seed must run inside the generated stack with its isolated targets"
        )
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Baseline checksum does not match the declared manifest")
    baseline = BaselineManifest.model_validate_json(payload)
    if baseline.environment_id != settings.sim_environment_id:
        raise ValueError("Baseline and application environment IDs do not match")
    if baseline.feed_config != settings.feed_config.model_dump(mode="json"):
        raise ValueError("Baseline and application feed configurations do not match")
    if baseline.model_artifacts:
        raise ValueError("Model artifact baseline restoration is not implemented")
    return baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("/control/baseline.json"))
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--wait", type=int, default=120)
    args = parser.parse_args()
    if args.wait < 0:
        parser.error("Wait must be nonnegative")
    try:
        settings = Settings()
        baseline = load_baseline(args.manifest, args.expected_sha256, settings)
        plan = build_demo_plan(baseline.seed, baseline.reference_time, baseline.catalog_size)
        result = import_plan(plan, settings)
        if args.wait:
            result["media_status"] = wait_for_media(plan.run_id, args.wait)
        result["import_run_id"] = result.pop("run_id")
        result.update(
            environment_id=baseline.environment_id,
            baseline_sha256=args.expected_sha256,
            operation="initial_seed",
            reset_performed=False,
        )
    except (ValueError, OSError, TimeoutError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
