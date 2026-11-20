"""Microsoft Entra OIDC adapter.

Off by default. No self-registration, no implicit learner/staff role assignment.
Tenant, app roles, and a College-approved identity mapping are all required.

This adapter is not sufficient on its own for production use: College tenant
configuration, managed HTTPS hosting, roster verification, retention and a
safeguarding/DPIA review are still explicit release gates.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

ROLE_CLAIMS = {
    "learner": "Feedback.Learner",
    "tutor": "Feedback.Tutor",
    "admin": "Feedback.Quality",
}


@dataclass(frozen=True)
class EntraConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    allowlist: dict[str, dict]

    @classmethod
    def from_env(cls) -> "EntraConfig":
        tenant = str(UUID(os.environ["FEEDBACK_LOOP_ENTRA_TENANT_ID"]))
        client = str(UUID(os.environ["FEEDBACK_LOOP_ENTRA_CLIENT_ID"]))
        redirect = os.environ["FEEDBACK_LOOP_ENTRA_REDIRECT_URI"]
        secret = os.environ["FEEDBACK_LOOP_ENTRA_CLIENT_SECRET"]
        cookie_secret = os.environ["FEEDBACK_LOOP_SESSION_SECRET"]
        allowlist_path = Path(os.environ["FEEDBACK_LOOP_ENTRA_ALLOWLIST_PATH"])
        parsed = urlsplit(redirect)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path != "/auth/callback" or parsed.query or parsed.fragment:
            raise ValueError("Entra redirect must be an explicit https://.../auth/callback URL.")
        if len(cookie_secret) < 32 or len(secret) < 12:
            raise ValueError("Secure OIDC client and cookie secrets must be configured.")
        mapping = json.loads(allowlist_path.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            raise ValueError("Approved identity mapping must be a JSON object.")
        for oid, value in mapping.items():
            if str(UUID(oid)) != oid.lower() or not isinstance(value, dict):
                raise ValueError("Identity mapping keys must be canonical object IDs.")
            if value.get("role") not in ROLE_CLAIMS or not isinstance(value.get("user_id"), str):
                raise ValueError("Each approved identity needs a local user ID and valid role.")
        return cls(tenant, client, secret, redirect, cookie_secret, mapping)


def approved_identity(claims: dict, config: EntraConfig) -> dict:
    """Return the pre-approved local identity for *validated ID-token claims*.

    Never call this on an unverified token. Authlib's OIDC exchange must
    validate signature, nonce, state, audience and expiry before this step.
    """
    expected_issuer = f"https://login.microsoftonline.com/{config.tenant_id}/v2.0"
    if claims.get("tid") != config.tenant_id or claims.get("iss") != expected_issuer:
        raise ValueError("Incorrect College tenant.")
    if claims.get("aud") != config.client_id:
        raise ValueError("Incorrect app audience.")
    try:
        oid = str(UUID(str(claims["oid"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("A valid Microsoft object identifier is required.") from exc
    entry = config.allowlist.get(oid)
    if not entry:
        raise ValueError("Account is not enrolled in the College pilot.")
    roles = claims.get("roles", [])
    if not isinstance(roles, list) or ROLE_CLAIMS[entry["role"]] not in roles:
        raise ValueError("Required Microsoft Entra application role is missing.")
    return {"oid": oid, "user_id": entry["user_id"], "role": entry["role"]}


def session_identity(request: Request, config: EntraConfig) -> dict | None:
    """Recheck the approved mapping on every request.

    Signed session cookies are not an authorization database: the server also
    checks the current user and role against its own records.
    """
    session = request.session
    oid = session.get("oid")
    entry = config.allowlist.get(oid) if isinstance(oid, str) else None
    if not entry or session.get("user_id") != entry["user_id"] or session.get("role") != entry["role"]:
        return None
    return entry


def verify_csrf(request: Request) -> None:
    expected = request.session.get("csrf")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not isinstance(expected, str) or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Missing or invalid request token.")


def configure_entra_routes(app: FastAPI, config: EntraConfig) -> None:
    """Register validated OIDC login/logout and HTTPS-only signed sessions."""
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="college",
        client_id=config.client_id,
        client_secret=config.client_secret,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{config.tenant_id}/v2.0/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"},
    )
    app.add_middleware(
        SessionMiddleware, secret_key=config.session_secret,
        session_cookie="feedback_loop_session",
        same_site="lax", https_only=True, max_age=8 * 60 * 60,
    )

    @app.get("/auth/login")
    async def login(request: Request):
        request.session.clear()
        return await oauth.college.authorize_redirect(request, config.redirect_uri)

    @app.get("/auth/callback")
    async def callback(request: Request):
        try:
            token = await oauth.college.authorize_access_token(request)
            # Authlib validates ID token (including issuer/nonce/signature/time)
            # and exposes the verified claims as userinfo when openid is used.
            claims = token.get("userinfo")
            if claims is None:
                raise ValueError("Verified OIDC identity token missing.")
            identity = approved_identity(dict(claims), config)
        except Exception:
            request.session.clear()
            raise HTTPException(403, "Sign-in could not be approved.") from None

        # Discard OAuth access and refresh tokens; this application currently
        # does not call Graph. Retain only the minimum approved identity.
        request.session.clear()
        request.session.update(identity)
        request.session["csrf"] = secrets.token_urlsafe(32)
        return RedirectResponse("/", status_code=303)

    @app.post("/auth/logout")
    async def logout(request: Request):
        verify_csrf(request)
        request.session.clear()
        return {"success": True}
