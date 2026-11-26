"""Scope and configuration regression tests (synthetic data only)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mvp.api import Assignment, Cohort, CohortAssignment, Course, Enrollment, Feedback, User, create_app
from mvp.organisation import OrganisationChange


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite:///{tmp_path / 'organisation.db'}"
    app = create_app(db_url=url, demo_mode=True)
    engine = create_engine(url)
    client = TestClient(app)
    client.headers["X-Demo-User"] = "admin-1"
    with Session(engine) as db:
        db.add_all([
            User(id="media-tutor", name="Media Tutor", role="tutor"),
            User(id="game-tutor", name="Games Tutor", role="tutor"),
            Course(id="shared", title="Level 2 Games and Media"),
            Course(id="media", title="Media"),
        ])
        db.flush()
        db.add_all([
            Cohort(id="shared-26", course_id="shared", name="Shared class", academic_year="2026/27"),
            Cohort(id="media-26", course_id="media", name="Media class", academic_year="2026/27"),
            Cohort(id="shared-27", course_id="shared", name="Next year", academic_year="2027/28"),
        ])
        db.flush()
        for cohort in ("shared-26", "media-26", "shared-27"):
            db.add(Enrollment(cohort_id=cohort, user_id="learner-3", member_role="learner"))
            db.add(CohortAssignment(cohort_id=cohort, assignment_id="web"))
            db.add(Feedback(assignment_id="web", cohort_id=cohort, learner_id="learner-3",
                            tutor_id="media-tutor", feedback_text="Teacher feedback", teams_reference="Demo"))
        db.commit()
    assert client.post("/api/organisation/faculties", json={"id": "digital", "title": "Digital"}).status_code == 201
    for name in ("computing", "games", "media"):
        assert client.post("/api/organisation/departments", json={"id": name, "title": name.title(), "faculty_id": "digital"}).status_code == 201
    for course, departments in (("computing", ["computing"]), ("shared", ["games", "media"]), ("media", ["media"])):
        assert client.put(f"/api/organisation/courses/{course}/departments/2026/27", json={"department_ids": departments}).status_code == 200
    return client, engine


def allocate(client, staff, **kwargs):
    client.headers["X-Demo-User"] = "admin-1"
    return client.put(f"/api/organisation/staff/{staff}/allocations/2026/27", json=kwargs)


def scope(client, staff):
    client.headers["X-Demo-User"] = staff
    result = client.get("/api/oversight")
    assert result.status_code == 200, result.text
    return result.json()


def test_shared_course_department_leads_and_lecturers_have_scoped_read_only_access(setup):
    client, _ = setup
    assert allocate(client, "game-tutor", programme_lead_department_ids=["games"]).status_code == 200
    result = scope(client, "game-tutor")
    assert {c["id"] for c in result["cohorts"]} == {"shared-26"}
    assert len(result["feedback"]) == 1
    fid = result["feedback"][0]["id"]
    assert client.get(f"/api/oversight/feedback/{fid}").json()["read_only"]
    assert client.post(f"/api/threads/{fid}/comments", json={"body": "Cannot impersonate"}).status_code == 404
    assert client.post(f"/api/threads/{fid}/status", json={"status": "CLOSED", "expected_version": 1}).status_code == 404
    assert client.get("/api/reports").status_code == 403
    assert allocate(client, "media-tutor", curriculum_team_lead_department_ids=["media"], lecturer_department_ids=["games", "media"]).status_code == 200
    result = scope(client, "media-tutor")
    assert {c["id"] for c in result["cohorts"]} == {"shared-26", "media-26"}
    assert len(result["feedback"]) == 2
    assert allocate(client, "tutor-1", lecturer_department_ids=["computing", "games"]).status_code == 200
    assert {c["id"] for c in scope(client, "tutor-1")["cohorts"]} == {"computing-26", "web-26", "shared-26"}


def test_one_iv_per_course_year_and_iv_can_cover_multiple_courses(setup):
    client, engine = setup
    assert allocate(client, "tutor-2", iv_course_ids=["shared", "media"]).status_code == 200
    assert allocate(client, "tutor-1", iv_course_ids=["shared"]).status_code == 409
    assert {c["id"] for c in scope(client, "tutor-2")["cohorts"]} == {"shared-26", "media-26"}
    assert allocate(client, "tutor-2", iv_course_ids=["shared", "media"]).status_code == 200
    assert allocate(client, "tutor-2", iv_course_ids=["media"]).status_code == 200
    assert {c["id"] for c in scope(client, "tutor-2")["cohorts"]} == {"media-26"}
    assert allocate(client, "tutor-1", iv_course_ids=["shared"]).status_code == 200
    with Session(engine) as db:
        assert db.scalars(select(OrganisationChange).where(OrganisationChange.action == "staff_allocations_changed")).all()


def test_quality_global_oversight_but_learner_and_unallocated_tutor_cannot_read_or_configure(setup):
    client, _ = setup
    quality = scope(client, "admin-1")
    assert len(quality["cohorts"]) == 5
    assert len(quality["feedback"]) == 9
    assert client.get("/api/oversight/feedback/1").status_code == 200
    assert client.post("/api/threads/1/comments", json={"body": "No"}).status_code == 403
    for user in ("learner-1", "tutor-1"):
        client.headers["X-Demo-User"] = user
        assert client.get("/api/oversight").status_code == 403
        assert client.get("/api/oversight/feedback/1").status_code == 403
        assert client.get("/api/organisation?academic_year=2026/27").status_code == 403
        assert client.put("/api/organisation/staff/tutor-1/allocations/2026/27", json={"lecturer_department_ids": ["computing"]}).status_code == 403
    assert allocate(client, "game-tutor", lecturer_department_ids=["games"]).status_code == 200
    scope(client, "game-tutor")
    assert client.get("/api/oversight/feedback/1").status_code == 404
    assert client.get("/api/threads/1").status_code == 404


def test_config_validation_and_production_management_opt_in(setup, monkeypatch):
    client, _ = setup
    assert allocate(client, "learner-1", iv_course_ids=["shared"]).status_code == 404
    assert allocate(client, "tutor-1", lecturer_department_ids=["unknown"]).status_code == 422
    assert client.put("/api/organisation/courses/shared/departments/2026/29", json={"department_ids": ["games"]}).status_code == 422
    assert client.put("/api/organisation/courses/shared/departments/2026/27", json={"department_ids": ["unknown"]}).status_code == 422
    from types import SimpleNamespace
    from mvp.organisation import can_manage_organisation
    account = SimpleNamespace(id="admin-1", role="admin")
    monkeypatch.delenv("FEEDBACK_LOOP_ORGANISATION_ADMIN_USERS", raising=False)
    assert not can_manage_organisation(account, False)
    monkeypatch.setenv("FEEDBACK_LOOP_ORGANISATION_ADMIN_USERS", "admin-1")
    assert can_manage_organisation(account, False)
