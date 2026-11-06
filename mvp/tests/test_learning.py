"""Synthetic course/roster, rubric and longitudinal-target integration tests.

Security properties are exercised at the HTTP boundary, not only in UI filters.
"""
import pytest
from fastapi.testclient import TestClient

from mvp.api import create_app


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(
        db_url=f"sqlite:///{tmp_path / 'learning.db'}", demo_mode=True))


def as_person(client, identity):
    client.headers["X-Demo-User"] = identity
    return client


def feedback_payload(**updates):
    data = {
        "assignment_id": "java",
        "cohort_id": "computing-26",
        "learner_id": "learner-1",
        "feedback_text": "Explain which tests demonstrate the encapsulation requirement.",
        "next_step": "Add tests for invalid property values.",
        "teams_reference": "Synthetic Teams Java task",
        "teams_recorded_confirmed": True,
        "feedback_required": True,
    }
    data.update(updates)
    return data


def test_cohort_roster_is_role_scoped(client):
    as_person(client, "tutor-1")
    cohorts = client.get("/api/cohorts").json()
    assert len(cohorts) == 1
    assert cohorts[0]["id"] == "computing-26"
    assert {x["id"] for x in cohorts[0]["learners"]} == {"learner-1", "learner-2"}
    bootstrap = client.get("/api/bootstrap").json()
    assert all(x["cohort_id"] == "computing-26" for x in bootstrap["learners"])
    assert {a["id"] for a in bootstrap["assignments"]} == {"java", "database", "web"}

    as_person(client, "learner-1")
    mine = client.get("/api/cohorts").json()
    assert mine[0]["id"] == "computing-26" and mine[0]["learners"] is None
    assert client.get("/api/targets").status_code == 200
    assert client.get("/api/assignments/java/criteria", params={"cohort_id": "web-26"}).status_code == 404

    as_person(client, "tutor-2")
    theirs = client.get("/api/cohorts").json()
    assert len(theirs) == 1
    assert theirs[0]["id"] == "web-26"
    assert [student["id"] for student in theirs[0]["learners"]] == ["learner-3"]
    assert [a["id"] for a in client.get("/api/bootstrap").json()["assignments"]] == ["web"]
    assert client.get("/api/threads/1").status_code == 404

    as_person(client, "admin-1")
    assert client.get("/api/cohorts").status_code == 403
    assert client.get("/api/targets").status_code == 403
    assert client.get("/api/assignments/java/criteria", params={"cohort_id": "computing-26"}).status_code == 404


def test_cannot_author_feedback_outside_shared_cohort(client):
    as_person(client, "tutor-1")
    assert client.post("/api/threads", json=feedback_payload(
        learner_id="learner-3", assignment_id="web")).status_code == 403
    assert client.post("/api/threads", json=feedback_payload(
        cohort_id="web-26", assignment_id="web")).status_code == 403
    as_person(client, "tutor-2")
    assert client.post("/api/threads", json=feedback_payload()).status_code == 403
    assert client.post("/api/threads", json=feedback_payload(
        assignment_id="web", cohort_id="web-26", learner_id="learner-3")).status_code == 201
    as_person(client, "learner-3")
    assert client.get("/api/threads/1").status_code == 404
    assert {t["learner_id"] for t in client.get("/api/threads").json()} == {"learner-3"}


def test_rubric_criterion_matches_assignment_and_teacher_is_authorised(client):
    as_person(client, "tutor-1")
    entries = client.get("/api/assignments/java/criteria", params={
        "cohort_id": "computing-26"}).json()
    lo2 = next(x for x in entries if x["code"] == "LO2")
    posted = client.post("/api/threads", json=feedback_payload(
        criterion_id=lo2["id"]))
    assert posted.status_code == 201
    assert posted.json()["criterion_id"] == lo2["id"]
    assert "Encapsulation" not in posted.json()["criterion"]
    assert "Use abstraction" in posted.json()["criterion"]
    assert client.post("/api/threads", json=feedback_payload(
        assignment_id="database", criterion_id=lo2["id"])).status_code == 422

    added = client.post("/api/assignments/java/criteria", json={
        "cohort_id": "computing-26", "code": "P1", "description": "Apply validation safely"})
    assert added.status_code == 201 and added.json()["code"] == "P1"
    assert client.post("/api/assignments/java/criteria", json={
        "cohort_id": "computing-26", "code": "P1", "description": "Duplicate"}).status_code == 409
    as_person(client, "learner-1")
    assert client.post("/api/assignments/java/criteria", json={
        "cohort_id": "computing-26", "code": "P2", "description": "Not teacher"}).status_code == 403
    as_person(client, "tutor-2")
    assert client.post("/api/assignments/java/criteria", json={
        "cohort_id": "computing-26", "code": "P3", "description": "Not assigned"}).status_code == 403


