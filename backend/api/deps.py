"""Shared FastAPI dependencies for the Parity API.

Currently just authentication (``require_auth``), which every
state-changing router should depend on so a stray unauthenticated
route can't slip through. Keep `GET /api/v1/health*` free of this
dependency — it's the liveness/readiness surface and must stay
reachable without a credential.
"""

import secrets

import structlog
from fastapi import Header, HTTPException

from config import settings

log = structlog.get_logger()

# Emitted once per process, not once per request, so a busy endpoint
# doesn't spam the logs.
_warned_no_token = False


def _extract_token(authorization: str | None, x_api_key: str | None) -> str | None:
    """Pull a bearer credential out of either supported header.

    Accepts ``Authorization: Bearer <token>`` (preferred) or a bare
    ``X-API-Key: <token>`` header.
    """
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value
    if x_api_key:
        return x_api_key
    return None


async def require_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """Require a valid shared API token on the request.

    Reads the credential from ``Authorization: Bearer <token>`` or
    ``X-API-Key: <token>`` and compares it, constant-time
    (``secrets.compare_digest``), against ``settings.parity_api_token``.
    Raises ``HTTPException(401)`` when the token is configured and the
    request's credential is missing or doesn't match.

    Returns a string identifying the authenticated principal. Callers
    that need to record "who did this" (e.g. approving/executing a
    change) should use this return value rather than trusting
    client-supplied request-body fields.

    **Dev fallback, explicit and logged:** if
    ``settings.parity_api_token`` is the empty string (i.e.
    ``PARITY_API_TOKEN`` is unset), auth is disabled — every request is
    allowed through as the ``"anonymous (no-auth-configured)"``
    principal, and a loud warning is logged once at first use. This
    keeps local dev working without a token, but it means auth is
    OFF; any deployment reachable outside localhost MUST set
    ``PARITY_API_TOKEN``.
    """
    global _warned_no_token
    if not settings.parity_api_token:
        if not _warned_no_token:
            log.warning(
                "parity_api_token_not_set",
                detail=(
                    "PARITY_API_TOKEN is empty -- ALL requests are being allowed "
                    "without authentication. Set PARITY_API_TOKEN before exposing "
                    "this API beyond localhost."
                ),
            )
            _warned_no_token = True
        return "anonymous (no-auth-configured)"

    token = _extract_token(authorization, x_api_key)
    if not token or not secrets.compare_digest(token, settings.parity_api_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API credential")

    return "api-token"
