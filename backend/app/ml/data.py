"""Explicit adapters keep historical import replay separate from live receipts."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.feed.contracts import FeedContext
from app.logging.models import Engagement, EventReceipt, Impression
from app.ml.config import TrainingManifest
from app.ml.contracts import Interaction
from app.ml.vector_store import catalog_vectors
from app.models import ImportedInteraction, Pin


def load_interactions(db: Session, *, user_id: str | None = None, import_run_ids=None):
    purchases = select(ImportedInteraction)
    reference = aliased(EventReceipt)
    engagements = (
        select(Engagement, Impression.received_at, reference.received_at)
        .outerjoin(Impression, Impression.event_id == Engagement.impression_event_id)
        .outerjoin(reference, reference.event_id == Engagement.referenced_impression_event_id)
        .where(Engagement.attribution_status != "pending")
    )
    if user_id is not None:
        purchases = purchases.where(ImportedInteraction.user_id == user_id)
        engagements = engagements.where(Engagement.user_id == user_id)
    if import_run_ids is not None:
        purchases = purchases.where(ImportedInteraction.import_run_id.in_(import_run_ids))
    result = [
        Interaction(
            event_id="import:" + e.id,
            user_id=e.user_id,
            pin_id=e.pin_id,
            occurred_at=e.event_time,
            known_at=e.received_at,
            received_at=e.received_at,
            provenance="imported_purchase_proxy",
            import_run_id=e.import_run_id,
        )
        for e in db.scalars(purchases)
    ]
    result.extend(
        Interaction(
            event_id=e.event_id,
            user_id=e.user_id,
            pin_id=e.pin_id,
            occurred_at=e.event_time,
            known_at=max(time for time in (e.received_at, view_receipt, reference_receipt) if time),
            received_at=e.received_at,
            provenance="simulator" if e.sim_run_id else "observed_app",
            action=e.type,
        )
        for e, view_receipt, reference_receipt in db.execute(engagements)
    )
    return result


def adapt_interactions(interactions, manifest: TrainingManifest):
    result = []
    known_through = manifest.label_known_through or manifest.cutoffs.test_end_exclusive
    for event in interactions:
        if event.provenance not in manifest.source_weights:
            continue
        raw_receipt = event.received_at or event.known_at
        if max(raw_receipt, event.known_at) > known_through:
            continue  # Dataset extraction cutoff, independent of feature history cutoff.
        if event.provenance == "imported_purchase_proxy":
            if event.import_run_id not in manifest.import_run_ids:
                raise ValueError("Imported event does not belong to the declared exact import runs")
        if manifest.availability_policy == "historical_import_replay":
            if event.provenance != "imported_purchase_proxy":
                raise ValueError("Only imported purchases can be historically replayed")
            event = event.model_copy(
                update={
                    "known_at": event.occurred_at,
                    "received_at": raw_receipt,
                }
            )
        result.append(event)
    return sorted(result, key=lambda e: (e.occurred_at, e.event_id))


@dataclass(frozen=True)
class OnlineInputs:
    catalog: list
    interactions: list
    features: object


def online_inputs(db: Session, context: FeedContext, personalization):
    from app.ml.features import PointInTimeFeatures

    catalog = catalog_vectors(db, personalization.embedding.version, context)
    events = load_interactions(db)
    features = PointInTimeFeatures(catalog, events, personalization.user_embedding)
    return OnlineInputs(catalog, events, features)


def import_catalog(db, manifest, context):
    """Fixed content is an explicit offline policy; live availability is never rewritten."""
    catalog = catalog_vectors(db, manifest.embedding_version, context)
    pins = {
        p.id: p
        for p in db.scalars(
            select(Pin).where(
                Pin.import_run_id.in_(manifest.import_run_ids),
                Pin.status == "ready",
            )
        )
    }
    catalog = [item for item in catalog if item.pin_id in pins]
    if manifest.content_policy == "fixed_import_content":
        catalog = [
            item.model_copy(
                update={
                    "available_at": pins[item.pin_id].available_at,
                    "known_at": pins[item.pin_id].available_at,
                }
            )
            for item in catalog
        ]
    return catalog
