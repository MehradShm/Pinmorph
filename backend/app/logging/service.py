from datetime import datetime

from sqlalchemy.orm import Session

from app.learning import LearningExercisePending
from app.logging.schemas import EventInput, EventResult


class InvalidAttribution(ValueError):
    """The event cannot refer to this authenticated user's served item."""


class EventConflict(ValueError):
    """An event ID was reused with different content or by a different user."""


class EventIngestor:
    def ingest(
        self, db: Session, user_id: str, event: EventInput, received_at: datetime
    ) -> EventResult:
        """Atomic ingestion, with effective event_time = server receipt for ordinary UI.

        Validate user/request/pin/position and implemented view rule against saved serving
        records. Canonicalize the validated client payload, including diagnostic client
        time, but excluding receipt time. Reserve event_id globally with authenticated
        user identity; exact retries return duplicate, conflicting reuse raises EventConflict.
        A second ID for the same view gets a receipt but no additional Impression.

        Engagements arriving before a matching view remain pending. On view arrival,
        reconcile only the same user/request/pin/position and explicit impression reference
        when supplied. Resolve duplicate-view aliases through their ledger payload. Accept
        direct closeup actions as unattributed. Reject a known mismatching reference; never
        mutate boards from telemetry. Concurrent retries must rely on DB constraints and
        rollback/re-read, not a read-before-insert assumption. No simulator time override.
        """
        # TODO(phase2-events): validation, global idempotency, inserts, reconciliation, commit.
        raise LearningExercisePending("phase2-events")
