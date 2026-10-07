"""Local operator command. Registration/API cannot grant moderator privileges."""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            user = db.scalar(select(User).where(User.email == args.email.lower()))
            if not user:
                raise SystemExit("No matching local account")
            user.is_moderator = not args.revoke
            db.commit()
            print("Local moderator role updated")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
