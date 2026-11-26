"""Feedback Loop MVP API.

This is a LOCAL DEMONSTRATION ONLY. Identity is simulated using X-Demo-User.
Never expose this mode on a network or use real College learner data.
Production requires verified Microsoft Entra ID tokens, role mapping and a DPIA.
"""
from __future__ import annotations

import os
import hashlib
import json
from uuid import UUID
from urllib.parse import urlparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, create_engine, select, update
from sqlalchemy.exc import IntegrityError
from .entra import EntraConfig, configure_entra_routes, session_identity, verify_csrf
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker
from .base import Base
from .organisation import OversightScope, can_manage_organisation, register_organisation_routes
from .notifications import FeedbackNotificationObserver, register_notification_routes
from .events import (FEEDBACK_CREATED, FEEDBACK_STATUS_CHANGED, FeedbackChanged, FeedbackEventPublisher)
from .reporting import AggregateReportReadModel, ReportProjectionObserver
from .reconciliation import ReportReconciliationService
from .local_migrations import upgrade_local_feedback_schema
from .workflow import (ACTION_REQUIRED, IN_PROGRESS, READY_FOR_REVIEW, CLOSED, INFORMATION,
                       FeedbackStateMachine, TransitionRejected)

WEB = Path(__file__).parent / "web"
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
EVIDENCE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain"}
FeedbackJudgement = Literal["requires_improvement", "satisfactory", "good", "very_good", "excellent"]
JUDGEMENT_LABELS = {
    "requires_improvement": "Requires improvement",
    "satisfactory": "Satisfactory",
    "good": "Good",
    "very_good": "Very good",
    "excellent": "Excellent",
}

def validated_work_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    domain = (parsed.hostname or "").lower()
    domains = ("teams.microsoft.com", "teams.cloud.microsoft", "microsoft365.com")
    if parsed.scheme != "https" or parsed.username or parsed.password or not (
        domain in domains or domain.endswith(".sharepoint.com")
    ):
        raise ValueError("Use an HTTPS Teams or SharePoint work link.")
    return value



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


class User(Base):
    __tablename__ = "mvp_users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))


class Assignment(Base):
    __tablename__ = "mvp_assignments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))

    module: Mapped[str] = mapped_column(String(100))


class Course(Base):
    __tablename__ = "mvp_courses"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))


class Cohort(Base):
    __tablename__ = "mvp_cohorts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("mvp_courses.id"))
    name: Mapped[str] = mapped_column(String(120))
    academic_year: Mapped[str] = mapped_column(String(20))


