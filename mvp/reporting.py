"""Aggregate-only CQRS-style reporting projection and query service.

Writes update Feedback (source of truth) and, in the same transaction, typed
events increment reporting counters. Admin queries read just this table, not
student feedback text or private evidence. An explicit rebuild repairs or
backfills counters from the write model; this is *not* event sourcing.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, delete, func, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base
from .events import FEEDBACK_CREATED, FEEDBACK_STATUS_CHANGED, FeedbackChanged
from .workflow import STATES, CLOSED, READY_FOR_REVIEW


class ReportCounter(Base):
    __tablename__ = "mvp_report_counters"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReportProjectionState(Base):
    """Bootstrap marker; missing counters are never silently repaired on restart."""
    __tablename__ = "mvp_report_projection_state"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )


def _adjust(db: Session, key: str, change: int) -> None:
    """Use an atomic SQL update to avoid lost counter increments in parallel writes.

    This is still an MVP, not a concurrency or multi-tenant production guarantee.
    """
    db.flush()  # Materialise newly-added counters if another event runs in this transaction.
    statement = update(ReportCounter).where(ReportCounter.key == key)
    if change < 0:
        statement = statement.where(ReportCounter.value >= -change)
    result = db.execute(
        statement.values(value=ReportCounter.value + change),
        execution_options={"synchronize_session": False},
    )
    if result.rowcount == 0:
        if change < 0:
            raise RuntimeError(f"Report projection out of sync: {key}")
        db.add(ReportCounter(key=key, value=change))
        db.flush()


class ReportProjectionObserver:
    """Observer that maintains aggregate counters transactionally."""

    def __call__(self, db: Session, event: FeedbackChanged) -> None:
        if event.event_type == FEEDBACK_CREATED:
            _adjust(db, "total", 1)
            if event.feedback_required:
                _adjust(db, "actions_required", 1)
            _adjust(db, f"status:{event.status}", 1)
            if event.focus_tag:
                _adjust(db, f"focus:{event.focus_tag}", 1)
        elif event.event_type == FEEDBACK_STATUS_CHANGED:
            _adjust(db, f"status:{event.previous_status}", -1)
            _adjust(db, f"status:{event.status}", 1)


class AggregateReportReadModel:
    """Queries use the materialised counters, not the feedback write table."""

    def expected_counters(self, db: Session, feedback_model: type) -> dict[str, int]:
        """Derive authoritative aggregate counts without loading feedback content."""
        total = db.scalar(select(func.count()).select_from(feedback_model)) or 0
        actions = db.scalar(select(func.count()).select_from(feedback_model).where(
            feedback_model.feedback_required.is_(True))) or 0
        state_rows = db.execute(
            select(feedback_model.status, func.count()).group_by(feedback_model.status)).all()
        tag_rows = db.execute(
            select(feedback_model.focus_tag, func.count())
            .where(feedback_model.focus_tag.is_not(None), feedback_model.focus_tag != "")
            .group_by(feedback_model.focus_tag)).all()
        counters = {"total": total, "actions_required": actions}
        counters.update({f"status:{state}": 0 for state in STATES})
        for state, count in state_rows:
            counters[f"status:{state}"] = count
        for tag, count in tag_rows:
            counters[f"focus:{tag}"] = count
        return counters

    def rebuild(self, db: Session, feedback_model: type) -> None:
        """Explicit rebuild of the read model, to be committed by the caller."""
        values = self.expected_counters(db, feedback_model)
        db.execute(delete(ReportCounter))
        db.flush()
        db.add_all(ReportCounter(key=key, value=count) for key, count in values.items())
        db.flush()

    def ensure_initialized(self, db: Session, feedback_model: type) -> None:
        if db.get(ReportProjectionState, "aggregate-v1") is not None:
            return
        # Backfill a genuinely new projection once. Once marked initialized,
        # missing counters indicate drift and require an audited repair.
        if (db.scalar(select(func.count()).select_from(ReportCounter)) or 0) == 0:
            self.rebuild(db, feedback_model)
        db.add(ReportProjectionState(name="aggregate-v1"))
        db.flush()

    def snapshot(self, db: Session) -> dict:
        counters = {c.key: c.value for c in db.scalars(select(ReportCounter)).all()}
        focus = Counter({
            key[len("focus:"):]: count for key, count in counters.items()
            if key.startswith("focus:") and count > 0
        })
        return {
            "total": counters.get("total", 0),
            "actions_required": counters.get("actions_required", 0),
            "closed": counters.get(f"status:{CLOSED}", 0),
            "awaiting_review": counters.get(f"status:{READY_FOR_REVIEW}", 0),
            "by_status": [
                {"status": state, "count": counters.get(f"status:{state}", 0)}
                for state in STATES
            ],
            "focus_areas": [
                {"name": name, "count": count} for name, count in
                sorted(focus.items(), key=lambda item: (-item[1], item[0].casefold()))
            ],
            "note": "Counts reflect recorded feedback and teacher-entered focus areas.",
        }
