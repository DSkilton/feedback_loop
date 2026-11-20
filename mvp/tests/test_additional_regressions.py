"""Additional workflow, reporting and access-control regression scenarios."""
from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mvp.api import Feedback, create_app
from mvp.events import FEEDBACK_CREATED, FEEDBACK_STATUS_CHANGED, FeedbackChanged
from mvp.reporting import AggregateReportReadModel
from mvp.workflow import FeedbackStateMachine, TransitionRejected


@pytest.fixture
def project(tmp_path):
    location = tmp_path / "workflow-regression.db"
    client = TestClient(create_app(db_url=f"sqlite:///{location}", demo_mode=True))
    return client, location


def identity(client, account):
    client.headers["X-Demo-User"] = account
    return client


def rows(path, sql, params=()):
    with sqlite3.connect(path) as connection:
        return connection.execute(sql, params).fetchall()


def counts(client):
    identity(client, "admin-1")
    return client.get("/api/reports").json()


def test_information_only_reopens_as_information_without_assigning_student_work(project):
    client, path = project
    identity(client, "tutor-1")
    baseline = counts(client)
    identity(client, "tutor-1")
    assert client.post("/api/threads/6/status", json={"status": "CLOSED"}).status_code == 200
    assert client.post("/api/threads/6/status", json={"status": "ACTION_REQUIRED"}).status_code == 409
    response = client.post("/api/threads/6/status", json={"status": "INFORMATION"})
    assert response.status_code == 200
    assert response.json()["status"] == "INFORMATION"
    assert response.json()["feedback_required"] is False
    assert response.json()["closed_at"] is None

    identity(client, "learner-2")
    assert client.post("/api/threads/6/status", json={"status": "IN_PROGRESS"}).status_code == 403
    assert client.post("/api/threads/6/status", json={"status": "READY_FOR_REVIEW",
        "progress_note": "I edited the assignment."}).status_code == 403
    assert client.get("/api/threads/6").json()["status"] == "INFORMATION"

    updated = counts(client)
    assert updated["actions_required"] == baseline["actions_required"]
    assert updated["total"] == baseline["total"]
    assert updated["by_status"] == baseline["by_status"]
    audit = rows(path, "select previous_status,status,tutor_approved from mvp_domain_events where feedback_id=6 order by id")
    assert audit == [("INFORMATION", "CLOSED", 1), ("CLOSED", "INFORMATION", 0)]


def test_actionable_feedback_reopens_only_to_action_required(project):
    client, _ = project
    identity(client, "tutor-1")
    assert client.post("/api/threads/3/status", json={"status": "CLOSED"}).status_code == 200
    assert client.post("/api/threads/3/status", json={"status": "INFORMATION"}).status_code == 409
    assert client.post("/api/threads/3/status", json={"status": "ACTION_REQUIRED"}).status_code == 200
    identity(client, "learner-1")
    assert client.post("/api/threads/3/status", json={"status": "IN_PROGRESS"}).status_code == 200


def test_unknown_roles_cannot_access_thread_list_details_or_reporting(project):
    client, path = project
    with sqlite3.connect(path) as db:
        db.execute("insert into mvp_users (id, name, role) values (?, ?, ?)",
                   ("visitor-1", "Visitor", "observer"))
    identity(client, "visitor-1")
    assert client.get("/api/threads").status_code == 403
    assert client.get("/api/threads/1").status_code == 403
    assert client.post("/api/threads/1/comments", json={"body": "Test"}).status_code == 403
    assert client.post("/api/threads/1/status", json={"status": "CLOSED"}).status_code == 403
    assert client.get("/api/reports").status_code == 403


def test_tutor_assignment_scope_applies_to_read_and_write_endpoints(project):
    client, path = project
    with sqlite3.connect(path) as db:
        db.execute("insert into mvp_users (id, name, role) values (?, ?, ?)",
                   ("tutor-2", "Second Tutor", "tutor"))
        db.execute("update mvp_feedback set tutor_id='tutor-2' where id=1")
    identity(client, "tutor-1")
    assert client.get("/api/threads/1").status_code == 404
    assert client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 404
    assert client.get("/api/threads/1/evidence/1").status_code == 404
    identity(client, "tutor-2")
    assert client.get("/api/threads/1").status_code == 200
    assert client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 200


