"""Explicit, audited reconciliation of aggregate reporting read models.

The normal reporting query never uses this module. Reconciliation reads only
aggregate source columns; it does not inspect feedback text or attachments.
Checks and repairs are transactions with append-only maintenance audit rows.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base
from .reporting import AggregateReportReadModel, ReportCounter


class ReportMaintenanceAudit(Base):
    __tablename__ = "mvp_report_maintenance_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    was_consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _digest(counters: dict[str, int]) -> str:
    data = json.dumps(counters, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class ReportReconciliationService:
    """Compare derived counters to the authoritative feedback rows on demand."""

    def __init__(self, read_model: AggregateReportReadModel | None = None):
        self._read_model = read_model or AggregateReportReadModel()

    def expected(self, db: Session, feedback_model: type) -> dict[str, int]:
        return self._read_model.expected_counters(db, feedback_model)

    def observed(self, db: Session) -> dict[str, int]:
        return dict(db.execute(select(ReportCounter.key, ReportCounter.value)).all())

    def compare(self, db: Session, feedback_model: type) -> dict:
        expected = self.expected(db, feedback_model)
        observed = self.observed(db)
        discrepancies = [
            {"metric": key, "expected": expected.get(key), "actual": observed.get(key)}
            for key in sorted(expected.keys() | observed.keys())
            if expected.get(key) != observed.get(key)
        ]
        return {
            "consistent": not discrepancies,
            "mismatch_count": len(discrepancies),
            "discrepancies": discrepancies,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def run(self, db: Session, feedback_model: type, *, actor_id: str, reason: str,
            repair: bool = False) -> dict:
        """Audit a check or repair in a single transaction, committed by caller.

        Caller must enforce authentication and authorize repair separately.
        A failure before commit rolls back both the repair and its audit row.
        """
        description = reason.strip()
        if not description or len(description) > 500:
            raise ValueError("An operational reason of 1–500 characters is required.")
        before = self.compare(db, feedback_model)
        before_counters = self.observed(db)
        if repair and not before["consistent"]:
            self._read_model.rebuild(db, feedback_model)
        after = self.compare(db, feedback_model) if repair else before
        if repair and not after["consistent"]:
            raise RuntimeError("Rebuilt report counters are not consistent.")
        after_counters = self.observed(db) if repair else before_counters
        db.add(ReportMaintenanceAudit(
            actor_id=actor_id, action="repair" if repair else "check",
            reason=description, was_consistent=before["consistent"],
            mismatch_count=before["mismatch_count"],
            before_hash=_digest(before_counters), after_hash=_digest(after_counters),
        ))
        return {
            **before,
            "action": "repair" if repair else "check",
            "repaired": repair and not before["consistent"],
            "consistent_after": after["consistent"],
        }
