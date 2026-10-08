"""Local hourly rollups with seven UTC days of late-event repair."""

import logging
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import utcnow
from app.monetization.analytics import rebuild


def main():
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(Settings())
    last_hour = None
    try:
        while True:
            now = utcnow()
            hour = now.replace(minute=0, second=0, microsecond=0)
            if hour != last_hour:
                try:
                    with Session(engine) as db:
                        result = rebuild(db, now.date() - timedelta(days=6), now.date())
                    last_hour = hour
                    logging.info("analytics_rebuilt: %s pins", result["pin_count"])
                except Exception as exc:
                    logging.error("analytics_rebuild_failed: %s", type(exc).__name__)
            time.sleep(60)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
