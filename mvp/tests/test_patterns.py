"""Regression tests for state-machine rules, Observer audit and CQRS projection."""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from mvp.api import create_app
from mvp.reporting import AggregateReportReadModel, ReportCounter
from mvp.workflow import FeedbackStateMachine, TransitionRejected


@pytest.mark.parametrize("role,current,target,required,note,approved", [
    ("learner", "ACTION_REQUIRED", "IN_PROGRESS", True, "", False),
    ("learner", "IN_PROGRESS", "ACTION_REQUIRED", True, "", False),
    ("learner", "IN_PROGRESS", "READY_FOR_REVIEW", True, "Added assertions", False),
    ("learner", "READY_FOR_REVIEW", "IN_PROGRESS", True, "", False),
    ("tutor", "READY_FOR_REVIEW", "CLOSED", True, "", True),
    ("tutor", "INFORMATION", "CLOSED", False, "", True),
    ("tutor", "CLOSED", "ACTION_REQUIRED", True, "", False),
    ("tutor", "READY_FOR_REVIEW", "IN_PROGRESS", True, "", False),
])
def test_state_machine_allows_explicit_role_scoped_transitions(
    role, current, target, required, note, approved
):
    transition = FeedbackStateMachine().decide(
        current=current, target=target, actor_role=role,
        feedback_required=required, progress_note=note,
    )
    assert transition.previous == current
    assert transition.target == target
    assert transition.tutor_approved is approved


@pytest.mark.parametrize("role,current,target,required,note,code", [
    ("learner", "READY_FOR_REVIEW", "CLOSED", True, "", 403),
    ("learner", "INFORMATION", "CLOSED", False, "", 403),
    ("learner", "IN_PROGRESS", "READY_FOR_REVIEW", True, "   ", 422),
    ("learner", "ACTION_REQUIRED", "IN_PROGRESS", False, "", 403),
    ("learner", "CLOSED", "IN_PROGRESS", True, "", 403),
    ("tutor", "ACTION_REQUIRED", "CLOSED", True, "", 409),
    ("tutor", "IN_PROGRESS", "CLOSED", True, "", 409),
    ("admin", "READY_FOR_REVIEW", "CLOSED", True, "", 403),
    ("tutor", "INFORMATION", "READY_FOR_REVIEW", False, "", 409),
    ("tutor", "CLOSED", "CLOSED", True, "", 409),
])
def test_state_machine_rejects_illegal_actions(role, current, target, required, note, code):
    with pytest.raises(TransitionRejected) as exc:
        FeedbackStateMachine().decide(
            current=current, target=target, actor_role=role,
            feedback_required=required, progress_note=note,
        )
    assert exc.value.code == code


@pytest.fixture
def system(tmp_path):
    path = tmp_path / "read_models.db"
    db_url = f"sqlite:///{path}"
    client = TestClient(create_app(db_url=db_url, demo_mode=True))
    return client, path, db_url


def caller(client, identity):
    client.headers["X-Demo-User"] = identity
    return client


def query(path, sql, params=()):
    with sqlite3.connect(path) as connection:
        return connection.execute(sql, params).fetchall()


def test_observer_audit_and_report_counters_share_one_commit(system):
    client, path, _ = system
    before = query(path, "select count(*) from mvp_domain_events")[0][0]
    caller(client, "learner-1")
    assert client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"}).status_code == 200
    assert client.post("/api/threads/1/status", json={
        "status": "READY_FOR_REVIEW", "progress_note": "Tests now include invalid inputs."
    }).status_code == 200

    caller(client, "tutor-1")
    assert client.post("/api/threads/1/status", json={"status": "CLOSED"}).status_code == 200
    history = client.get("/api/threads/1").json()["timeline"]
    assert any("Tutor approved and CLOSED" in item["text"] for item in history)

    records = query(path, """
        select event_type, previous_status, status, tutor_approved, actor_id
        from mvp_domain_events where feedback_id=1 order by id
    """)
    assert [x[:4] for x in records] == [
        ("feedback.status_changed", "ACTION_REQUIRED", "IN_PROGRESS", 0),
        ("feedback.status_changed", "IN_PROGRESS", "READY_FOR_REVIEW", 0),
        ("feedback.status_changed", "READY_FOR_REVIEW", "CLOSED", 1),
    ]
    assert records[-1][-1] == "tutor-1"
    assert query(path, "select count(*) from mvp_domain_events")[0][0] == before + 3

    caller(client, "admin-1")
    report = client.get("/api/reports").json()
    assert report["total"] == 6
    assert report["closed"] == 2
    assert report["awaiting_review"] == 0
    assert report["actions_required"] == 5
    # The read model agrees with authoritative feedback, but a GET does not scan it.
    projection = {
        row["status"]: row["count"] for row in report["by_status"]
    }
    write_states = dict(query(path,
        "select status, count(*) from mvp_feedback group by status"))
    assert all(projection[status] == count for status, count in write_states.items())


