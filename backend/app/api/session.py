"""Anonymous-session ownership without storing or logging the bearer token."""

from __future__ import annotations

import hashlib
import re
import secrets

from fastapi import Header, Request, Response

from app.services.imported_results import DEFAULT_OWNER_ID

SESSION_HEADER = "X-Analysis-Session"
SESSION_COOKIE = "llps_analysis_session"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def analysis_owner(
    request: Request,
    response: Response,
    header_token: str | None = Header(default=None, alias=SESSION_HEADER),
) -> str:
    """Return a non-secret owner key and issue a safe token when absent/invalid."""
    cookie_token = request.cookies.get(SESSION_COOKIE)
    token = header_token if header_token and _TOKEN.fullmatch(header_token) else cookie_token
    if token is None or _TOKEN.fullmatch(token) is None:
        token = _new_token()
    settings = getattr(request.app.state, "settings", None)
    retention_days = getattr(settings, "analysis_retention_days", 7)
    public_https = getattr(settings, "public_https", False)
    configured_secure = getattr(settings, "session_cookie_secure", None)
    secure = public_https if configured_secure is None else configured_secure
    same_site = getattr(settings, "session_cookie_samesite", "lax")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=retention_days * 86400,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )
    if getattr(settings, "dev_disable_job_ownership", False):
        return DEFAULT_OWNER_ID
    return hashlib.sha256(token.encode("ascii")).hexdigest()
