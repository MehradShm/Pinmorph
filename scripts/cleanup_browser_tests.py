"""Delete only disposable browser-test accounts recorded in exact identity artifacts."""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import Pin, User
from app.storage import make_s3_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("frontend/test-results"))
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    removed = 0
    try:
        with Session(engine) as db:
            for artifact in args.artifacts.rglob("account.json"):
                identity = json.loads(artifact.read_text())
                if not re.fullmatch(r"browser-\d{13}-[a-z0-9]+@example\.test", identity["email"]):
                    raise ValueError("Artifact is not a generated browser-test identity")
                user = db.get(User, identity["id"])
                if user is None:
                    continue
                if user.email != identity["email"]:
                    raise ValueError("Artifact identity does not match the database account")
                pins = list(db.scalars(select(Pin).where(Pin.owner_id == user.id)))
                if any(pin.status in {"queued", "processing"} for pin in pins):
                    raise RuntimeError("Wait for browser-test media jobs before cleanup")
                for pin in pins:
                    objects = storage.list_objects_v2(
                        Bucket=settings.s3_bucket, Prefix=f"pins/{pin.id}/"
                    )
                    for item in objects.get("Contents", []):
                        storage.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])
                db.execute(delete(Pin).where(Pin.owner_id == user.id))
                db.delete(user)
                db.commit()
                removed += 1
        print(f"Removed {removed} recorded browser-test accounts")
    finally:
        storage.close()
        engine.dispose()


if __name__ == "__main__":
    main()