def test_creation_observer_updates_focus_and_actions(system):
    client, path, _ = system
    caller(client, "tutor-1")
    response = client.post("/api/threads", json={
        "assignment_id": "java", "learner_id": "learner-1",
        "feedback_text": "Add a negative test case.",
        "next_step": "Provide evidence of the failing input.",
        "focus_tag": "Testing", "teams_reference": "Teams java exercise",
        "teams_recorded_confirmed": True,
    })
    assert response.status_code == 201
    assert query(path, "select event_type from mvp_domain_events where feedback_id=?",
                 (response.json()["id"],)) == [("feedback.created",)]
    caller(client, "admin-1")
    report = client.get("/api/reports").json()
    assert report["total"] == 7 and report["actions_required"] == 6
    assert next(t["count"] for t in report["focus_areas"] if t["name"] == "Testing") == 2
    assert next(t["count"] for t in report["by_status"] if t["status"] == "ACTION_REQUIRED") == 3


def test_refused_transition_has_no_event_or_projection_effect(system):
    client, path, _ = system
    caller(client, "learner-1")
    assert client.post("/api/threads/1/status", json={"status": "CLOSED"}).status_code == 403
    assert client.post("/api/threads/1/status", json={"status": "READY_FOR_REVIEW"}).status_code == 403
    assert query(path, "select count(*) from mvp_domain_events")[0][0] == 0
    assert query(path, "select status from mvp_feedback where id=1") == [("ACTION_REQUIRED",)]
    assert query(path, "select value from mvp_report_counters where key='status:ACTION_REQUIRED'") == [(2,)]


def test_observer_projection_failure_rolls_back_workflow_and_audit(system):
    client, path, _ = system
    # Simulate a damaged projection. A decrement from zero must fail loudly,
    # never leave a committed workflow change with stale management metrics.
    with sqlite3.connect(path) as db:
        db.execute("update mvp_report_counters set value=0 where key='status:ACTION_REQUIRED'")
    caller(client, "learner-1")
    with pytest.raises(RuntimeError, match="projection out of sync"):
        client.post("/api/threads/1/status", json={"status": "IN_PROGRESS"})
    assert query(path, "select status from mvp_feedback where id=1") == [("ACTION_REQUIRED",)]
    assert query(path, "select count(*) from mvp_domain_events")[0][0] == 0
    assert query(path, "select count(*) from mvp_events")[0][0] == 0


def test_backfill_older_database_and_read_only_query(system):
    client, path, db_url = system
    with sqlite3.connect(path) as db:
        db.execute("delete from mvp_report_counters")
    # Simulate upgrading an existing local demo database, without re-seeding.
    create_app(db_url=db_url, demo_mode=False)
    assert query(path, "select value from mvp_report_counters where key='total'") == [(6,)]
    engine = create_engine(db_url)
    statements = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, sql, params, ctx, many: statements.append(sql))
    with Session(engine) as db:
        model = AggregateReportReadModel().snapshot(db)
    assert model["total"] == 6
    assert all("mvp_feedback" not in statement for statement in statements)
    assert any("mvp_report_counters" in statement for statement in statements)


def test_admin_read_model_has_no_student_evidence_access(system):
    client, _, _ = system
    caller(client, "admin-1")
    result = client.get("/api/reports")
    assert result.status_code == 200
    assert "learner_id" not in str(result.json())
    assert "feedback_text" not in str(result.json())
    assert client.get("/api/threads/1/evidence/1").status_code == 403
