"""Read-only inspection of one persisted serving request; never manufacture view events."""

import argparse
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.logging.models import Engagement, FeedRequest, Impression, ServedFeature, ServedItem


def inspect_request(db: Session, request_id: str) -> dict | None:
    request = db.get(FeedRequest, request_id)
    if request is None:
        return None
    items = list(
        db.scalars(
            select(ServedItem)
            .where(ServedItem.request_id == request_id)
            .order_by(ServedItem.position)
        )
    )
    views = list(db.scalars(select(Impression).where(Impression.request_id == request_id)))
    actions = list(db.scalars(select(Engagement).where(Engagement.request_id == request_id)))
    features = {
        row.pin_id: row
        for row in db.scalars(select(ServedFeature).where(ServedFeature.request_id == request_id))
    }
    return {
        "request_id": request_id,
        "model_versions": request.model_versions,
        "config_version": request.config_version,
        "experiment_arms": request.experiment_arms,
        "served_at": request.served_at.isoformat(),
        "received_at": request.received_at.isoformat(),
        "served_count": len(items),
        "viewed_count": len(views),
        "unviewed_count": len(items) - len(views),
        "engagement_count": len(actions),
        "pending_engagement_count": sum(row.attribution_status == "pending" for row in actions),
        "items": [
            {
                "pin_id": item.pin_id,
                "position": item.position,
                "candidate_sources": item.candidate_sources,
                "rank_score": item.rank_score,
                "final_score": item.final_score,
                "viewed": any(view.pin_id == item.pin_id for view in views),
                "features": features[item.pin_id].features if item.pin_id in features else None,
                "feature_schema_version": (
                    features[item.pin_id].feature_schema_version
                    if item.pin_id in features
                    else None
                ),
                "feature_as_of": (
                    features[item.pin_id].feature_as_of.isoformat()
                    if item.pin_id in features
                    else None
                ),
            }
            for item in items
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", type=UUID, required=True)
    arguments = parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            result = inspect_request(db, str(arguments.request_id))
        if result is None:
            print(json.dumps({"request_id": str(arguments.request_id), "status": "not_found"}))
            return 2
        print(json.dumps(result, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
