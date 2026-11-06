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
    assert client.post(f"/api/threads/{fid}/status", json={"status": "READY_FOR_REVIEW"}).status_code == 422
    assert client.post(f"/api/threads/{fid}/status", json={"status": "READY_FOR_REVIEW", "progress_note": "Added validation and tests."}).status_code == 200
    history = client.get(f"/api/threads/{fid}").json()["timeline"]
    assert any("Added validation and tests." in e["text"] for e in history)
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
        "teams_recorded_confirmed": True,
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
        "teams_recorded_confirmed": True,
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


def test_teams_handoff_requires_tutor_confirmation_and_blocks_duplicates(client):
    as_user(client, "tutor-1")
    payload = {
        "assignment_id": "java", "learner_id": "learner-1",
        "feedback_text": "Your loops are clear; check edge cases.",
        "next_step": "Add a test for an empty list.", "focus_tag": "Testing",
        "teams_reference": "https://teams.microsoft.com/l/assignment-demo",
        "teams_class_id": "demo-class-1",
        "teams_assignment_id": "demo-assignment-1",
        "teams_submission_id": "demo-submission-1",
        "feedback_required": True,
    }
    assert client.post("/api/threads", json=payload).status_code == 422
    payload["teams_recorded_confirmed"] = True
    response = client.post("/api/threads", json=payload)
    assert response.status_code == 201
    handoff = client.get(f"/api/threads/{response.json()['id']}").json()["teams_handoff"]
    assert handoff["teams_class_id"] == "demo-class-1"
    assert handoff["confirmed_at"] is not None
    assert client.post("/api/threads", json=payload).status_code == 409
    payload["teams_submission_id"] = ""
    assert client.post("/api/threads", json=payload).status_code == 422


def test_evidence_upload_download_is_private_and_validated(client):
    as_user(client, "learner-1")
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
    assert client.post("/api/threads/1/evidence", files={"file": ("work.pdf", pdf, "application/pdf")}).status_code == 403
    assert client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 200
    wrong = client.post("/api/threads/1/evidence", files={"file": ("bad.png", pdf, "image/png")})
    assert wrong.status_code == 422
    large = client.post("/api/threads/1/evidence", files={"file": ("big.pdf", b"%PDF-" + b"a" * (2 * 1024 * 1024), "application/pdf")})
    assert large.status_code == 413
    invalid = client.post("/api/threads/1/evidence", files={"file": ("run.html", b"<script></script>", "text/html")})
    assert invalid.status_code == 422
    uploaded = client.post("/api/threads/1/evidence", data={"caption": "Validation test results"},
                           files={"file": ("../test.pdf", pdf, "application/pdf")})
    assert uploaded.status_code == 201
    eid = uploaded.json()["id"]
    assert uploaded.json()["filename"] == "test.pdf"
    detail = client.get("/api/threads/1").json()
    assert detail["evidence"][0]["caption"] == "Validation test results"
    assert any("Attached evidence" in item["text"] for item in detail["timeline"])
    own_download = client.get(f"/api/threads/1/evidence/{eid}")
    assert own_download.status_code == 200 and own_download.content == pdf
    assert "attachment;" in own_download.headers["content-disposition"]
    assert own_download.headers["x-content-type-options"] == "nosniff"
    as_user(client, "learner-2")
    assert client.get(f"/api/threads/1/evidence/{eid}").status_code == 404
    assert client.post("/api/threads/1/evidence", files={"file": ("work.pdf", pdf)}).status_code == 404
    as_user(client, "admin-1")
    assert client.get(f"/api/threads/1/evidence/{eid}").status_code == 403
    as_user(client, "tutor-1")
    assert client.get(f"/api/threads/1/evidence/{eid}").status_code == 200
    assert client.post("/api/threads/1/evidence", files={"file": ("work.pdf", pdf)}).status_code == 403


def test_recurring_tags_across_distinct_assignments_and_role_scope(client):
    as_user(client, "tutor-1")
    # Existing seeded learner-1 has "Data modelling" on the database assignment.
    data = {
        "assignment_id": "web", "learner_id": "learner-1",
        "feedback_text": "Consider the data structures behind the form.",
        "next_step": "Show how the fields map to the database.",
        "focus_tag": "data modelling", "teams_reference": "Teams web assignment second task",
        "teams_recorded_confirmed": True,
    }
    assert client.post("/api/threads", json=data).status_code == 201
    focus = client.get("/api/tutor/focus-areas")
    assert focus.status_code == 200
    items = focus.json()["recurring"]
    assert len(items) == 1
    assert items[0]["learner_id"] == "learner-1"
    assert items[0]["assignment_count"] == 2
    assert items[0]["feedback_count"] == 2
    # A second feedback record for the same assignment doesn't create
    # an extra distinct-assignment development issue.
    same = {**data, "teams_reference": "Teams database extra criterion", "assignment_id": "database"}
    assert client.post("/api/threads", json=same).status_code == 201
    items = client.get("/api/tutor/focus-areas").json()["recurring"]
    assert items[0]["assignment_count"] == 2 and items[0]["feedback_count"] == 3
    as_user(client, "learner-1")
    assert client.get("/api/tutor/focus-areas").status_code == 403
    as_user(client, "admin-1")
    assert client.get("/api/tutor/focus-areas").status_code == 403
