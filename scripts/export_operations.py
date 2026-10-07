"""Export authenticated diagnostics from the declared local simulation environment."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.artifact_io import publish_bytes
from app.config import Settings


def export(settings: Settings, api_url: str) -> dict:
    url = urlsplit(api_url)
    if (
        url.scheme != "http"
        or url.hostname not in {"localhost", "127.0.0.1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Diagnostic export requires a local loopback HTTP API origin")
    if not settings.sim_mode:
        raise ValueError("Use the generated simulation.env for the declared disposable environment")
    headers = {"X-Sim-Control-Token": settings.sim_control_token.get_secret_value()}
    with httpx.Client(
        base_url=api_url, headers=headers, timeout=10, follow_redirects=False, trust_env=False
    ) as client:
        capabilities = client.get("/sim/capabilities")
        capabilities.raise_for_status()
        if capabilities.json().get("environment_id") != settings.sim_environment_id:
            raise ValueError("API environment does not match the supplied configuration")
        readiness = client.get("/health/ready")
        if readiness.status_code not in {200, 503}:
            readiness.raise_for_status()
        response = client.get("/sim/diagnostics")
        response.raise_for_status()
    return {
        "schema_version": "operations-observation:v1",
        "environment_id": settings.sim_environment_id,
        "capabilities": capabilities.json(),
        "readiness": {"http_status": readiness.status_code, "data": readiness.json()},
        "diagnostics": response.json(),
        "exercise_outcome": "not_assessed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8002")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = export(Settings(_env_file=args.env_file), args.api_url)
        if args.output:
            checksum = publish_bytes(args.output, json.dumps(report, indent=2).encode() + b"\n")
            print(json.dumps({"path": str(args.output), "sha256": checksum}))
        else:
            print(json.dumps(report, indent=2))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
