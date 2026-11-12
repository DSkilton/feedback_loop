"""Report reconciliation: permissions, drift, repairs, audit and rollback."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from mvp.api import create_app


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "report-reconciliation.db"
    client = TestClient(create_app(db_url=f"sqlite:///{path}", demo_mode=True))
    return client, path


def as_user(client, user):
    client.headers["X-Demo-User"] = user
    return client


def query(path, sql, args=()):
    with sqlite3.connect(path) as db:
        return db.execute(sql, args).fetchall()


def change(path, sql, args=()):
    with sqlite3.connect(path) as db:
        db.execute(sql, args)


def send_check(client, reason="Periodic data accuracy check"):
    return client.post("/api/reports/reconcile", json={"reason": reason})


def send_repair(client, reason="Rebuild counters after identifying drift"):
    return client.post("/api/reports/reconcile/repair", json={
        "reason": reason, "confirmation": "REBUILD_REPORT_COUNTERS",
    })


def test_admin_check_is_audited_and_read_only(setup):
    client, path = setup
    as_user(client, "admin-1")
    before = client.get("/api/reports").json()
    check = send_check(client)
    assert check.status_code == 200
    body = check.json()
    assert body["action"] == "check"
    assert body["consistent"] is True
    assert body["mismatch_count"] == 0
    assert body["discrepancies"] == []
    assert body["checked_at"]
    assert body["repaired"] is False
    assert client.get("/api/reports").json() == before
    audit = query(path, """
        select actor_id, action, reason, was_consistent, mismatch_count,
               before_hash, after_hash from mvp_report_maintenance_audit
    """)
    assert len(audit) == 1
    assert audit[0][:5] == ("admin-1", "check", "Periodic data accuracy check", 1, 0)
    assert len(audit[0][5]) == 64 and audit[0][5] == audit[0][6]
    assert query(path, "select count(*) from mvp_domain_events") == [(0,)]


def test_detects_missing_metrics_wrong_values_and_extra_keys(setup):
    client, path = setup
    change(path, "update mvp_report_counters set value=95 where key='total'")
    change(path, "delete from mvp_report_counters where key='status:IN_PROGRESS'")
    change(path, "delete from mvp_report_counters where key='focus:Testing'")
    change(path, "insert into mvp_report_counters (key, value) values ('focus:obsolete', 9)")
    as_user(client, "admin-1")
    regular = client.get("/api/reports").json()
    assert regular["total"] == 95
    result = send_check(client).json()
    assert result["consistent"] is False and result["mismatch_count"] == 4
    diffs = {d["metric"]: d for d in result["discrepancies"]}
    assert diffs["total"] == {"metric": "total", "expected": 6, "actual": 95}
    assert diffs["status:IN_PROGRESS"] == {
        "metric": "status:IN_PROGRESS", "expected": 1, "actual": None
    }
    assert diffs["focus:Testing"] == {
        "metric": "focus:Testing", "expected": 1, "actual": None
    }
    assert diffs["focus:obsolete"] == {
        "metric": "focus:obsolete", "expected": None, "actual": 9
    }
    assert "feedback_text" not in str(result)
    assert "learner_id" not in str(result)
    assert "Your Book class" not in str(result)
    assert client.get("/api/reports").json() == regular
    assert query(path, "select was_consistent, mismatch_count from mvp_report_maintenance_audit") == [(0, 4)]


def test_repair_is_separately_authorized_and_requires_confirmation(setup, monkeypatch):
    client, path = setup
    change(path, "update mvp_report_counters set value=40 where key='total'")
    as_user(client, "learner-1")
    assert send_check(client).status_code == 403
    assert send_repair(client).status_code == 403
    as_user(client, "tutor-1")
    assert send_check(client).status_code == 403
    assert send_repair(client).status_code == 403
    as_user(client, "admin-1")
    monkeypatch.delenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", raising=False)
    assert send_repair(client).status_code == 403
    monkeypatch.setenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "other-admin-1")
    assert send_repair(client).status_code == 403
    monkeypatch.setenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "admin-1")
    assert client.post("/api/reports/reconcile/repair", json={"reason": "No confirmation"}).status_code == 422
    assert client.post("/api/reports/reconcile/repair", json={
        "reason": "No confirmation", "confirmation": "YES",
    }).status_code == 422
    assert client.post("/api/reports/reconcile/repair", json={
        "reason": "  ", "confirmation": "REBUILD_REPORT_COUNTERS",
    }).status_code == 422
    assert query(path, "select count(*) from mvp_report_maintenance_audit") == [(0,)]
    assert query(path, "select value from mvp_report_counters where key='total'") == [(40,)]


def test_repair_restores_consistency_and_second_repair_is_noop(setup, monkeypatch):
    client, path = setup
    monkeypatch.setenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "other, admin-1")
    as_user(client, "admin-1")
    expected_report = client.get("/api/reports").json()
    change(path, "update mvp_report_counters set value=17 where key='total'")
    change(path, "delete from mvp_report_counters where key='status:READY_FOR_REVIEW'")
    change(path, "update mvp_report_counters set value=44 where key='focus:Testing'")
    before = send_check(client).json()
    assert before["mismatch_count"] == 3
    fixed = send_repair(client).json()
    assert fixed["action"] == "repair"
    assert fixed["repaired"] is True
    assert fixed["consistent"] is False
    assert fixed["consistent_after"] is True
    assert fixed["mismatch_count"] == 3
    assert client.get("/api/reports").json() == expected_report
    assert send_check(client).json()["consistent"] is True
    noop = send_repair(client, "Scheduled recheck of accurate counters").json()
    assert noop["repaired"] is False
    assert noop["consistent_after"] is True
    assert query(path, "select action, mismatch_count, was_consistent from mvp_report_maintenance_audit order by id") == [
        ("check", 3, 0), ("repair", 3, 0), ("check", 0, 1), ("repair", 0, 1)
    ]
    rows = query(path, "select before_hash, after_hash from mvp_report_maintenance_audit where action='repair' order by id")
    assert rows[0][0] != rows[0][1]
    assert rows[1][0] == rows[1][1]
    assert query(path, "select count(*) from mvp_feedback") == [(6,)]
    assert query(path, "select count(*) from mvp_domain_events") == [(0,)]


def test_missing_totals_and_empty_projection_can_be_reconciled(setup, monkeypatch):
    client, path = setup
    monkeypatch.setenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "admin-1")
    as_user(client, "admin-1")
    change(path, "delete from mvp_report_counters")
    check = send_check(client).json()
    assert check["consistent"] is False
    assert any(row["metric"] == "total" and row["actual"] is None for row in check["discrepancies"])
    assert send_repair(client).json()["consistent_after"] is True
    assert query(path, "select value from mvp_report_counters where key='total'") == [(6,)]


def test_failed_audit_insert_rolls_back_repair(setup, monkeypatch):
    client, path = setup
    monkeypatch.setenv("FEEDBACK_LOOP_REPORT_REPAIR_USERS", "admin-1")
    as_user(client, "admin-1")
    change(path, "update mvp_report_counters set value=22 where key='total'")
    change(path, """create trigger block_report_audit before insert on mvp_report_maintenance_audit
        begin select raise(abort, 'audit storage unavailable'); end""")
    with pytest.raises(Exception, match="audit storage unavailable"):
        send_repair(client)
    # Repair and audit are one transaction; failure must retain the previous counters.
    assert query(path, "select value from mvp_report_counters where key='total'") == [(22,)]
    assert query(path, "select count(*) from mvp_report_maintenance_audit") == [(0,)]


def test_normal_report_does_not_trigger_reconciliation_or_audit(setup):
    client, path = setup
    as_user(client, "admin-1")
    for _ in range(3):
        assert client.get("/api/reports").status_code == 200
    assert query(path, "select count(*) from mvp_report_maintenance_audit") == [(0,)]
