"""Core role/transition tests with synthetic data in isolated SQLite databases."""
import pytest
from fastapi.testclient import TestClient
from mvp.api import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path / 'feedback.db'}", demo_mode=True)
    return TestClient(app)


def as_user(client, user):
    client.headers["X-Demo-User"] = user
    return client


def test_demo_disabled_by_default(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path / 'closed.db'}", demo_mode=False)
    response = TestClient(app).get("/api/bootstrap", headers={"X-Demo-User": "tutor-1"})
    assert response.status_code == 403


def test_student_can_progress_own_work_but_cannot_close(client):
    as_user(client, "learner-1")
    response = client.get("/api/threads")
    assert response.status_code == 200
    own = response.json()
    assert own and all(t["learner_id"] == "learner-1" for t in own)
    assert client.get("/api/threads/4").status_code == 404
    thread = next(t for t in own if t["status"] == "ACTION_REQUIRED")
    fid = thread["id"]
    assert client.post(f"/api/threads/{fid}/status", json={"status": "CLOSED"}).status_code == 403
    assert client.post(f"/api/threads/{fid}/status", json={"status": "IN_PROGRESS"}).status_code == 200
    assert client.post(f"/api/threads/{fid}/status", json={"status": "READY_FOR_REVIEW"}).status_code == 200
    assert client.post(f"/api/threads/{fid}/status", json={"status": "CLOSED"}).status_code == 403
    assert client.post("/api/threads", json={}).status_code == 422  # invalid payload cannot be written
    assert client.get("/api/reports").status_code == 403


def test_teacher_reviews_closes_and_reopens(client):
    as_user(client, "tutor-1")
    assert client.post("/api/threads/1/status", json={"status": "CLOSED"}).status_code == 409
    # Synthetic seeded record 3 is ready for a tutor decision.
    result = client.post("/api/threads/3/status", json={"status": "CLOSED"})
    assert result.status_code == 200
    assert result.json()["closed_at"] is not None
    details = client.get("/api/threads/3").json()
    assert any("CLOSED" in event["text"] for event in details["timeline"])
    reopened = client.post("/api/threads/3/status", json={"status": "ACTION_REQUIRED"})
    assert reopened.status_code == 200
    assert reopened.json()["closed_at"] is None


def test_student_cannot_edit_tutor_feedback_or_other_students_comments(client):
    as_user(client, "learner-1")
    assert client.post("/api/threads/4/comments", json={"body": "Hello"}).status_code == 404
    assert client.post("/api/threads/4/status", json={"status": "IN_PROGRESS"}).status_code == 404
    assert client.post("/api/threads/1/comments", json={"body": "I've started the work."}).status_code == 201
    details = client.get("/api/threads/1").json()
    assert any(e["text"] == "I've started the work." for e in details["timeline"])
    assert details["feedback_text"].startswith("Your Book class")
    assert client.post("/api/threads/1/comments", json={"body": "  "}).status_code == 422


def test_teacher_controls_feedback_required_checkbox(client):
    as_user(client, "tutor-1")
    created = client.post("/api/threads", json={
        "assignment_id": "java", "learner_id": "learner-1",
        "feedback_text": "Well-structured solution. No additional work this week.",
        "next_step": "", "teams_reference": "Teams assignment java",
        "feedback_required": False,
    })
    assert created.status_code == 201
    assert created.json()["status"] == "INFORMATION"
    assert created.json()["feedback_required"] is False
    fid = created.json()["id"]
    as_user(client, "learner-1")
    assert client.post(f"/api/threads/{fid}/status", json={"status": "CLOSED"}).status_code == 403
    as_user(client, "tutor-1")
    assert client.post(f"/api/threads/{fid}/status", json={"status": "CLOSED"}).status_code == 200


def test_feedback_required_must_include_action_and_teams_reference(client):
    as_user(client, "tutor-1")
    data = {
        "assignment_id": "java", "learner_id": "learner-1",
        "feedback_text": "Your solution is improving.",
        "next_step": "", "teams_reference": "Teams java",
        "feedback_required": True,
    }
    assert client.post("/api/threads", json=data).status_code == 422
    data["next_step"] = "Add an edge-case test."
    assert client.post("/api/threads", json=data).status_code == 201
    data["teams_reference"] = ""
    assert client.post("/api/threads", json=data).status_code == 422


def test_quality_reporting_aggregate_only(client):
    as_user(client, "admin-1")
    response = client.get("/api/reports")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 6
    assert data["actions_required"] == 5
    assert data["awaiting_review"] == 1
    assert "learners" not in data and "pastoral" in data["note"]
    assert client.get("/api/threads").status_code == 403
    assert client.get("/api/threads/1").status_code == 403


def test_unknown_demo_identity_is_rejected(client):
    response = client.get("/api/bootstrap", headers={"X-Demo-User": "not-a-person"})
    assert response.status_code == 401
