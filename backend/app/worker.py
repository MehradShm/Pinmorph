import logging

from redis import Redis
from rq import Worker
from rq.serializers import JSONSerializer

from app.config import Settings


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    with Redis.from_url(settings.redis_url.get_secret_value()) as connection:
        # Run inside Linux containers; RQ forks a process for each job.
        worker = Worker(["default"], connection=connection, serializer=JSONSerializer)
        worker.work(logging_level=settings.log_level, with_scheduler=True)


if __name__ == "__main__":
    main()
