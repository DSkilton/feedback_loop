"""Roster preview, authorisation, validation and atomic import contracts."""
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from mvp.api import Cohort, Enrollment, User, create_app
from mvp.rosters import COLUMNS


@pytest.fixture
def workspace(tmp_path):
    url = f"sqlite:///{tmp_path / 'roster.db'}"
    client = TestClient(create_app(db_url=url, demo_mode=True))
    client.headers["X-Demo-User"] = "admin-1"
    return client, create_engine(url)


def csv_file(*rows):
    return (",".join(COLUMNS) + "\n" + "\n".join(rows)).encode()


def upload(client, data, name="roster.csv", digest=""):
    return client.post("/api/organisation/rosters", files={"file": (name, data)}, data={"expected_sha256": digest})


def test_preview_is_read_only_and_commit_is_additive_idempotent(workspace):
    client, engine = workspace
    data = csv_file("computing,new-class,New class,2026/27,00045,New Learner,learner",
                    "computing,new-class,New class,2026/27,tutor-2,Sam Patel,tutor")
    preview = upload(client, data).json()
    assert preview["valid"] and not preview["imported"]
    assert preview["new_cohorts"] == 1 and preview["new_learners"] == 1 and preview["new_memberships"] == 2
    with Session(engine) as db:
        assert db.get(User, "00045") is None
        assert db.get(Cohort, "new-class") is None
    committed = upload(client, data, digest=preview["sha256"]).json()
    assert committed["imported"]
    second = upload(client, data, digest=preview["sha256"]).json()
    assert second["imported"] and second["new_memberships"] == 0 and second["unchanged"] == 2
    with Session(engine) as db:
        assert db.get(User, "00045").role == "learner"
        assert len(db.scalars(select(Enrollment).where(Enrollment.cohort_id == "new-class")).all()) == 2
        assert db.get(User, "learner-1") is not None
    client.headers["X-Demo-User"] = "tutor-2"
    assert "new-class" in {c["id"] for c in client.get("/api/bootstrap").json()["cohorts"]}


def test_conflicts_are_reported_and_prevent_partial_import(workspace):
    client, engine = workspace
    data = csv_file("computing,new-class,New class,2026/27,new-learner,New Learner,learner",
                    "computing,new-class,New class,2026/27,learner-1,Other Name,learner",
                    "computing,new-class,New class,2026/27,new-tutor,New Tutor,tutor")
    preview = upload(client, data).json()
    assert not preview["valid"] and preview["error_count"] == 2
    result = upload(client, data, digest=preview["sha256"]).json()
    assert not result["imported"]
    with Session(engine) as db:
        assert db.get(User, "new-learner") is None
        assert db.get(Cohort, "new-class") is None


def test_duplicate_rows_and_changed_preview_are_rejected(workspace):
    client, _ = workspace
    row = "computing,new-class,New class,2026/27,new-learner,New Learner,learner"
    preview = upload(client, csv_file(row, row)).json()
    assert not preview["valid"] and preview["error_count"] == 1
    assert upload(client, csv_file(row), digest=preview["sha256"]).status_code == 409


def workbook_data(*rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(COLUMNS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_xlsx_text_ids_preserved_and_formulas_rejected(workspace):
    client, _ = workspace
    row = ("computing", "new-class", "New class", "2026/27", "00045", "New Learner", "learner")
    preview = upload(client, workbook_data(row), "roster.xlsx").json()
    assert preview["valid"] and preview["preview"][0]["user_id"] == "00045"
    numeric = (*row[:4], 45, *row[5:])
    assert not upload(client, workbook_data(numeric), "roster.xlsx").json()["valid"]
    formula = (*row[:5], "=1+1", row[6])
    assert upload(client, workbook_data(formula), "roster.xlsx").status_code == 422


def test_import_is_admin_only_and_invalid_formats_fail_closed(workspace):
    client, _ = workspace
    assert upload(client, b"not a roster").status_code == 422
    assert upload(client, b"not a workbook", "roster.xlsx").status_code == 422
    assert upload(client, b"bad", "roster.xlsm").status_code == 422
    client.headers["X-Demo-User"] = "tutor-1"
    assert upload(client, csv_file("computing,new-class,New class,2026/27,new-learner,New Learner,learner")).status_code == 403
