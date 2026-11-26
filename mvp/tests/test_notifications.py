"""Notification inbox permissions, transactional creation, and reminder idempotency."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from mvp.api import Enrollment, Feedback, StructuredFeedbackEvent, create_app
from mvp.notifications import Notification, due_review_reminders
from mvp.tests.helpers import versioned_status_post


@pytest.fixture
def workspace(tmp_path):
    url = f"sqlite:///{tmp_path / 'notifications.db'}"
    app = create_app(db_url=url, demo_mode=True)
    return TestClient(app), create_engine(url)


def identity(client, name):
    client.headers["X-Demo-User"] = name
    return client


def inbox(client):
    response = client.get("/api/notifications")
    assert response.status_code == 200
    return response.json()


def test_publish_and_review_notifications_are_recipient_scoped(workspace):
    client, _ = workspace
    identity(client, "tutor-1")
    payload = {"assignment_id": "java", "cohort_id": "computing-26", "learner_id": "learner-1",
               "feedback_text": "Review the tests.", "next_step": "Add test cases.",
               "teams_reference": "Demo assignment", "teams_recorded_confirmed": True}
    response = client.post("/api/threads", json=payload)
    assert response.status_code == 201
    fid = response.json()["id"]
    assert inbox(client)["unread_count"] == 0
    identity(client, "learner-1")
    first = inbox(client)
    assert first["unread_count"] == 1
    notification = first["items"][0]
    assert notification["kind"] == "feedback_published"
    assert notification["feedback_id"] == fid
    identity(client, "learner-2")
    assert inbox(client)["items"] == []
    assert client.post(f"/api/notifications/{notification['id']}/read").status_code == 404
    identity(client, "learner-1")
    assert client.post(f"/api/notifications/{notification['id']}/read").status_code == 200
    assert inbox(client)["unread_count"] == 0
    assert versioned_status_post(client, f"/api/threads/{fid}/status", json={"status": "IN_PROGRESS"}).status_code == 200
    assert versioned_status_post(client, f"/api/threads/{fid}/status", json={"status": "READY_FOR_REVIEW", "progress_note": "Added tests."}).status_code == 200
    identity(client, "tutor-1")
    assert inbox(client)["items"][0]["kind"] == "review_requested"
    assert versioned_status_post(client, f"/api/threads/{fid}/status", json={"status": "CLOSED"}).status_code == 200
    identity(client, "learner-1")
    assert inbox(client)["items"][0]["kind"] == "review_completed"
    assert client.post("/api/notifications/read-all").status_code == 200
    assert inbox(client)["unread_count"] == 0


def test_idempotent_bulk_replay_creates_one_notification(workspace):
    client, engine = workspace
    identity(client, "tutor-1")
    payload = {"client_key": "00000000-0000-4000-8000-000000000011", "assignment_id": "java",
               "cohort_id": "computing-26", "learner_id": "learner-1", "feedback_required": False,
               "feedback_text": "Good progress.", "teams_reference": "Demo assignment", "teams_recorded_confirmed": True}
    for _ in range(2):
        assert client.post("/api/threads/bulk", json={"items": [payload]}).json()["saved"] == 1
    with Session(engine) as db:
        assert len(db.scalars(select(Notification)).all()) == 1


def test_reminders_are_daily_idempotent_configurable_and_skip_closed_work(workspace):
    client, engine = workspace
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.execute(update(Feedback).where(Feedback.id == 3).values(updated_at=now - timedelta(days=2)))
        db.commit()
        assert due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent, now=now) == 1
        db.commit()
        assert due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent, now=now) == 0
        db.commit()
    identity(client, "tutor-1")
    assert inbox(client)["items"][0]["kind"] == "review_reminder"
    assert client.put("/api/notifications/preferences", json={"desktop_enabled": False, "review_reminders": False}).status_code == 200
    with Session(engine) as db:
        assert due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent, now=now + timedelta(days=1)) == 0
    assert client.put("/api/notifications/preferences", json={"desktop_enabled": True, "review_reminders": True}).status_code == 200
    assert versioned_status_post(client, "/api/threads/3/status", json={"status": "CLOSED"}).status_code == 200
    with Session(engine) as db:
        assert due_review_reminders(db, Feedback, Enrollment, StructuredFeedbackEvent, now=now + timedelta(days=2)) == 0


def test_revoked_enrolment_hides_existing_notifications(workspace):
    client, engine = workspace
    identity(client, "learner-1")
    assert versioned_status_post(client, "/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 200
    assert versioned_status_post(client, "/api/threads/1/status", json={"status": "READY_FOR_REVIEW", "progress_note": "Ready."}).status_code == 200
    identity(client, "tutor-1")
    assert inbox(client)["unread_count"] == 1
    nid = inbox(client)["items"][0]["id"]
    with Session(engine) as db:
        row = db.scalar(select(Enrollment).where(Enrollment.user_id == "tutor-1", Enrollment.cohort_id == "computing-26"))
        db.delete(row)
        db.commit()
    assert inbox(client)["items"] == []
    assert client.post(f"/api/notifications/{nid}/read").status_code == 404
