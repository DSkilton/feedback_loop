"""Transactional notification inbox and independent scheduled review reminders."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base
from .events import FEEDBACK_CREATED, FEEDBACK_STATUS_CHANGED
from .workflow import ACTION_REQUIRED, CLOSED, IN_PROGRESS, INFORMATION, READY_FOR_REVIEW


def now_utc():
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "mvp_notifications"
    __table_args__ = (UniqueConstraint("recipient_id", "source_key", name="uq_mvp_notification_source"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"), index=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    source_key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class NotificationPreference(Base):
    __tablename__ = "mvp_notification_preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"), primary_key=True)
    desktop_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reminders: Mapped[bool] = mapped_column(Boolean, default=True)


MESSAGES = {
    "feedback_published": "New teacher feedback is available.",
    "review_requested": "Learner work is ready for tutor review.",
    "review_completed": "Your tutor has reviewed your work.",
    "further_work": "Your tutor has requested further work.",
    "feedback_reopened": "Your tutor has reopened a feedback item.",
    "review_reminder": "A feedback item is still awaiting your review.",
}


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    desktop_enabled: bool = False
    review_reminders: bool = True


def preferences(db, user_id):
    row = db.get(NotificationPreference, user_id)
    return NotificationSettings(desktop_enabled=row.desktop_enabled, review_reminders=row.review_reminders) if row else NotificationSettings()


class FeedbackNotificationObserver:
    """Writes the notification in the same transaction, with no external network call."""

    def __init__(self, feedback_model):
        self.feedback_model = feedback_model

    def __call__(self, db, event):
        Feedback = self.feedback_model
        thread = db.get(Feedback, event.feedback_id)
        if thread is None:
            raise RuntimeError("Notification event has no corresponding feedback record.")
        recipient = None
        kind = None
        if event.event_type == FEEDBACK_CREATED:
            recipient, kind = thread.learner_id, "feedback_published"
        elif event.event_type == FEEDBACK_STATUS_CHANGED:
            if event.actor_id == thread.learner_id and event.status == READY_FOR_REVIEW:
                recipient, kind = thread.tutor_id, "review_requested"
            elif event.actor_id == thread.tutor_id:
                if event.status == CLOSED:
                    recipient, kind = thread.learner_id, "review_completed"
                elif event.previous_status == READY_FOR_REVIEW and event.status == IN_PROGRESS:
                    recipient, kind = thread.learner_id, "further_work"
                elif event.previous_status == CLOSED and event.status in (ACTION_REQUIRED, INFORMATION):
                    recipient, kind = thread.learner_id, "feedback_reopened"
        if recipient and kind:
            version = db.scalar(select(Feedback.version).where(Feedback.id == event.feedback_id))
            db.add(Notification(recipient_id=recipient, feedback_id=event.feedback_id,
                                kind=kind, source_key=f"feedback:{event.feedback_id}:{version}:{kind}"))


def visible_notification_ids(person, Feedback, Enrollment):
    if person.role not in ("learner", "tutor"):
        return select(Notification.id).where(Notification.id < 0)
    owner = Feedback.learner_id if person.role == "learner" else Feedback.tutor_id
    return select(Notification.id).join(Feedback, Feedback.id == Notification.feedback_id).where(
        Notification.recipient_id == person.id, owner == person.id,
        Feedback.cohort_id.in_(select(Enrollment.cohort_id).where(
            Enrollment.user_id == person.id, Enrollment.member_role == person.role)))


def register_notification_routes(app, database, actor, Feedback, Enrollment):
    @app.get("/api/notifications")
    def inbox(person=Depends(actor), db: Session = Depends(database)):
        visible = visible_notification_ids(person, Feedback, Enrollment)
        rows = db.scalars(select(Notification).where(Notification.id.in_(visible))
                          .order_by(Notification.id.desc()).limit(100)).all()
        unread = db.scalar(select(func.count()).select_from(Notification).where(
            Notification.id.in_(visible), Notification.read_at.is_(None))) or 0
        return {
            "unread_count": unread,
            "preferences": preferences(db, person.id).model_dump(),
            "items": [{"id": n.id, "feedback_id": n.feedback_id, "kind": n.kind,
                       "message": MESSAGES[n.kind], "created_at": n.created_at.isoformat(),
                       "read": n.read_at is not None} for n in rows],
        }

    @app.put("/api/notifications/preferences")
    def update_preferences(payload: NotificationSettings, person=Depends(actor), db: Session = Depends(database)):
        row = db.get(NotificationPreference, person.id)
        if row is None:
            row = NotificationPreference(user_id=person.id)
            db.add(row)
        row.desktop_enabled = payload.desktop_enabled
        row.review_reminders = payload.review_reminders
        db.commit()
        return payload.model_dump()

    @app.post("/api/notifications/read-all")
    def mark_all_read(person=Depends(actor), db: Session = Depends(database)):
        visible = visible_notification_ids(person, Feedback, Enrollment)
        db.execute(update(Notification).where(Notification.id.in_(visible), Notification.read_at.is_(None))
                   .values(read_at=now_utc()))
        db.commit()
        return {"success": True}

    @app.post("/api/notifications/{notification_id}/read")
    def mark_read(notification_id: int, person=Depends(actor), db: Session = Depends(database)):
        visible = visible_notification_ids(person, Feedback, Enrollment)
        row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.id.in_(visible)))
        if row is None:
            raise HTTPException(404, "Notification not found.")
        if row.read_at is None:
            row.read_at = now_utc()
        db.commit()
        return {"success": True}


def due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent, *, now, after_hours=24):
    """One reminder per recipient/feedback revision/UTC day; safe to retry the scheduled command."""
    if after_hours < 1:
        raise ValueError("Reminder age must be at least one hour.")
    cutoff = now - timedelta(hours=after_hours)
    requested_at = select(func.max(StructuredFeedbackEvent.created_at)).where(
        StructuredFeedbackEvent.feedback_id == Feedback.id,
        StructuredFeedbackEvent.status == READY_FOR_REVIEW
    ).correlate(Feedback).scalar_subquery()
    rows = db.scalars(select(Feedback).where(
        Feedback.status == READY_FOR_REVIEW,
        func.coalesce(requested_at, Feedback.updated_at) <= cutoff,
        select(Enrollment.id).where(Enrollment.user_id == Feedback.tutor_id,
                                    Enrollment.cohort_id == Feedback.cohort_id,
                                    Enrollment.member_role == "tutor").exists()
    )).all()
    created = 0
    for thread in rows:
        if not preferences(db, thread.tutor_id).review_reminders:
            continue
        key = f"reminder:{thread.id}:{thread.version}:{now.date().isoformat()}"
        exists = db.scalar(select(Notification.id).where(
            Notification.recipient_id == thread.tutor_id, Notification.source_key == key))
        if exists:
            continue
        try:
            with db.begin_nested():
                db.add(Notification(recipient_id=thread.tutor_id, feedback_id=thread.id,
                                    source_key=key, kind="review_reminder", created_at=now))
                db.flush()
            created += 1
        except IntegrityError:
            # Another worker may have already inserted this same unique reminder.
            if not db.scalar(select(Notification.id).where(
                    Notification.recipient_id == thread.tutor_id, Notification.source_key == key)):
                raise
    return created