def test_persistent_target_links_different_assignments_and_only_tutor_achieves(client):
    as_person(client, "tutor-1")
    created = client.post("/api/targets", json={
        "cohort_id": "computing-26", "learner_id": "learner-2",
        "title": "Demonstrate testing decisions",
        "guidance": "Explain why your test cases prove the expected results."})
    assert created.status_code == 201
    tid = created.json()["id"]
    assert created.json()["status"] == "OPEN"
    first = client.post(f"/api/targets/{tid}/links", json={"feedback_id": 4})
    second = client.post(f"/api/targets/{tid}/links", json={"feedback_id": 5})
    assert first.status_code == 201 and second.status_code == 201
    linked = client.get(f"/api/targets/{tid}").json()["linked_feedback"]
    assert {x["assignment_id"] for x in linked} == {"java", "database"}
    assert client.post(f"/api/targets/{tid}/links", json={"feedback_id": 4}).status_code == 409
    assert client.post(f"/api/targets/{tid}/links", json={"feedback_id": 1}).status_code == 403
    assert client.post(f"/api/targets/{tid}/status", json={
        "status": "ACHIEVED", "reason": "Clear independent evidence demonstrated."}).status_code == 200
    achieved = client.get(f"/api/targets/{tid}").json()
    assert achieved["status"] == "ACHIEVED"
    assert achieved["history"][-1]["reason"] == "Clear independent evidence demonstrated."

    as_person(client, "learner-2")
    assert client.get(f"/api/targets/{tid}").json()["status"] == "ACHIEVED"
    assert client.post(f"/api/targets/{tid}/status", json={
        "status": "OPEN", "reason": "Student tries to reopen the target."}).status_code == 403
    assert client.post("/api/targets", json={
        "cohort_id": "computing-26", "learner_id": "learner-2",
        "title": "Something", "guidance": "Not allowed"}).status_code == 403

    as_person(client, "learner-1")
    assert client.get(f"/api/targets/{tid}").status_code == 404
    as_person(client, "tutor-2")
    assert client.get(f"/api/targets/{tid}").status_code == 404

    as_person(client, "tutor-1")
    reopened = client.post(f"/api/targets/{tid}/status", json={
        "status": "OPEN", "reason": "Further evidence is needed on later tasks."})
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "OPEN"
    assert reopened.json()["achieved_at"] is None
    assert len(reopened.json()["history"]) == 2


def test_target_requires_closed_linked_feedback_and_written_tutor_judgement(client):
    as_person(client, "tutor-1")
    # Seed target includes two linked *open* assignments; no auto-completion.
    seeded = client.get("/api/targets").json()[0]
    tid = seeded["id"]
    assert len({x["assignment_id"] for x in seeded["linked_feedback"]}) == 2
    assert seeded["status"] == "OPEN"
    assert client.post(f"/api/targets/{tid}/status", json={
        "status": "ACHIEVED", "reason": "Student has improved."}).status_code == 409
    assert client.post(f"/api/targets/{tid}/status", json={
        "status": "ACHIEVED", "reason": "yes"}).status_code == 422
    # Tutor closes only after learner reaches ready for review.
    as_person(client, "learner-1")
    assert client.post("/api/threads/3/status", json={"status": "CLOSED"}).status_code == 403
    as_person(client, "tutor-1")
    assert client.post("/api/threads/3/status", json={"status": "CLOSED"}).status_code == 200
    reviewed = client.post(f"/api/targets/{tid}/status", json={
        "status": "ACHIEVED", "reason": "Evidence independently demonstrates improvement."})
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "ACHIEVED"


def test_cannot_steal_another_cohort_or_link_unauthorised_feedback(client):
    as_person(client, "tutor-1")
    assert client.post("/api/targets", json={
        "cohort_id": "web-26", "learner_id": "learner-3",
        "title": "Improving documentation", "guidance": "Explain changes clearly."}).status_code == 403
    assert client.post("/api/targets", json={
        "cohort_id": "computing-26", "learner_id": "learner-3",
        "title": "Improving documentation", "guidance": "Explain changes clearly."}).status_code == 403
    as_person(client, "tutor-2")
    allowed = client.post("/api/targets", json={
        "cohort_id": "web-26", "learner_id": "learner-3",
        "title": "Improve accessibility", "guidance": "Test keyboard focus."})
    assert allowed.status_code == 201
    tid = allowed.json()["id"]
    assert client.post(f"/api/targets/{tid}/links", json={"feedback_id": 1}).status_code == 404
    assert client.post(f"/api/targets/{tid}/status", json={
        "status": "ACHIEVED", "reason": "No attached feedback evidence yet."}).status_code == 409
    as_person(client, "admin-1")
    assert client.get(f"/api/targets/{tid}").status_code in (403, 404)
