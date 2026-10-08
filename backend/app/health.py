from collections.abc import Callable
from time import perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import text

from app.ml.config import EmbeddingConfig


def check_lens(settings):
    with httpx.Client(timeout=settings.health_timeout_seconds, trust_env=False) as client:
        response = client.get(settings.lens_endpoint + "/health")
        response.raise_for_status()
        info = response.json()
        recipe = EmbeddingConfig()
        if info.get("version") != "embedder:clip-image-crop:v1" or any(
            info.get("personalization", {}).get(name) != getattr(recipe, name)
            for name in (
                "version",
                "weights_sha256",
                "dimension",
                "preprocess_version",
                "text_policy",
                "image_weight",
            )
        ):
            raise RuntimeError("Incompatible Lens runtime")


class DependencyHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float
    error_type: str | None = None


def check_postgres(engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL statement_timeout = 2000"))
        connection.execute(text("SELECT 1"))
        # Update alongside schema migrations: an older schema is not ready to serve this API.
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "72aa31f096bc":
            raise RuntimeError("Database schema does not match this application version")
        if not connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ):
            raise RuntimeError("The vector extension is missing")


def check_dependencies(checks: dict[str, Callable[[], object]]) -> dict[str, DependencyHealth]:
    results = {}
    for name, check in checks.items():
        started = perf_counter()
        try:
            check()
            results[name] = DependencyHealth(
                status="ok", latency_ms=round((perf_counter() - started) * 1000, 2)
            )
        except Exception as exc:
            # Connection messages may include credentials; return only their exception class.
            results[name] = DependencyHealth(
                status="error",
                latency_ms=round((perf_counter() - started) * 1000, 2),
                error_type=type(exc).__name__,
            )
    return results
