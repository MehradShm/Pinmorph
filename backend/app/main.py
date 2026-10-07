import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer

from app.api import router
from app.boards.api import router as boards_router
from app.config import Settings
from app.database import make_engine
from app.discovery.api import router as discovery_router
from app.discovery.service import DiscoveryServices
from app.feed.api import router as feed_router
from app.feed.service import FeedService
from app.health import check_dependencies, check_postgres
from app.learning import LearningExercisePending
from app.logging.service import EventIngestor
from app.operations.api import router as operations_router
from app.operations.metrics import RequestMetrics
from app.search.api import router as search_router
from app.search.service import PostgresTextSearch
from app.social.api import router as social_router
from app.storage import make_s3_client

logger = logging.getLogger("pinmorph.requests")


def create_app(
    settings: Settings | None = None,
    *,
    health_checks: dict[str, Callable[[], object]] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    # Validate versioned configuration before the application starts accepting requests.
    feed_service = FeedService(settings.feed_config)
    discovery_services = DiscoveryServices(settings.discovery_config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        logging.basicConfig(level=settings.log_level, format="%(message)s")
        engine = make_engine(settings)
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=settings.health_timeout_seconds,
            socket_timeout=settings.health_timeout_seconds,
        )
        storage = make_s3_client(settings)
        application.state.settings = settings
        application.state.feed_service = feed_service
        application.state.search_backend = PostgresTextSearch()
        application.state.discovery_services = discovery_services
        application.state.event_ingestor = EventIngestor()
        application.state.request_metrics = RequestMetrics()
        application.state.engine = engine
        application.state.storage = storage
        application.state.queue = Queue("default", connection=redis, serializer=JSONSerializer)
        application.state.health_checks = (
            health_checks
            if health_checks is not None
            else {
                "postgres": lambda: check_postgres(engine),
                "redis": redis.ping,
                "object_storage": lambda: storage.head_bucket(Bucket=settings.s3_bucket),
            }
        )
        try:
            yield
        finally:
            storage.close()
            redis.close()
            engine.dispose()

    application = FastAPI(title="Pinmorph", version="0.1.0", lifespan=lifespan)
    application.include_router(router)
    application.include_router(feed_router)
    application.include_router(search_router)
    application.include_router(social_router)
    application.include_router(boards_router)
    application.include_router(discovery_router)
    application.include_router(operations_router)

    @application.exception_handler(LearningExercisePending)
    async def pending_exercise(request: Request, exc: LearningExercisePending):
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Phase {exc.phase} learning implementation is pending",
                "exercise": exc.exercise,
                "request_id": request.state.request_id,
            },
        )

    @application.middleware("http")
    async def request_diagnostics(request: Request, call_next):
        # Operational access logs only; recommendation/event logging is a phase 2 learning task.
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            if request.url.path.startswith("/api/") and any(
                name.lower().startswith("x-sim-") for name in request.headers
            ):
                # Run attribution is not implemented yet; never silently ignore an override.
                response = JSONResponse(
                    status_code=422,
                    content={"detail": "Simulator request overrides are not implemented"},
                )
            else:
                response = await call_next(request)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "request_failed",
                        "request_id": request_id,
                        "error_type": type(exc).__name__,
                    }
                )
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith(("/api/", "/sim/")):
            response.headers.setdefault("Cache-Control", "no-store")
        route = request.scope.get("route")
        request.app.state.request_metrics.observe(
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        logger.info(
            json.dumps(
                {
                    "event": "request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": round((perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    @application.get("/health/live")
    def liveness():
        return {"status": "ok"}

    @application.get("/health/ready")
    def readiness(request: Request):
        results = check_dependencies(request.app.state.health_checks)
        ready = all(result.status == "ok" for result in results.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "request_id": request.state.request_id,
                "dependencies": {name: result.model_dump() for name, result in results.items()},
            },
        )

    return application


app = create_app()