def test_duplicate_teams_submission_does_not_change_projection_or_audit(project):
    client, path = project
    identity(client, "tutor-1")
    payload = {
        "assignment_id": "java", "learner_id": "learner-1",
        "feedback_text": "Add tests for invalid values.",
        "next_step": "Upload an example failing assertion.",
        "teams_reference": "Teams java review",
        "teams_recorded_confirmed": True,
        "teams_class_id": "class-1",
        "teams_assignment_id": "assignment-1",
        "teams_submission_id": "submission-1",
    }
    assert client.post("/api/threads", json=payload).status_code == 201
    first = counts(client)
    audit_count = rows(path, "select count(*) from mvp_domain_events")[0][0]
    identity(client, "tutor-1")
    assert client.post("/api/threads", json=payload).status_code == 409
    assert counts(client) == first
    assert rows(path, "select count(*) from mvp_domain_events")[0][0] == audit_count
    assert rows(path, "select count(*) from mvp_teams_handoffs")[0][0] == 7


def test_evidence_limit_does_not_append_extra_audit_events(project):
    client, path = project
    identity(client, "learner-1")
    assert client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 200
    for i in range(5):
        response = client.post("/api/threads/1/evidence", files={
            "file": (f"evidence-{i}.txt", b"Updated setter tests.", "text/plain")
        })
        assert response.status_code == 201
    events_before = rows(path, "select count(*) from mvp_events where feedback_id=1")[0][0]
    response = client.post("/api/threads/1/evidence", files={
        "file": ("additional.txt", b"An additional file.", "text/plain")
    })
    assert response.status_code == 409
    assert rows(path, "select count(*) from mvp_evidence where feedback_id=1")[0][0] == 5
    assert rows(path, "select count(*) from mvp_events where feedback_id=1")[0][0] == events_before
    attached = client.get("/api/threads/1").json()["evidence"]
    assert len(attached) == 5
    assert all(len(item["sha256"]) == 64 for item in attached)


def test_evidence_ids_cannot_be_reused_on_unrelated_threads(project):
    client, _ = project
    identity(client, "learner-1")
    client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"})
    result = client.post("/api/threads/1/evidence", files={
        "file": ("proof.txt", b"New evidence", "text/plain")
    })
    assert result.status_code == 201
    file_id = result.json()["id"]
    assert client.get(f"/api/threads/2/evidence/{file_id}").status_code == 404
    assert client.get(f"/api/threads/1/evidence/{file_id}").status_code == 200
    identity(client, "admin-1")
    assert client.get(f"/api/threads/1/evidence/{file_id}").status_code == 403


def test_projection_rebuild_is_repeatable_and_restores_correct_counts(project):
    client, path = project
    identity(client, "tutor-1")
    assert client.post("/api/threads/3/status", json={"status": "CLOSED"}).status_code == 200
    expected = counts(client)
    with sqlite3.connect(path) as connection:
        connection.execute("update mvp_report_counters set value=99 where key='total'")
    assert counts(client)["total"] == 99
    engine = create_engine(f"sqlite:///{path}")
    model = AggregateReportReadModel()
    with Session(engine) as db:
        model.rebuild(db, Feedback)
        db.commit()
        assert model.snapshot(db) == expected
        model.rebuild(db, Feedback)
        db.commit()
        assert model.snapshot(db) == expected


def test_typed_domain_event_validation_and_immutability():
    valid = FeedbackChanged(
        event_type=FEEDBACK_STATUS_CHANGED, feedback_id=1, actor_id="tutor-1",
        previous_status="READY_FOR_REVIEW", status="CLOSED",
        feedback_required=True, focus_tag="Testing", tutor_approved=True,
    )
    assert valid.tutor_approved
    with pytest.raises(FrozenInstanceError):
        valid.status = "ACTION_REQUIRED"
    with pytest.raises(ValueError, match="Unsupported"):
        FeedbackChanged(event_type="invalid", feedback_id=1, actor_id="tutor-1",
                        previous_status=None, status="CLOSED", feedback_required=True, focus_tag="")
    with pytest.raises(ValueError, match="previous state"):
        FeedbackChanged(event_type=FEEDBACK_STATUS_CHANGED, feedback_id=1, actor_id="tutor-1",
                        previous_status=None, status="CLOSED", feedback_required=True, focus_tag="")
    with pytest.raises(ValueError, match="must not have"):
        FeedbackChanged(event_type=FEEDBACK_CREATED, feedback_id=1, actor_id="tutor-1",
                        previous_status="IN_PROGRESS", status="CLOSED", feedback_required=True, focus_tag="")


@pytest.mark.parametrize("current,target,required", [
    ("CLOSED", "ACTION_REQUIRED", False),
    ("CLOSED", "INFORMATION", True),
])
def test_state_machine_cannot_change_information_flag_implicitly(current, target, required):
    with pytest.raises(TransitionRejected) as err:
        FeedbackStateMachine().decide(current=current, target=target,
                                      actor_role="tutor", feedback_required=required)
    assert err.value.code == 409
