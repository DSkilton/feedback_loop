"""Entra mapping policy tests: no Microsoft tenant or secrets are needed."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from mvp.api import create_app
from mvp.entra import EntraConfig, approved_identity

TENANT = "11111111-1111-4111-8111-111111111111"
CLIENT = "22222222-2222-4222-8222-222222222222"
OID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def config():
    return EntraConfig(
        tenant_id=TENANT, client_id=CLIENT, client_secret="test-only-not-a-real-secret",
        redirect_uri="https://example.edu/auth/callback",
        session_secret="test-only-not-a-real-secret-longer-than-32",
        allowlist={OID: {"user_id": "tutor-1", "role": "tutor"}},
    )


def claims(**changes):
    data = {
        "aud": CLIENT, "tid": TENANT, "oid": OID,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "roles": ["Feedback.Tutor"],
    }
    data.update(changes)
    return data


def test_approved_entra_identity_requires_exact_tenant_role_app_and_allowlist(config):
    approved = approved_identity(claims(), config)
    assert approved == {"oid": OID, "user_id": "tutor-1", "role": "tutor"}
    for wrong in (
        claims(tid="ffffffff-ffff-4fff-8fff-ffffffffffff"),
        claims(iss="https://login.microsoftonline.com/common/v2.0"),
        claims(aud="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        claims(roles=["Feedback.Learner"]),
        claims(roles=[]),
        claims(oid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        claims(oid="not-a-guid"),
    ):
        with pytest.raises(ValueError):
            approved_identity(wrong, config)


def test_enrollment_role_cannot_be_elevated_by_token(config):
    impostor = replace(config, allowlist={OID: {"user_id": "tutor-1", "role": "learner"}})
    with pytest.raises(ValueError):
        approved_identity(claims(), impostor)


def test_non_demo_mode_rejects_spoofed_demo_header(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path / 'noauth.db'}", demo_mode=False, auth_mode="disabled")
    client = TestClient(app)
    assert client.get("/api/auth-mode").json()["mode"] == "disabled"
    assert client.get("/api/threads", headers={"X-Demo-User": "tutor-1"}).status_code == 403
    assert client.post("/api/threads/1/status", headers={"X-Demo-User": "tutor-1"},
                       json={"status": "CLOSED"}).status_code == 403
