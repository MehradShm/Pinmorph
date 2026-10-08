"""Rebuild creator analytics for explicit UTC days; does not change raw events."""

import argparse
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import utcnow
from app.monetization.analytics import rebuild


def main():
    today = utcnow().date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=6))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    parser.add_argument("--owner-id")
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            result = rebuild(db, args.start, args.end, owner_id=args.owner_id)
        print(f"Rebuilt {result['pin_count']} pins / {result['day_count']} UTC days")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
