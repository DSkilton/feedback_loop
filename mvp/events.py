"""Small synchronous Observer implementation for durable feedback changes.

The publisher does not know which observers audit or maintain projections.
Call publish(db, event) inside the *same* database transaction as the write,
then commit once. Failed observers therefore prevent partial state updates.
No external messages, emails, or asynchronous delivery are implied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from sqlalchemy.orm import Session

FEEDBACK_CREATED = "feedback.created"
FEEDBACK_STATUS_CHANGED = "feedback.status_changed"


@dataclass(frozen=True)
class FeedbackChanged:
    event_type: str
    feedback_id: int
    actor_id: str
    previous_status: str | None
    status: str
    feedback_required: bool
    focus_tag: str
    tutor_approved: bool = False

    def __post_init__(self) -> None:
        if self.event_type not in (FEEDBACK_CREATED, FEEDBACK_STATUS_CHANGED):
            raise ValueError("Unsupported feedback event type.")
        if self.event_type == FEEDBACK_STATUS_CHANGED and not self.previous_status:
            raise ValueError("Status change events need their previous state.")
        if self.event_type == FEEDBACK_CREATED and self.previous_status is not None:
            raise ValueError("Feedback creation must not have a previous state.")


class FeedbackObserver(Protocol):
    def __call__(self, db: Session, event: FeedbackChanged) -> None: ...


class FeedbackEventPublisher:
    """Dispatches change notifications to each registered observer, in order."""

    def __init__(self, *observers: FeedbackObserver):
        self._observers: tuple[FeedbackObserver, ...] = tuple(observers)

    def publish(self, db: Session, event: FeedbackChanged) -> None:
        for observe in self._observers:
            observe(db, event)
