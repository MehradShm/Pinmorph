"""Daily opt-in local SMTP outbox. SMTP delivery is at least once after a crash."""

import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import User, utcnow
from app.product.models import EmailOutbox, UserSettings
from app.social.models import Notification
from app.social.policy import visible_owner


def prepare_digest(db: Session, user: User, now):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    prefs = db.get(UserSettings, user.id)
    if not prefs or not prefs.email_digest or not user.email:
        return None
    period = now.strftime("%Y-%m-%d")
    old = db.scalar(
        select(EmailOutbox).where(EmailOutbox.user_id == user.id, EmailOutbox.period == period)
    )
    if old:
        return old
    notices = db.execute(
        select(Notification, User.display_name)
        .join(User, User.id == Notification.actor_id)
        .where(
            Notification.recipient_id == user.id,
            Notification.read_at.is_(None),
            Notification.created_at > now - timedelta(days=1),
            Notification.created_at <= now,
            visible_owner(Notification.actor_id, user, include_muted=True),
        )
        .order_by(Notification.created_at)
        .limit(100)
    ).all()
    if not notices:
        return None
    body = "Your Pinmorph activity\n\n" + "\n".join(
        f"{name}: {notice.kind.replace('_', ' ')}" for notice, name in notices
    )
    row = EmailOutbox(user_id=user.id, period=period, recipient=user.email, body=body)
    db.add(row)
    db.flush()
    return row


def deliver_pending(settings: Settings | None = None):
    settings = settings or Settings()
    engine = make_engine(settings)
    delivered = 0
    try:
        with Session(engine) as db:
            rows = db.scalars(
                select(EmailOutbox)
                .where(EmailOutbox.status == "pending")
                .with_for_update(skip_locked=True)
                .limit(100)
            ).all()
            for row in rows:
                prefs = db.get(UserSettings, row.user_id)
                row.attempts += 1
                if not prefs or not prefs.email_digest:
                    row.status = "cancelled"
                    continue
                # Rebuild at dispatch so new blocks/mutes cannot leak an older prepared notice.
                user = db.get(User, row.user_id)
                now = utcnow()
                notices = db.execute(
                    select(Notification, User.display_name)
                    .join(User, User.id == Notification.actor_id)
                    .where(
                        Notification.recipient_id == user.id,
                        Notification.read_at.is_(None),
                        Notification.created_at > now - timedelta(days=1),
                        Notification.created_at <= now,
                        visible_owner(Notification.actor_id, user, include_muted=True),
                    )
                    .limit(100)
                ).all()
                if not notices:
                    row.status = "cancelled"
                    continue
                row.body = "Your Pinmorph activity\n\n" + "\n".join(
                    f"{name}: {n.kind.replace('_', ' ')}" for n, name in notices
                )
                message = EmailMessage()
                message["From"] = "Pinmorph <activity@pinmorph.test>"
                message["To"] = row.recipient
                message["Subject"] = "Your Pinmorph daily digest"
                message["Message-ID"] = f"<{row.id}@pinmorph.test>"
                message.set_content(row.body)
                try:
                    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=5) as smtp:
                        smtp.send_message(message)
                except (OSError, smtplib.SMTPException):
                    continue
                row.status = "delivered"
                row.delivered_at = utcnow()
                delivered += 1
            db.commit()
    finally:
        engine.dispose()
    return delivered


def daily_tick(settings: Settings | None = None):
    settings = settings or Settings()
    engine = make_engine(settings)
    try:
        with Session(engine) as db:
            users = db.scalars(
                select(User)
                .join(UserSettings, UserSettings.user_id == User.id)
                .where(UserSettings.email_digest.is_(True))
            ).all()
            for user in users:
                prepare_digest(db, user, utcnow())
            db.commit()
    finally:
        engine.dispose()
    return deliver_pending(settings)
