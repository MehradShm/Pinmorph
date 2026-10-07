"""Globally idempotent event receipts, serialized per served request for reconciliation."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.logging.models import Engagement, EventReceipt, FeedRequest, Impression, ServedItem
from app.logging.schemas import EventInput, EventResult
from app.models import Pin


class InvalidAttribution(ValueError):
    pass


class EventConflict(ValueError):
    pass


class EventIngestor:
    def ingest(
        self, db: Session, user_id: str, event: EventInput, received_at: datetime
    ) -> EventResult:
        payload = event.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        event_id = str(event.event_id)
        # Event IDs are global. Request locking also serializes different IDs for the same view.
        key = int.from_bytes(hashlib.sha256(event_id.encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        old = db.get(EventReceipt, event_id)
        if old:
            if old.user_id != user_id or old.payload_hash != digest:
                raise EventConflict()
            db.commit()
            return EventResult(event_id=event.event_id, outcome="duplicate")
        request_id = str(event.request_id) if event.request_id else None
        pin_id = str(event.pin_id)
        if request_id:
            request = db.scalar(
                select(FeedRequest).where(FeedRequest.request_id == request_id).with_for_update()
            )
            item = db.get(ServedItem, (request_id, pin_id))
            if (
                not request
                or request.user_id != user_id
                or not item
                or item.position != event.position
            ):
                raise InvalidAttribution()
        elif not db.get(Pin, pin_id):
            raise InvalidAttribution()
        reference = getattr(event, "impression_event_id", None)
        if reference:
            known = db.get(EventReceipt, str(reference))
            if known and not (
                known.kind == "impression"
                and known.user_id == user_id
                and known.payload.get("request_id") == request_id
                and known.payload.get("pin_id") == pin_id
                and known.payload.get("position") == event.position
            ):
                raise InvalidAttribution()
        view = (
            db.scalar(
                select(Impression).where(
                    Impression.request_id == request_id, Impression.pin_id == pin_id
                )
            )
            if request_id
            else None
        )
        if event.kind == "impression":
            outcome = "duplicate_view" if view else "accepted"
        else:
            outcome = "unattributed" if not request_id else "accepted" if view else "pending"
            if reference and not db.get(EventReceipt, str(reference)):
                outcome = "pending"
        db.add(
            EventReceipt(
                event_id=event_id,
                user_id=user_id,
                kind=event.kind,
                payload_hash=digest,
                payload=payload,
                outcome=outcome,
                event_time=received_at,
                received_at=received_at,
                client_event_time=event.client_event_time,
            )
        )
        db.flush()
        if event.kind == "impression":
            if view is None:
                view = Impression(
                    event_id=event_id,
                    user_id=user_id,
                    request_id=request_id,
                    pin_id=pin_id,
                    position=event.position,
                    event_time=received_at,
                    received_at=received_at,
                    view_rule_version=event.view_rule_version,
                )
                db.add(view)
                db.flush()
            pending = db.scalars(
                select(Engagement).where(
                    Engagement.request_id == request_id,
                    Engagement.pin_id == pin_id,
                    Engagement.user_id == user_id,
                    Engagement.position == event.position,
                    Engagement.attribution_status == "pending",
                )
            ).all()
            for action in pending:
                ref = action.referenced_impression_event_id
                if ref is None or ref == event_id:
                    action.impression_event_id = view.event_id
                    action.attribution_status = "attributed"
        else:
            attributed = outcome == "accepted"
            db.add(
                Engagement(
                    event_id=event_id,
                    user_id=user_id,
                    pin_id=pin_id,
                    request_id=request_id,
                    position=event.position,
                    referenced_impression_event_id=str(reference) if reference else None,
                    impression_event_id=view.event_id if attributed else None,
                    attribution_status="attributed" if attributed else outcome,
                    type=event.type,
                    event_time=received_at,
                    received_at=received_at,
                )
            )
        db.commit()
        return EventResult(event_id=event.event_id, outcome=outcome)
