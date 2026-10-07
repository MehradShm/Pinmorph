from collections.abc import Callable
from time import perf_counter
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text


class DependencyHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float
    error_type: str | None = None


def check_postgres(engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL statement_timeout = 2000"))
        connection.execute(text("SELECT 1"))
        # Update alongside schema migrations: an older schema is not ready to serve this API.
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "cdfce4ed4eea":
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
