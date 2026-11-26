"""Contract tests for teacher review, optimistic concurrency and partial bulk publishing."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from mvp.api import create_app


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "bulk.db"
    client = TestClient(create_app(db_url=f"sqlite:///{path}", demo_mode=True))
    client.headers["X-Demo-User"] = "tutor-1"
    return client, path


def item(learner, key, **overrides):
    data = {
        "client_key": key,
        "assignment_id": "java",
        "cohort_id": "computing-26",
        "learner_id": learner,
        "feedback_text": "Specific feedback on your programming assignment.",
        "next_step": "",
        "feedback_required": False,
        "judgement": "good",
        "work_url": "https://teams.microsoft.com/example",
        "teams_reference": "Teams Unit 4 feedback",
        "teams_recorded_confirmed": True,
    }
    data.update(overrides)
    return data


def test_bulk_continues_after_failed_row_and_reports_per_row_outcomes(workspace):
    client, path = workspace
    start = client.get("/api/threads").json()
    base_count = len(start)
    payload = [
        item("learner-1", "00000000-0000-4000-8000-000000000001"),
        item("learner-3", "00000000-0000-4000-8000-000000000002"),
        item("learner-2", "00000000-0000-4000-8000-000000000003"),
    ]
    response = client.post("/api/threads/bulk", json={"items": payload})
    assert response.status_code == 200
    result = response.json()
    assert result["saved"] == 2 and result["failed"] == 1
    assert [r["ok"] for r in result["results"]] == [True, False, True]
    assert result["results"][1]["code"] == 403
    assert len(client.get("/api/threads").json()) == base_count + 2
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_feedback_submissions").fetchone()[0] == 2


def test_bulk_retries_return_original_result_and_reject_changed_key(workspace):
    client, path = workspace
    payload = item("learner-1", "00000000-0000-4000-8000-000000000004")
    first = client.post("/api/threads/bulk", json={"items": [payload]}).json()
    assert first["saved"] == 1
    second = client.post("/api/threads/bulk", json={"items": [payload]}).json()
    assert second["saved"] == 1 and second["results"][0]["replayed"] is True
    assert second["results"][0]["feedback_id"] == first["results"][0]["feedback_id"]
    edited = {**payload, "feedback_text": "Changed after a lost acknowledgement"}
    conflict = client.post("/api/threads/bulk", json={"items": [edited]}).json()
    assert conflict["saved"] == 0 and conflict["results"][0]["code"] == 409
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_feedback_submissions").fetchone()[0] == 1


def test_failed_row_can_be_corrected_with_new_key(workspace):
    client, _ = workspace
    invalid = item("learner-3", "00000000-0000-4000-8000-000000000005")
    assert client.post("/api/threads/bulk", json={"items": [invalid]}).json()["failed"] == 1
    valid = item("learner-1", "00000000-0000-4000-8000-000000000006")
    assert client.post("/api/threads/bulk", json={"items": [valid]}).json()["saved"] == 1


def test_versioned_closure_requires_tutor_judgement_and_specific_note(workspace):
    client, path = workspace
    original = client.get("/api/threads/3").json()
    version = original["version"]
    response = client.post("/api/threads/3/status", json={"status": "CLOSED", "expected_version": version})
    assert response.status_code == 422
    approved = client.post("/api/threads/3/status", json={
        "status": "CLOSED", "expected_version": version,
        "judgement": "very_good", "review_note": "Clear evidence of improvement and better testing."
    })
    assert approved.status_code == 200
    assert approved.json()["version"] == version + 1
    details = client.get("/api/threads/3").json()
    assert details["reviews"][-1]["judgement"] == "very_good"
    assert "better testing" in details["reviews"][-1]["note"]
    assert any("Very good" in event["text"] for event in details["timeline"])
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_feedback_reviews where feedback_id=3").fetchone()[0] == 1


def test_stale_status_cannot_overwrite_tutor_decision_or_duplicate_events(workspace):
    client, path = workspace
    version = client.get("/api/threads/3").json()["version"]
    close = {
        "status": "CLOSED", "expected_version": version,
        "judgement": "satisfactory", "review_note": "The learner has addressed the required change.",
    }
    assert client.post("/api/threads/3/status", json=close).status_code == 200
    before = client.get("/api/threads/3").json()
    with sqlite3.connect(path) as connection:
        count = connection.execute("select count(*) from mvp_domain_events where feedback_id=3").fetchone()[0]
    assert client.post("/api/threads/3/status", json=close).status_code == 409
    assert client.post("/api/threads/3/status", json={"status": "ACTION_REQUIRED", "expected_version": version}).status_code == 409
    assert client.get("/api/threads/3").json()["version"] == before["version"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_domain_events where feedback_id=3").fetchone()[0] == count


def test_information_only_close_does_not_invent_assessment_judgement(workspace):
    client, path = workspace
    version = client.get("/api/threads/6").json()["version"]
    result = client.post("/api/threads/6/status", json={"status": "CLOSED", "expected_version": version})
    assert result.status_code == 200
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_feedback_reviews where feedback_id=6").fetchone()[0] == 0


def test_bulk_rejects_unauthorised_roles_and_invalid_work_links(workspace):
    client, path = workspace
    invalid = item("learner-1", "00000000-0000-4000-8000-000000000007", work_url="javascript:alert(1)")
    rejected = client.post("/api/threads/bulk", json={"items": [invalid]})
    assert rejected.status_code == 200
    assert rejected.json()["results"][0]["code"] == 422
    client.headers["X-Demo-User"] = "learner-1"
    assert client.post("/api/threads/bulk", json={"items": [item("learner-1", "00000000-0000-4000-8000-000000000008")]}).status_code == 403
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from mvp_feedback_submissions").fetchone()[0] == 0


def test_schema_invalid_row_does_not_prevent_later_valid_saves(workspace):
    client, _ = workspace
    bad = item("learner-1", "00000000-0000-4000-8000-000000000009", work_url="http://untrusted.example")
    good = item("learner-2", "00000000-0000-4000-8000-000000000010")
    response = client.post("/api/threads/bulk", json={"items": [bad, good]})
    assert response.status_code == 200
    result = response.json()
    assert result["saved"] == 1 and result["failed"] == 1
    assert [r["code"] for r in result["results"] if not r["ok"]] == [422]
    assert result["results"][1]["ok"] is True
