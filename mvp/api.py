"""Feedback Loop MVP API.

This is a LOCAL DEMONSTRATION ONLY. Identity is simulated using X-Demo-User.
Never expose this mode on a network or use real College learner data.
Production requires verified Microsoft Entra ID tokens, role mapping and a DPIA.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

WEB = Path(__file__).parent / "web"
ACTION_REQUIRED = "ACTION_REQUIRED"
IN_PROGRESS = "IN_PROGRESS"
READY_FOR_REVIEW = "READY_FOR_REVIEW"
CLOSED = "CLOSED"
INFORMATION = "INFORMATION"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


class Base(DeclarativeBase):
    pass


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


class Feedback(Base):
    __tablename__ = "mvp_feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("mvp_assignments.id"))
    learner_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    tutor_id: Mapped[str] = mapped_column(ForeignKey("mvp_users.id"))
    criterion: Mapped[str] = mapped_column(String(160), default="")
    feedback_text: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(Text, default="")
    focus_tag: Mapped[str] = mapped_column(String(50), default="")
    teams_reference: Mapped[str] = mapped_column(String(200))
    feedback_required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default=ACTION_REQUIRED)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class NewFeedback(BaseModel):
    assignment_id: str
    learner_id: str
    criterion: str = Field(default="", max_length=160)
    feedback_text: str = Field(min_length=1, max_length=4000)
    next_step: str = Field(default="", max_length=2000)
    focus_tag: str = Field(default="", max_length=50)
    teams_reference: str = Field(min_length=3, max_length=200)
    feedback_required: bool = True


class StatusChange(BaseModel):
    status: Literal["ACTION_REQUIRED", "IN_PROGRESS", "READY_FOR_REVIEW", "CLOSED"]
    progress_note: str = Field(default="", max_length=2000)


class NewComment(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def seed_demo(db: Session) -> None:
    if db.get(User, "tutor-1"):
        return
    db.add_all([
        User(id="tutor-1", name="Jo Morgan", role="tutor"),
        User(id="learner-1", name="Alex Taylor", role="learner"),
        User(id="learner-2", name="Morgan Ellis", role="learner"),
        User(id="admin-1", name="Quality Team", role="admin"),
        Assignment(id="java", title="Java Library System", module="Programming"),
        Assignment(id="database", title="Database Design", module="Databases"),
        Assignment(id="web", title="Accessible Portfolio", module="Web Development"),
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
    for a, learner, criterion, words, step, tag, status, required in samples:
        db.add(Feedback(
            assignment_id=a, learner_id=learner, tutor_id="tutor-1", criterion=criterion,
            feedback_text=words, next_step=step, focus_tag=tag,
            teams_reference="Teams demo assignment " + a,
            status=status, feedback_required=required,
            closed_at=utcnow() if status == CLOSED else None,
        ))
    db.commit()


def create_app(db_url: str | None = None, demo_mode: bool | None = None, seed: bool = True) -> FastAPI:
    """Construct the local MVP. The default demo mode is OFF (fail closed)."""
    is_demo = (os.getenv("FEEDBACK_LOOP_DEMO_MODE") == "1") if demo_mode is None else demo_mode
    url = db_url or os.getenv("FEEDBACK_LOOP_DB_URL", "sqlite:///./feedback_loop_mvp.db")
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    sessions = sessionmaker(engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    if is_demo and seed:
        with sessions() as db:
            seed_demo(db)

    app = FastAPI(title="Feedback Loop — Local MVP", version="0.1.0")
    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    def database():
        with sessions() as db:
            yield db

    def actor(x_demo_user: str | None = Header(default=None), db: Session = Depends(database)) -> User:
        if not is_demo:
            raise HTTPException(403, "Authentication not configured. Entra ID required.")
        if not x_demo_user:
            raise HTTPException(401, "Choose a synthetic demo identity.")
        person = db.get(User, x_demo_user)
        if person is None:
            raise HTTPException(401, "Unknown demo identity.")
        return person

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
        return thread

    def summarise(db: Session, thread: Feedback) -> dict:
        assignment = db.get(Assignment, thread.assignment_id)
        learner = db.get(User, thread.learner_id)
        return {
            "id": thread.id, "assignment": assignment.title, "module": assignment.module,
            "learner": learner.name, "learner_id": thread.learner_id,
            "criterion": thread.criterion, "feedback_text": thread.feedback_text,
            "next_step": thread.next_step, "focus_tag": thread.focus_tag,
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
    def bootstrap(person: User = Depends(actor), db: Session = Depends(database)):
        return {
            "user": {"id": person.id, "name": person.name, "role": person.role},
            "assignments": [{"id": a.id, "title": a.title, "module": a.module}
                            for a in db.scalars(select(Assignment)).all()] if person.role == "tutor" else [],
            "learners": [{"id": u.id, "name": u.name}
                         for u in db.scalars(select(User).where(User.role == "learner")).all()]
                         if person.role == "tutor" else [],
        }

    @app.get("/api/threads")
    def list_threads(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role == "admin":
            raise HTTPException(403, "Use aggregate reports.")
        condition = Feedback.learner_id == person.id if person.role == "learner" else Feedback.tutor_id == person.id
        threads = db.scalars(select(Feedback).where(condition).order_by(Feedback.updated_at.desc())).all()
        return [summarise(db, t) for t in threads]

    @app.get("/api/threads/{fid}")
    def detail(fid: int, person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        return {**summarise(db, thread), "timeline": timeline(db, fid)}

    @app.post("/api/threads", status_code=201)
    def new_thread(payload: NewFeedback, person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "tutor":
            raise HTTPException(403, "Only tutors can author feedback.")
        learner = db.get(User, payload.learner_id)
        if learner is None or learner.role != "learner" or db.get(Assignment, payload.assignment_id) is None:
            raise HTTPException(422, "Choose a valid learner and assignment.")
        if not payload.feedback_text.strip() or (payload.feedback_required and not payload.next_step.strip()):
            raise HTTPException(422, "Feedback text and, when required, an actionable next step are needed.")
        thread = Feedback(
            assignment_id=payload.assignment_id, learner_id=learner.id, tutor_id=person.id,
            criterion=payload.criterion.strip(), feedback_text=payload.feedback_text.strip(),
            next_step=payload.next_step.strip(), focus_tag=payload.focus_tag.strip(),
            teams_reference=payload.teams_reference.strip(), feedback_required=payload.feedback_required,
            status=ACTION_REQUIRED if payload.feedback_required else INFORMATION,
        )
        db.add(thread)
        db.flush()
        db.add(Event(feedback_id=thread.id, actor_id=person.id, description="Tutor shared feedback"))
        db.commit()
        return summarise(db, thread)

    @app.post("/api/threads/{fid}/status")
    def change_status(fid: int, payload: StatusChange, person: User = Depends(actor), db: Session = Depends(database)):
        thread = accessible(db, person, fid)
        current, target = thread.status, payload.status
        if person.role == "learner":
            allowed = {(ACTION_REQUIRED, IN_PROGRESS), (IN_PROGRESS, READY_FOR_REVIEW),
                       (READY_FOR_REVIEW, IN_PROGRESS), (IN_PROGRESS, ACTION_REQUIRED)}
            if not thread.feedback_required or (current, target) not in allowed:
                raise HTTPException(403, "Learners can progress work but cannot close it.")
            if target == READY_FOR_REVIEW and not payload.progress_note.strip():
                raise HTTPException(422, "Explain what you changed before requesting review.")
        elif person.role == "tutor":
            allowed = {(READY_FOR_REVIEW, CLOSED), (INFORMATION, CLOSED),
                       (READY_FOR_REVIEW, IN_PROGRESS), (CLOSED, ACTION_REQUIRED),
                       (ACTION_REQUIRED, IN_PROGRESS), (IN_PROGRESS, READY_FOR_REVIEW)}
            if (current, target) not in allowed:
                raise HTTPException(409, "That tutor transition is not permitted.")
        else:
            raise HTTPException(403, "Only tutors and learners can update work.")
        thread.status = target
        thread.updated_at = utcnow()
        thread.closed_at = utcnow() if target == CLOSED else None
        if person.role == "learner" and target == READY_FOR_REVIEW:
            db.add(Note(feedback_id=fid, author_id=person.id,
                        body="Work submitted for review: " + payload.progress_note.strip()))
        db.add(Event(feedback_id=fid, actor_id=person.id, description=f"Moved from {current} to {target}"))
        db.commit()
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

    @app.get("/api/reports")
    def reports(person: User = Depends(actor), db: Session = Depends(database)):
        if person.role != "admin":
            raise HTTPException(403, "Administrator role required.")
        threads = db.scalars(select(Feedback)).all()
        states = Counter(t.status for t in threads)
        tags = Counter(t.focus_tag for t in threads if t.focus_tag)
        return {
            "total": len(threads), "actions_required": sum(t.feedback_required for t in threads),
            "closed": states[CLOSED],
            "awaiting_review": states[READY_FOR_REVIEW],
            "by_status": [{"status": key, "count": states[key]} for key in
                          (ACTION_REQUIRED, IN_PROGRESS, READY_FOR_REVIEW, CLOSED, INFORMATION)],
            "focus_areas": [{"name": key, "count": count} for key, count in tags.most_common()],
            "note": "Synthetic demonstration data. Aggregate reporting only; no pastoral notes.",
        }

    return app


app = create_app()
