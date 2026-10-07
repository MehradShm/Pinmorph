"""Read-only dependency/backlog snapshots; independent of unfinished ranking/event core."""

from datetime import UTC, datetime
from time import perf_counter

from rq import worker_registration
from rq.job import Job
from rq.utils import as_text, utcparse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.logging.models import Engagement, EventReceipt
from app.ml.models import PinEmbedding
from app.models import Pin


def database_snapshot(engine) -> dict:
    with Session(engine) as db:
        db.execute(text("SET LOCAL statement_timeout = 2000"))
        pins = dict(db.execute(select(Pin.status, func.count()).group_by(Pin.status)).all())
        outcomes = dict(
            db.execute(
                select(EventReceipt.outcome, func.count()).group_by(EventReceipt.outcome)
            ).all()
        )
        return {
            "pins_by_status": pins,
            "event_receipts_by_outcome": outcomes,
            "pending_engagements": db.scalar(
                select(func.count())
                .select_from(Engagement)
                .where(Engagement.attribution_status == "pending")
            ),
            "latest_embedding_known_at": db.scalar(select(func.max(PinEmbedding.known_at))),
            "event_ingestion_core": "pending",
        }


def queue_snapshot(queue, now: datetime) -> dict:
    ids = queue.get_job_ids(0, 100)
    jobs = (
        Job.fetch_many(ids, connection=queue.connection, serializer=queue.serializer) if ids else []
    )
    enqueued = [job.enqueued_at for job in jobs if job is not None and job.enqueued_at is not None]
    oldest = min(enqueued) if enqueued else None
    workers = []
    stale_workers = 0
    # Worker.all() deletes stale registrations. Read hashes directly to preserve read-only behavior.
    keys = sorted(worker_registration.get_keys(queue=queue))
    for key in keys[:100]:
        state, heartbeat = queue.connection.hmget(key, "state", "last_heartbeat")
        if state is None and heartbeat is None:
            stale_workers += 1
            continue
        workers.append(
            {
                "name": key.removeprefix("rq:worker:"),
                "state": as_text(state) if state is not None else "unknown",
                "last_heartbeat": utcparse(as_text(heartbeat)) if heartbeat else None,
            }
        )
    # Direct ZCARD avoids RQ registry cleanup side effects during a diagnostic read.
    registry_counts = {
        name: queue.connection.zcard(registry.key)
        for name, registry in (
            ("started", queue.started_job_registry),
            ("failed", queue.failed_job_registry),
            ("scheduled", queue.scheduled_job_registry),
            ("deferred", queue.deferred_job_registry),
        )
    }
    return {
        "name": queue.name,
        "queued": queue.count,
        "registries": registry_counts,
        "sampled_queue_head_jobs": len(ids),
        "queue_head_sample_limit": 100,
        "oldest_sampled_enqueued_at": oldest,
        "oldest_sampled_queue_age_seconds": max(0, (now - oldest).total_seconds())
        if oldest
        else None,
        "workers": workers,
        "registered_worker_count": len(keys),
        "worker_sample_limit": 100,
        "stale_sampled_worker_registrations": stale_workers,
    }


def collect_diagnostics(engine, queue, metrics, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    result = {"observed_at": now, "requests": metrics.snapshot(), "components": {}}
    for name, collect in (
        ("database", lambda: database_snapshot(engine)),
        ("queue", lambda: queue_snapshot(queue, now)),
    ):
        started = perf_counter()
        try:
            result["components"][name] = {"status": "ok", "data": collect()}
        except Exception as exc:
            result["components"][name] = {"status": "error", "error_type": type(exc).__name__}
        result["components"][name]["latency_ms"] = (perf_counter() - started) * 1000
    return result