class Enrollment(Base):
    __tablename__ = "mvp_enrolments"
    __table_args__ = (UniqueConstraint("cohort_id", "user_id", name="uq_mvp_enrolment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("mvp_cohorts.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    member_role: Mapped[str] = mapped_column(String(20))


class CohortAssignment(Base):
    __tablename__ = "mvp_cohort_assignments"
    __table_args__ = (UniqueConstraint("cohort_id", "assignment_id", name="uq_mvp_cohort_assignment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("mvp_cohorts.id"))
    assignment_id: Mapped[str] = mapped_column(ForeignKey("mvp_assignments.id"))


class Criterion(Base):
    __tablename__ = "mvp_criteria"
    __table_args__ = (UniqueConstraint("assignment_id", "code", name="uq_mvp_assignment_criterion"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("mvp_assignments.id"))
    code: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ImprovementTarget(Base):
    __tablename__ = "mvp_improvement_targets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("mvp_cohorts.id"))
    learner_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    title: Mapped[str] = mapped_column(String(140))
    guidance: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TargetLink(Base):
    __tablename__ = "mvp_target_links"
    __table_args__ = (UniqueConstraint("target_id", "feedback_id", name="uq_mvp_target_feedback"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("mvp_improvement_targets.id"))
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))


class TargetReview(Base):
    __tablename__ = "mvp_target_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("mvp_improvement_targets.id"))
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Feedback(Base):
    __tablename__ = "mvp_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("mvp_assignments.id"))
    cohort_id: Mapped[str | None] = mapped_column(ForeignKey("mvp_cohorts.id"), nullable=True)
    criterion_id: Mapped[int | None] = mapped_column(ForeignKey("mvp_criteria.id"), nullable=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    criterion: Mapped[str] = mapped_column(String(160), default="")
    feedback_text: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(Text, default="")
    focus_tag: Mapped[str] = mapped_column(String(50), default="")
    teams_reference: Mapped[str] = mapped_column(String(200))
    feedback_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default=ACTION_REQUIRED)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    judgement: Mapped[str | None] = mapped_column(String(30), nullable=True)
    work_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FeedbackReview(Base):
    __tablename__ = "mvp_feedback_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    judgement: Mapped[str] = mapped_column(String(30))
    decision_note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FeedbackSubmission(Base):
    __tablename__ = "mvp_feedback_submissions"
    __table_args__ = (UniqueConstraint("tutor_id", "client_key", name="uq_mvp_feedback_client_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    client_key: Mapped[str] = mapped_column(String(36))
    payload_digest: Mapped[str] = mapped_column(String(64))
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Note(Base):
    __tablename__ = "mvp_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "mvp_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    description: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)



class StructuredFeedbackEvent(Base):
    """Append-only structured workflow log, written with the feedback transaction."""
    __tablename__ = "mvp_domain_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    feedback_required: Mapped[bool] = mapped_column(Boolean)
    focus_tag: Mapped[str] = mapped_column(String(50))
    tutor_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def audit_feedback_change(db: Session, change: FeedbackChanged) -> None:
    """Observer 1: durable, structured record and existing human-readable timeline."""
    db.add(StructuredFeedbackEvent(
        feedback_id=change.feedback_id, actor_id=change.actor_id,
        event_type=change.event_type, previous_status=change.previous_status,
        status=change.status, feedback_required=change.feedback_required,
        focus_tag=change.focus_tag, tutor_approved=change.tutor_approved,
    ))
    if change.event_type == FEEDBACK_CREATED:
        message = "Tutor shared feedback (Teams handoff confirmed)"
    elif change.tutor_approved:
        message = f"Tutor approved and CLOSED feedback loop from {change.previous_status}"
    else:
        message = f"Moved from {change.previous_status} to {change.status}"
    db.add(Event(feedback_id=change.feedback_id, actor_id=change.actor_id, description=message))


class TeamsHandoff(Base):
    """Manually attested initial feedback in Teams, never an automatic Graph sync."""
    __tablename__ = "mvp_teams_handoffs"
    __table_args__ = (
        UniqueConstraint("learner_id", "teams_class_id", "teams_assignment_id", "teams_submission_id",
                         name="uq_mvp_teams_submission_learner"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"), unique=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    teams_reference: Mapped[str] = mapped_column(String(200))
    teams_class_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    teams_assignment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    teams_submission_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    """Small private demonstration attachments stored inside the local demo DB."""
    __tablename__ = "mvp_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("mvp_feedback.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    filename: Mapped[str] = mapped_column(String(180))
    media_type: Mapped[str] = mapped_column(String(50))
    digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    caption: Mapped[str] = mapped_column(String(250), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def check_evidence(name: str, content: bytes) -> tuple[str, str]:
    """Verify extension and minimally recognisable content, not claimed MIME type."""
    filename = name.replace(chr(92), "/").split("/")[-1].strip()
    suffix = Path(filename).suffix.lower()
    media_type = EVIDENCE_TYPES.get(suffix)
    if not filename or len(filename) > 180 or not media_type:
        raise HTTPException(422, "Use a PDF, PNG, JPEG or plain UTF-8 text file.")
    if not content or len(content) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, "Evidence must be between 1 byte and 2 MiB.")
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(422, "File does not look like a PDF.")
    if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(422, "File does not look like a PNG.")
    if suffix in (".jpg", ".jpeg") and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(422, "File does not look like a JPEG.")
    if suffix == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "Text files must use UTF-8.") from exc
        if b"\x00" in content:
            raise HTTPException(422, "Binary files are not accepted as text.")
    return filename, media_type


class NewFeedback(BaseModel):
    assignment_id: str
    learner_id: str
    cohort_id: str | None = None
    criterion_id: int | None = Field(default=None, gt=0)
    target_id: int | None = Field(default=None, gt=0)
    criterion: str = Field(default="", max_length=160)
    feedback_text: str = Field(min_length=1, max_length=4000)
    next_step: str = Field(default="", max_length=2000)
    focus_tag: str = Field(default="", max_length=50)
    teams_reference: str = Field(min_length=3, max_length=200)
    teams_recorded_confirmed: bool = False
    teams_class_id: str = Field(default="", max_length=100)
    teams_assignment_id: str = Field(default="", max_length=100)
    teams_submission_id: str = Field(default="", max_length=100)
    feedback_required: bool = True
    judgement: FeedbackJudgement | None = None
    work_url: str = Field(default="", max_length=500)
    client_key: UUID | None = None

    @field_validator("work_url")
    @classmethod
    def check_work_url(cls, value: str) -> str:
        return validated_work_url(value.strip())


class BulkFeedbackItem(NewFeedback):
    client_key: UUID


class BulkFeedbackRequest(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=60)


class NewCriterion(BaseModel):
    cohort_id: str
    code: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=300)


class NewTarget(BaseModel):
    cohort_id: str
    learner_id: str
    title: str = Field(min_length=4, max_length=140)
    guidance: str = Field(default="", max_length=1000)


class TargetLinkRequest(BaseModel):
    feedback_id: int = Field(gt=0)


class TargetDecision(BaseModel):
    status: Literal["OPEN", "ACHIEVED"]
    reason: str = Field(min_length=15, max_length=1000)


class StatusChange(BaseModel):
    status: Literal["ACTION_REQUIRED", "IN_PROGRESS", "READY_FOR_REVIEW", "CLOSED", "INFORMATION"]
    expected_version: int = Field(ge=1)
    progress_note: str = Field(default="", max_length=2000)
    judgement: FeedbackJudgement | None = None
    review_note: str = Field(default="", max_length=2000)


class NewComment(BaseModel):
    body: str = Field(min_length=1, max_length=2000)



def cohort_ids(db: Session, user: User) -> set[str]:
    if user.role not in ("learner", "tutor"):
        return set()
    return set(db.scalars(select(Enrollment.cohort_id).where(
        Enrollment.user_id == user.id, Enrollment.member_role == user.role)).all())


def eligible_cohorts(db: Session, assignment_id: str, tutor_id: str, learner_id: str) -> set[str]:
    mapped = set(db.scalars(select(CohortAssignment.cohort_id).where(
        CohortAssignment.assignment_id == assignment_id)).all())
    staff = set(db.scalars(select(Enrollment.cohort_id).where(
        Enrollment.user_id == tutor_id, Enrollment.member_role == "tutor")).all())
    students = set(db.scalars(select(Enrollment.cohort_id).where(
        Enrollment.user_id == learner_id, Enrollment.member_role == "learner")).all())
    return mapped & staff & students


def is_authorised_assignment(db: Session, assignment_id: str, actor: User, cohort_id: str) -> bool:
    return (
        cohort_id in cohort_ids(db, actor)
        and db.scalar(select(CohortAssignment.id).where(
            CohortAssignment.cohort_id == cohort_id,
            CohortAssignment.assignment_id == assignment_id)) is not None
    )


class ReportCheckCommand(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReportRepairCommand(ReportCheckCommand):
    confirmation: Literal["REBUILD_REPORT_COUNTERS"]


def seed_demo(db: Session) -> None:
    if db.get(User, "tutor-1"):
        return
    db.add_all([
        User(id="tutor-1", name="Jo Morgan", role="tutor"),
        User(id="learner-1", name="Alex Taylor", role="learner"),
        User(id="learner-2", name="Morgan Ellis", role="learner"),
        User(id="admin-1", name="Quality Team", role="admin"),
        User(id="tutor-2", name="Sam Patel", role="tutor"),
        User(id="learner-3", name="Jamie Reed", role="learner"),
        Course(id="computing", title="Computing"),
        Cohort(id="computing-26", course_id="computing", name="Computing Pilot A", academic_year="2026/27"),
        Cohort(id="web-26", course_id="computing", name="Computing Pilot B", academic_year="2026/27"),
        Assignment(id="java", title="Java Library System", module="Programming"),
        Assignment(id="database", title="Database Design", module="Databases"),
        Assignment(id="web", title="Accessible Portfolio", module="Web Development"),
    ])
    db.flush()
    db.add_all([
        Enrollment(cohort_id="computing-26", user_id="tutor-1", member_role="tutor"),
        Enrollment(cohort_id="computing-26", user_id="learner-1", member_role="learner"),
        Enrollment(cohort_id="computing-26", user_id="learner-2", member_role="learner"),
        Enrollment(cohort_id="web-26", user_id="tutor-2", member_role="tutor"),
        Enrollment(cohort_id="web-26", user_id="learner-3", member_role="learner"),
        *(CohortAssignment(cohort_id="computing-26", assignment_id=a)
          for a in ("java", "database", "web")),
        CohortAssignment(cohort_id="web-26", assignment_id="web"),
        Criterion(assignment_id="java", code="LO2", description="Use abstraction and encapsulation"),
        Criterion(assignment_id="java", code="LO3", description="Implement automated tests"),
        Criterion(assignment_id="database", code="LO1", description="Design and normalise a relational model"),
        Criterion(assignment_id="web", code="LO3", description="Apply accessible interface principles"),
    ])
    db.flush()
    samples = [
        ("java", "learner-1", "LO2 · Encapsulation", "Your Book class has clear responsibilities. Check how setters protect its fields.", "Update the setters to validate values and add tests.", "Java", ACTION_REQUIRED, True),
        ("database", "learner-1", "LO1 · Normalisation", "The entities are appropriate. The enrolment relationship needs reviewing.", "Show how the junction table resolves the many-to-many relationship.", "Data modelling", IN_PROGRESS, True),
        ("web", "learner-1", "LO3 · Accessibility", "The layout is readable. Keyboard focus needs to be more visible.", "Improve keyboard focus and test every interactive element.", "Accessibility", READY_FOR_REVIEW, True),
        ("java", "learner-2", "LO2 · Testing", "Good use of methods. Assertions need to cover invalid inputs.", "Add two negative test cases and explain the expected results.", "Testing", ACTION_REQUIRED, True),
        ("database", "learner-2", "LO1 · Normalisation", "Your functional dependencies are clear. Continue checking for transitive dependencies.", "Review the tables for third normal form.", "Data modelling", CLOSED, True),
        ("web", "learner-2", "LO1 · Structure", "You have made a confident start and organised the pages well.", "", "", INFORMATION, False),
    ]
    seeded_threads = {}
    for a, learner, criterion, words, step, tag, status, required in samples:
        thread = Feedback(
            assignment_id=a, cohort_id="computing-26", learner_id=learner, tutor_id="tutor-1", criterion=criterion,
            feedback_text=words, next_step=step, focus_tag=tag,
            teams_reference="Teams demo assignment " + a,
            status=status, feedback_required=required,
            closed_at=utcnow() if status == CLOSED else None,
        )
        db.add(thread)
        db.flush()
        seeded_threads[(learner, a)] = thread.id
        db.add(TeamsHandoff(
            feedback_id=thread.id, learner_id=learner,
            teams_reference="Teams demo assignment " + a, confirmed_by="tutor-1",
        ))
    sample_target = ImprovementTarget(
        cohort_id="computing-26", learner_id="learner-1", tutor_id="tutor-1",
        title="Explain and test design decisions",
        guidance="When responding to feedback, explain why your change works and demonstrate how you checked it.",
    )
    db.add(sample_target)
    db.flush()
    db.add_all([
        TargetLink(target_id=sample_target.id, feedback_id=seeded_threads[("learner-1", "java")]),
        TargetLink(target_id=sample_target.id, feedback_id=seeded_threads[("learner-1", "web")]),
    ])
    db.commit()


def create_app(db_url: str | None = None, demo_mode: bool | None = None, seed: bool = True,
               auth_mode: str | None = None) -> FastAPI:
    """Construct the local MVP. The default demo mode is OFF (fail closed)."""
    is_demo = (os.getenv("FEEDBACK_LOOP_DEMO_MODE") == "1") if demo_mode is None else demo_mode
    mode = "demo" if is_demo else (auth_mode or os.getenv("FEEDBACK_LOOP_AUTH_MODE", "disabled"))
    if mode not in ("demo", "entra", "disabled"):
        raise ValueError("Unrecognised authentication mode")
    if is_demo and auth_mode == "entra":
        raise ValueError("Demo identity switching and Microsoft authentication cannot be combined.")
    entra_config = EntraConfig.from_env() if mode == "entra" else None
    url = db_url or os.getenv("FEEDBACK_LOOP_DB_URL", "sqlite:///./feedback_loop_mvp.db")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    sessions = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    if is_demo and engine.dialect.name == "sqlite":
        upgrade_local_feedback_schema(engine)
    read_model = AggregateReportReadModel()
    with sessions() as db:
        if is_demo and seed:
            seed_demo(db)
        # One-time backfill for existing demo databases, not a per-request scan.
        read_model.ensure_initialized(db, Feedback)
        db.commit()

    machine = FeedbackStateMachine()
    reconciler = ReportReconciliationService(read_model)
    publisher = FeedbackEventPublisher(audit_feedback_change, ReportProjectionObserver(), FeedbackNotificationObserver(Feedback))
    app = FastAPI(title="Feedback Loop — Local MVP", version="0.1.0")
    app.mount("/assets", StaticFiles(directory=WEB), name="assets")
    if entra_config:
        configure_entra_routes(app, entra_config)

    @app.get("/api/auth-mode")
    def auth_mode_status():
        return {"mode": mode}


    def database():
        with sessions() as db:
            yield db

    def actor(request: Request, x_demo_user: str | None = Header(default=None),
              db: Session = Depends(database)) -> User:
        if is_demo:
            if not x_demo_user:
                raise HTTPException(401, "Choose a synthetic demo identity.")
            person = db.get(User, x_demo_user)
            if person is None:
                raise HTTPException(401, "Unknown demo identity.")
            return person
        if entra_config:
            identity = session_identity(request, entra_config)
            if not identity:
                raise HTTPException(401, "Microsoft sign-in required.")
            person = db.get(User, identity["user_id"])
            if person is None or person.role != identity["role"]:
                raise HTTPException(403, "Account has no verified College pilot enrolment.")
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                verify_csrf(request)
            return person
        raise HTTPException(403, "Authentication is disabled until College configuration is approved.")

    oversight_scope = OversightScope()
    register_organisation_routes(app, database, actor, User, Course, is_demo)
    register_notification_routes(app, database, actor, Feedback, Enrollment)

    def accessible(db: Session, person: User, feedback_id: int) -> Feedback:
        thread = db.get(Feedback, feedback_id)
        if thread is None:
            raise HTTPException(404, "Feedback not found.")
        if person.role == "learner" and thread.learner_id != person.id:
            raise HTTPException(404, "Feedback not found.")
        if person.role == "tutor" and thread.tutor_id != person.id:
            raise HTTPException(404, "Feedback not found.")
        if person.role == "admin":
            raise HTTPException(403, "Admin reports are aggregate only.")
        if person.role not in ("learner", "tutor"):
            raise HTTPException(403, "Feedback access is not permitted for this role.")
        if thread.cohort_id not in cohort_ids(db, person):
            raise HTTPException(404, "Feedback not found.")
        return thread

    def summarise(db: Session, thread: Feedback) -> dict:
        assignment = db.get(Assignment, thread.assignment_id)
        learner = db.get(User, thread.learner_id)
        return {
            "id": thread.id, "assignment": assignment.title, "module": assignment.module,
            "learner": learner.name, "learner_id": thread.learner_id,
            "criterion": thread.criterion, "criterion_id": thread.criterion_id,
            "cohort_id": thread.cohort_id,
            "cohort_name": db.get(Cohort, thread.cohort_id).name if thread.cohort_id else None,
            "feedback_text": thread.feedback_text,
            "next_step": thread.next_step, "focus_tag": thread.focus_tag,
            "judgement": thread.judgement, "work_url": thread.work_url, "version": thread.version,
            "teams_reference": thread.teams_reference, "feedback_required": thread.feedback_required,
            "status": thread.status, "updated_at": stamp(thread.updated_at), "closed_at": stamp(thread.closed_at),
        }

    def timeline(db: Session, fid: int) -> list[dict]:
        notes = db.scalars(select(Note).where(Note.feedback_id == fid)).all()
        events = db.scalars(select(Event).where(Event.feedback_id == fid)).all()
        items = [
            {"type": "comment", "actor": db.get(User, n.author_id).name,
             "text": n.body, "at": stamp(n.created_at)} for n in notes
        ]
        items.extend(
            {"type": "event", "actor": db.get(User, e.actor_id).name,
             "text": e.description, "at": stamp(e.created_at)} for e in events
        )
        return sorted(items, key=lambda x: x["at"] or "")

    @app.get("/")
    def home():
        return FileResponse(WEB / "index.html")

    @app.get("/api/bootstrap")
    def bootstrap(request: Request, person: User = Depends(actor), db: Session = Depends(database)):
        return {
            "auth_mode": mode, "csrf_token": request.session.get("csrf") if entra_config else None,
            "user": {"id": person.id, "name": person.name, "role": person.role},
            "can_view_oversight": oversight_scope.enabled(db, person),
            "can_manage_organisation": can_manage_organisation(person, is_demo),
            "cohorts": [
                {"id": c.id, "name": c.name, "academic_year": c.academic_year,
                 "course": db.get(Course, c.course_id).title}
                for c in db.scalars(select(Cohort).where(Cohort.id.in_(cohort_ids(db, person)))).all()
            ] if person.role != "admin" else [],
            "assignments": [
                {"id": a.id, "title": a.title, "module": a.module, "cohort_id": m.cohort_id}
                for m in db.scalars(select(CohortAssignment).where(
                    CohortAssignment.cohort_id.in_(cohort_ids(db, person)))).all()
                if (a := db.get(Assignment, m.assignment_id)) is not None
            ] if person.role == "tutor" else [],
            "learners": [
                {"id": u.id, "name": u.name, "cohort_id": e.cohort_id}
                for e in db.scalars(select(Enrollment).where(
                    Enrollment.cohort_id.in_(cohort_ids(db, person)),
                    Enrollment.member_role == "learner")).all()
                if (u := db.get(User, e.user_id)) is not None
            ] if person.role == "tutor" else [],
            "criteria": [
                {"id": c.id, "assignment_id": c.assignment_id, "code": c.code,
                 "description": c.description}
                for c in db.scalars(select(Criterion).where(
                    Criterion.assignment_id.in_(
                        select(CohortAssignment.assignment_id).where(
                            CohortAssignment.cohort_id.in_(cohort_ids(db, person)))))).all()
            ] if person.role == "tutor" else [],
        }


    @app.get("/api/cohorts")
    def list_cohorts(person: User = Depends(actor), db: Session = Depends(database)):
        """Only approved cohort memberships are visible; never enumerate the whole College."""
        if person.role not in ("tutor", "learner"):
            raise HTTPException(403, "Cohort membership required.")
        records = db.scalars(select(Cohort).where(Cohort.id.in_(cohort_ids(db, person)))).all()
        return [{
            "id": c.id, "name": c.name,
            "course": db.get(Course, c.course_id).title,
            "academic_year": c.academic_year,
            "learners": [
                {"id": student.id, "name": student.name}
                for e in db.scalars(select(Enrollment).where(
                    Enrollment.cohort_id == c.id,
                    Enrollment.member_role == "learner")).all()
                if (student := db.get(User, e.user_id)) is not None
            ] if person.role == "tutor" else None,
        } for c in records]

    @app.get("/api/assignments/{assignment_id}/criteria")
    def list_criteria(assignment_id: str, cohort_id: str, person: User = Depends(actor),
                      db: Session = Depends(database)):
        if not is_authorised_assignment(db, assignment_id, person, cohort_id):
            raise HTTPException(404, "Assignment not found.")
        criteria = db.scalars(select(Criterion).where(
            Criterion.assignment_id == assignment_id).order_by(Criterion.sort_order, Criterion.id)).all()
        return [{"id": c.id, "code": c.code, "description": c.description} for c in criteria]

    @app.post("/api/assignments/{assignment_id}/criteria", status_code=201)
    def create_criterion(assignment_id: str, payload: NewCriterion,
                         person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "tutor" or not is_authorised_assignment(db, assignment_id, person, payload.cohort_id):
            raise HTTPException(403, "Assigned tutor required.")
        if not payload.code.strip() or not payload.description.strip():
            raise HTTPException(422, "Criterion code and description are required.")
        criterion = Criterion(assignment_id=assignment_id, code=payload.code.strip().upper(),
                              description=payload.description.strip())
        db.add(criterion)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Criterion already exists for this assignment.") from exc
        db.refresh(criterion)
        return {"id": criterion.id, "assignment_id": assignment_id,
                "code": criterion.code, "description": criterion.description}

    def get_target(db: Session, person: User, target_id: int) -> ImprovementTarget:
        target = db.get(ImprovementTarget, target_id)
        if not target or target.cohort_id not in cohort_ids(db, person):
            raise HTTPException(404, "Target not found.")
        if person.role == "learner" and target.learner_id != person.id:
            raise HTTPException(404, "Target not found.")
        if person.role == "tutor" and target.tutor_id != person.id:
            raise HTTPException(404, "Target not found.")
        if person.role not in ("tutor", "learner"):
            raise HTTPException(403, "Not authorised.")
        return target

    def target_payload(db: Session, target: ImprovementTarget) -> dict:
        links = db.scalars(select(TargetLink).where(
            TargetLink.target_id == target.id).order_by(TargetLink.id)).all()
        threads = [db.get(Feedback, l.feedback_id) for l in links]
        reviews = db.scalars(select(TargetReview).where(
            TargetReview.target_id == target.id).order_by(TargetReview.id)).all()
        return {
            "id": target.id, "title": target.title, "guidance": target.guidance,
            "status": target.status, "cohort_id": target.cohort_id,
            "learner_id": target.learner_id, "learner": db.get(User, target.learner_id).name,
            "tutor_id": target.tutor_id, "created_at": stamp(target.created_at),
            "achieved_at": stamp(target.achieved_at),
            "linked_feedback": [
                {"feedback_id": t.id, "assignment": db.get(Assignment, t.assignment_id).title,
                 "assignment_id": t.assignment_id, "status": t.status}
                for t in threads if t
            ],
            "history": [
                {"status": v.status, "reason": v.reason,
                 "at": stamp(v.created_at), "tutor": db.get(User, v.tutor_id).name}
                for v in reviews
            ],
            "can_achieve": any(t is not None and t.status == CLOSED for t in threads),
        }

    @app.get("/api/targets")
    def list_targets(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role not in ("tutor", "learner"):
            raise HTTPException(403, "Targets belong to tutors and learners.")
        condition = (ImprovementTarget.tutor_id == person.id if person.role == "tutor"
                     else ImprovementTarget.learner_id == person.id)
        results = db.scalars(select(ImprovementTarget).where(
            condition, ImprovementTarget.cohort_id.in_(cohort_ids(db, person))
        ).order_by(ImprovementTarget.created_at.desc())).all()
        return [target_payload(db, t) for t in results]

    @app.get("/api/targets/{target_id}")
    def target_detail(target_id: int, person: User = Depends(actor), db: Session = Depends(database)):
        return target_payload(db, get_target(db, person, target_id))

    @app.post("/api/targets", status_code=201)
    def create_target(payload: NewTarget, person: User = Depends(actor),
                      db: Session = Depends(database)):
        if person.role != "tutor" or payload.cohort_id not in cohort_ids(db, person):
            raise HTTPException(403, "Assigned tutor required.")
        learner = db.get(User, payload.learner_id)
        if not learner or learner.role != "learner" or payload.cohort_id not in cohort_ids(db, learner):
            raise HTTPException(403, "Learner is not enrolled in the tutor's cohort.")
        if not payload.title.strip() or not payload.guidance.strip():
            raise HTTPException(422, "Title and tutor-authored guidance are required.")
        target = ImprovementTarget(
            cohort_id=payload.cohort_id, learner_id=learner.id, tutor_id=person.id,
            title=payload.title.strip(), guidance=payload.guidance.strip(),
        )
        db.add(target)
        db.commit()
        return target_payload(db, target)

    @app.post("/api/targets/{target_id}/links", status_code=201)
    def link_target(target_id: int, payload: TargetLinkRequest,
                    person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "tutor":
            raise HTTPException(403, "Tutors link feedback to targets.")
        target = get_target(db, person, target_id)
        feedback = accessible(db, person, payload.feedback_id)
        if target.status != "OPEN" or feedback.learner_id != target.learner_id or feedback.cohort_id != target.cohort_id:
            raise HTTPException(403, "Feedback must belong to the target's learner and cohort.")
        db.add(TargetLink(target_id=target.id, feedback_id=feedback.id))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Feedback is already linked to this target.") from exc
        return target_payload(db, target)

    @app.post("/api/targets/{target_id}/status")
    def review_target(target_id: int, payload: TargetDecision,
                      person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "tutor":
            raise HTTPException(403, "Only a tutor can confirm target achievement.")
        target = get_target(db, person, target_id)
        if target.status == payload.status:
            raise HTTPException(409, "Target is already in that state.")
        if not payload.reason.strip() or len(payload.reason.strip()) < 15:
            raise HTTPException(422, "Explain the professional judgement in at least 15 characters.")
        if payload.status == "ACHIEVED":
            linked_ids = select(TargetLink.feedback_id).where(TargetLink.target_id == target.id)
            completed = db.scalar(select(Feedback.id).where(
                Feedback.id.in_(linked_ids), Feedback.status == CLOSED,
                Feedback.cohort_id == target.cohort_id, Feedback.learner_id == target.learner_id
            ).limit(1))
            if completed is None:
                raise HTTPException(409, "Close at least one linked feedback action before marking achieved.")
        target.status = payload.status
        target.achieved_at = utcnow() if payload.status == "ACHIEVED" else None
        db.add(TargetReview(target_id=target.id, tutor_id=person.id,
                            status=payload.status, reason=payload.reason.strip()))
        db.commit()
        return target_payload(db, target)

    @app.get("/api/oversight")
    def oversight(person: User = Depends(actor), db: Session = Depends(database)):
        if not oversight_scope.enabled(db, person):
            raise HTTPException(403, "Oversight is not allocated to this account.")
        ids = oversight_scope.cohort_ids(db, person, Cohort)
        cohorts = db.scalars(select(Cohort).where(Cohort.id.in_(ids)).order_by(Cohort.name)).all()
        threads = db.scalars(select(Feedback).where(Feedback.cohort_id.in_(ids))
                             .order_by(Feedback.updated_at.desc())).all()
        memberships = db.scalars(select(Enrollment).where(
            Enrollment.cohort_id.in_(ids), Enrollment.member_role == "learner")).all()
        return {
            "cohorts": [{"id": c.id, "name": c.name, "course": db.get(Course, c.course_id).title,
                         "academic_year": c.academic_year} for c in cohorts],
            "learners": [{"id": e.user_id, "cohort_id": e.cohort_id, "name": db.get(User, e.user_id).name}
                         for e in memberships],
            "feedback": [{**summarise(db, t), "tutor": db.get(User, t.tutor_id).name} for t in threads],
        }

    @app.get("/api/oversight/feedback/{fid}")
    def oversight_detail(fid: int, person: User = Depends(actor), db: Session = Depends(database)):
        if not oversight_scope.enabled(db, person):
            raise HTTPException(403, "Oversight is not allocated to this account.")
        thread = db.get(Feedback, fid)
        if not thread or thread.cohort_id not in oversight_scope.cohort_ids(db, person, Cohort):
            raise HTTPException(404, "Feedback not found.")
        reviews = db.scalars(select(FeedbackReview).where(FeedbackReview.feedback_id == fid)
                             .order_by(FeedbackReview.id)).all()
        return {
            **summarise(db, thread), "tutor": db.get(User, thread.tutor_id).name,
            "timeline": timeline(db, fid),
            "reviews": [{"judgement": r.judgement, "note": r.decision_note, "at": stamp(r.created_at)} for r in reviews],
            "read_only": True,
        }

    @app.get("/api/threads")
    def list_threads(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role == "admin":
            raise HTTPException(403, "Use aggregate reports.")
        if person.role not in ("learner", "tutor"):
            raise HTTPException(403, "Feedback access is not permitted for this role.")
        condition = Feedback.learner_id == person.id if person.role == "learner" else Feedback.tutor_id == person.id
        threads = db.scalars(select(Feedback).where(
            condition, Feedback.cohort_id.in_(cohort_ids(db, person))
        ).order_by(Feedback.updated_at.desc())).all()
        return [summarise(db, t) for t in threads]

    @app.get("/api/threads/{fid}")
    def detail(fid: int, person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        handoff = db.scalar(select(TeamsHandoff).where(TeamsHandoff.feedback_id == fid))
        evidence = db.scalars(select(Evidence).where(Evidence.feedback_id == fid).order_by(Evidence.created_at)).all()
        reviews = db.scalars(select(FeedbackReview).where(FeedbackReview.feedback_id == fid).order_by(FeedbackReview.id)).all()
        return {
            **summarise(db, thread), "timeline": timeline(db, fid),
            "reviews": [{"judgement": r.judgement, "note": r.decision_note, "at": stamp(r.created_at)} for r in reviews],
            "teams_handoff": {
                "confirmed_at": stamp(handoff.confirmed_at),
                "teams_class_id": handoff.teams_class_id,
                "teams_assignment_id": handoff.teams_assignment_id,
                "teams_submission_id": handoff.teams_submission_id,
            } if handoff else None,
            "evidence": [{"id": e.id, "filename": e.filename, "caption": e.caption,
                          "uploaded_by": db.get(User, e.author_id).name,
                          "created_at": stamp(e.created_at),
                          "sha256": e.digest} for e in evidence],
        }

    def save_feedback_item(db: Session, tutor: User, payload: NewFeedback) -> tuple[Feedback, bool]:
        if tutor.role != "tutor":
            raise HTTPException(403, "Only tutors can author feedback.")
        digest = hashlib.sha256(json.dumps(
            payload.model_dump(mode="json", exclude={"client_key"}), sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        client_key = str(payload.client_key) if payload.client_key else None
        if client_key:
            existing = db.scalar(select(FeedbackSubmission).where(
                FeedbackSubmission.tutor_id == tutor.id, FeedbackSubmission.client_key == client_key,
            ))
            if existing:
                if existing.payload_digest != digest:
                    raise HTTPException(409, "This submission key belongs to different feedback.")
                previous = db.get(Feedback, existing.feedback_id)
                if previous is None or previous.cohort_id not in cohort_ids(db, tutor):
                    raise HTTPException(403, "Feedback is no longer in an assigned teaching cohort.")
                return previous, True

        learner = db.get(User, payload.learner_id)
        if learner is None or learner.role != "learner" or db.get(Assignment, payload.assignment_id) is None:
            raise HTTPException(422, "Choose a valid learner and assignment.")
        permitted = eligible_cohorts(db, payload.assignment_id, tutor.id, learner.id)
        if not permitted:
            raise HTTPException(403, "Tutor and learner must share the assigned cohort.")
        if payload.cohort_id:
            if payload.cohort_id not in permitted:
                raise HTTPException(403, "Assignment is not shared in the selected cohort.")
            selected_cohort = payload.cohort_id
        elif len(permitted) == 1:
            selected_cohort = next(iter(permitted))
        else:
            raise HTTPException(422, "Choose the cohort for this feedback.")
        criterion = None
        if payload.criterion_id is not None:
            criterion = db.get(Criterion, payload.criterion_id)
            if criterion is None or criterion.assignment_id != payload.assignment_id:
                raise HTTPException(422, "Assessment criterion does not belong to the assignment.")
        target = None
        if payload.target_id is not None:
            target = db.get(ImprovementTarget, payload.target_id)
            if not target or target.status != "OPEN" or target.cohort_id != selected_cohort or target.learner_id != learner.id or target.tutor_id != tutor.id:
                raise HTTPException(403, "Target is not accessible for this learner and cohort.")
        if not payload.feedback_text.strip() or (payload.feedback_required and not payload.next_step.strip()):
            raise HTTPException(422, "Feedback text and, when required, an actionable next step are needed.")
        if not payload.teams_recorded_confirmed:
            raise HTTPException(422, "Confirm that initial feedback was recorded in Teams.")
        teams_ids = (payload.teams_class_id.strip(), payload.teams_assignment_id.strip(), payload.teams_submission_id.strip())
        if any(teams_ids) and not all(teams_ids):
            raise HTTPException(422, "Provide all three Teams identifiers or none.")
        if all(teams_ids):
            existing = db.scalar(select(TeamsHandoff).where(
                TeamsHandoff.learner_id == learner.id,
                TeamsHandoff.teams_class_id == teams_ids[0],
                TeamsHandoff.teams_assignment_id == teams_ids[1],
                TeamsHandoff.teams_submission_id == teams_ids[2]))
            if existing:
                raise HTTPException(409, "This Teams learner submission has an existing feedback loop.")
        thread = Feedback(
            assignment_id=payload.assignment_id, cohort_id=selected_cohort,
            criterion_id=criterion.id if criterion else None,
            learner_id=learner.id, tutor_id=tutor.id,
            criterion=f"{criterion.code} · {criterion.description}" if criterion else payload.criterion.strip(),
            feedback_text=payload.feedback_text.strip(),
            next_step=payload.next_step.strip(), focus_tag=payload.focus_tag.strip(),
            teams_reference=payload.teams_reference.strip(), feedback_required=payload.feedback_required,
            status=ACTION_REQUIRED if payload.feedback_required else INFORMATION,
            judgement=payload.judgement, work_url=payload.work_url,
        )
        db.add(thread)
        db.flush()
        db.add(TeamsHandoff(
            feedback_id=thread.id, learner_id=learner.id,
            teams_reference=payload.teams_reference.strip(),
            teams_class_id=teams_ids[0] or None,
            teams_assignment_id=teams_ids[1] or None,
            teams_submission_id=teams_ids[2] or None,
            confirmed_by=tutor.id,
        ))
        if target is not None:
            db.add(TargetLink(target_id=target.id, feedback_id=thread.id))
        if client_key:
            db.add(FeedbackSubmission(
                tutor_id=tutor.id, client_key=client_key,
                payload_digest=digest, feedback_id=thread.id,
            ))
        publisher.publish(db, FeedbackChanged(
            event_type=FEEDBACK_CREATED, feedback_id=thread.id, actor_id=tutor.id,
            previous_status=None, status=thread.status, feedback_required=thread.feedback_required,
            focus_tag=thread.focus_tag,
        ))
        return thread, False

    @app.post("/api/threads", status_code=201)
    def new_thread(payload: NewFeedback, person: User = Depends(actor), db: Session = Depends(database)):
        try:
            thread, _ = save_feedback_item(db, person, payload)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409, "Feedback submission was already saved or the Teams reference is in use.") from exc
        return summarise(db, thread)

    @app.post("/api/threads/bulk")
    def submit_bulk(payload: BulkFeedbackRequest, person: User = Depends(actor)):
        if person.role != "tutor":
            raise HTTPException(403, "Only tutors can author feedback.")
        results = []
        for raw in payload.items:
            try:
                item = BulkFeedbackItem.model_validate(raw)
            except ValidationError:
                results.append({
                    "client_key": str(raw.get("client_key", ""))[:36], "ok": False,
                    "code": 422, "error": "Feedback row has invalid or missing fields.",
                })
                continue
            with sessions() as row_db:
                try:
                    current_tutor = row_db.get(User, person.id)
                    thread, replayed = save_feedback_item(row_db, current_tutor, item)
                    row_db.commit()
                    results.append({
                        "client_key": str(item.client_key), "ok": True,
                        "replayed": replayed, "feedback_id": thread.id,
                    })
                except HTTPException as exc:
                    row_db.rollback()
                    results.append({
                        "client_key": str(item.client_key), "ok": False,
                        "code": exc.status_code, "error": str(exc.detail),
                    })
                except IntegrityError:
                    row_db.rollback()
                    results.append({
                        "client_key": str(item.client_key), "ok": False,
                        "code": 409, "error": "Duplicate feedback or submission reference; check before retrying.",
                    })
                except Exception:
                    row_db.rollback()
                    results.append({
                        "client_key": str(item.client_key), "ok": False,
                        "code": 500, "error": "Unable to save this row. It has been retained for retry.",
                    })
        return {
            "saved": sum(row["ok"] for row in results),
            "failed": sum(not row["ok"] for row in results),
            "results": results,
        }

    @app.post("/api/threads/{fid}/status")
    def change_status(fid: int, payload: StatusChange, person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        if thread.version != payload.expected_version:
            raise HTTPException(409, "Feedback has changed. Refresh the record before submitting again.")
        try:
            decision = machine.decide(
                current=thread.status, target=payload.status, actor_role=person.role,
                feedback_required=thread.feedback_required, progress_note=payload.progress_note,
            )
        except TransitionRejected as exc:
            raise HTTPException(exc.code, str(exc)) from exc
        if decision.tutor_approved and thread.feedback_required:
            if payload.judgement is None or len(payload.review_note.strip()) < 5:
                raise HTTPException(422, "Choose a judgement and write a short tutor review before closing.")
        elif payload.judgement is not None or payload.review_note.strip():
            raise HTTPException(422, "Review details are only accepted when closing actionable feedback.")

        changed_at = utcnow()
        affected = db.execute(update(Feedback).where(
            Feedback.id == fid, Feedback.version == payload.expected_version,
        ).values(
            status=decision.target, version=Feedback.version + 1, updated_at=changed_at,
            closed_at=changed_at if decision.tutor_approved else None,
        ).execution_options(synchronize_session=False)).rowcount
        if affected != 1:
            db.rollback()
            raise HTTPException(409, "Feedback has changed. Refresh the record before submitting again.")
        if decision.progress_note:
            db.add(Note(feedback_id=fid, author_id=person.id,
                        body="Work submitted for review: " + decision.progress_note))
        if decision.tutor_approved and thread.feedback_required:
            db.add(FeedbackReview(
                feedback_id=fid, tutor_id=person.id,
                judgement=payload.judgement, decision_note=payload.review_note.strip(),
            ))
            db.add(Note(
                feedback_id=fid, author_id=person.id,
                body=f"Review — {JUDGEMENT_LABELS[payload.judgement]}: {payload.review_note.strip()}",
            ))
        publisher.publish(db, FeedbackChanged(
            event_type=FEEDBACK_STATUS_CHANGED, feedback_id=fid, actor_id=person.id,
            previous_status=decision.previous, status=decision.target,
            feedback_required=thread.feedback_required, focus_tag=thread.focus_tag,
            tutor_approved=decision.tutor_approved,
        ))
        db.commit()
        db.refresh(thread)
        return summarise(db, thread)

    @app.post("/api/threads/{fid}/comments", status_code=201)
    def add_comment(fid: int, payload: NewComment, person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        if not payload.body.strip():
            raise HTTPException(422, "A comment is required.")
        db.add(Note(feedback_id=fid, author_id=person.id, body=payload.body.strip()))
        thread.updated_at = utcnow()
        db.commit()
        return {"success": True}


    @app.post("/api/threads/{fid}/evidence", status_code=201)
    async def upload_evidence(fid: int, file: UploadFile = File(...), caption: str = Form(default=""),
                              person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        if person.role != "learner" or thread.status not in (IN_PROGRESS, READY_FOR_REVIEW):
            raise HTTPException(403, "Only the learner can add evidence to active work.")
        if len(caption) > 250:
            raise HTTPException(422, "Evidence description is too long.")
        count = len(db.scalars(select(Evidence.id).where(Evidence.feedback_id == fid)).all())
        if count >= 5:
            raise HTTPException(409, "This feedback action already has five attachments.")
        content = await file.read(MAX_EVIDENCE_BYTES + 1)
        filename, media_type = check_evidence(file.filename or "", content)
        record = Evidence(feedback_id=fid, author_id=person.id, filename=filename,
                          media_type=media_type, digest=hashlib.sha256(content).hexdigest(),
                          data=content, caption=caption.strip())
        db.add(record)
        db.flush()
        db.add(Event(feedback_id=fid, actor_id=person.id,
                     description=f"Attached evidence: {filename[:150]}"))
        thread.updated_at = utcnow()
        db.commit()
        return {"id": record.id, "filename": filename, "sha256": record.digest}

    @app.get("/api/threads/{fid}/evidence/{eid}")
    def download_evidence(fid: int, eid: int, person: User = Depends(actor),
                          db: Session = Depends(database)):
        accessible(db, person, fid)
        evidence = db.get(Evidence, eid)
        if evidence is None or evidence.feedback_id != fid:
            raise HTTPException(404, "Evidence not found.")
        suffix = Path(evidence.filename).suffix.lower()
        return Response(
            content=evidence.data, media_type=evidence.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="evidence-{eid}{suffix}"',
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/tutor/focus-areas")
    def tutor_focus(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "tutor":
            raise HTTPException(403, "Tutor role required.")
        threads = db.scalars(select(Feedback).where(
            Feedback.tutor_id == person.id,
            Feedback.cohort_id.in_(cohort_ids(db, person)))).all()
        grouped = defaultdict(list)
        for t in threads:
            if t.focus_tag.strip():
                grouped[(t.cohort_id, t.learner_id, t.focus_tag.strip().casefold())].append(t)
        recurring = []
        for (group_cohort_id, learner_id, _), items in grouped.items():
            if len({t.assignment_id for t in items}) < 2:
                continue
            learner = db.get(User, learner_id)
            recurring.append({
                "learner": learner.name, "learner_id": learner_id,
                "cohort_id": group_cohort_id,
                "focus": items[0].focus_tag, "feedback_count": len(items),
                "assignment_count": len({t.assignment_id for t in items}),
                "threads": [{"feedback_id": t.id, "assignment": db.get(Assignment, t.assignment_id).title}
                            for t in items],
            })
        recurring.sort(key=lambda item: (-item["assignment_count"], item["learner"], item["focus"]))
        return {"recurring": recurring,
                "note": "Tutor-authored focus tags only; review context with the learner."}

    @app.post("/api/reports/reconcile")
    def reconcile_reports(payload: ReportCheckCommand, person: User = Depends(actor),
                          db: Session = Depends(database)):
        if person.role != "admin":
            raise HTTPException(403, "Quality administrator role required.")
        try:
            result = reconciler.run(db, Feedback, actor_id=person.id, reason=payload.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        db.commit()
        return result

    @app.post("/api/reports/reconcile/repair")
    def repair_reports(payload: ReportRepairCommand, person: User = Depends(actor),
                       db: Session = Depends(database)):
        if person.role != "admin":
            raise HTTPException(403, "Quality administrator role required.")
        allowed_ids = {id.strip() for id in os.getenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "").split(",") if id.strip()}
        if person.id not in allowed_ids:
            raise HTTPException(403, "Reporting repair permission is not configured for this account.")
        try:
            result = reconciler.run(db, Feedback, actor_id=person.id,
                                    reason=payload.reason, repair=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        db.commit()
        return result

    @app.get("/api/reports")
    def reports(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "admin":
            raise HTTPException(403, "Administrator role required.")
        return read_model.snapshot(db)

    return app


app = create_app()
