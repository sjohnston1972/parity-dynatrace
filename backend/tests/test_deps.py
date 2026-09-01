"""Unit tests for backend/api/deps.py::require_auth.

Run from backend/: ``pytest tests/test_deps.py -v``

Written to be runnable without pytest-asyncio (uses asyncio.run
directly), since the project doesn't otherwise depend on it.
"""

import asyncio

import pytest
from fastapi import HTTPException

from api import deps
from config import settings


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_warned_flag():
    """require_auth only warns once per process; reset between tests."""
    deps._warned_no_token = False
    yield
    deps._warned_no_token = False


@pytest.fixture
def token_configured():
    original = settings.parity_api_token
    settings.parity_api_token = "s3cret-token"
    yield "s3cret-token"
    settings.parity_api_token = original


def test_valid_bearer_token_allowed(token_configured):
    principal = _run(deps.require_auth(authorization=f"Bearer {token_configured}", x_api_key=None))
    assert principal == "api-token"


def test_valid_x_api_key_allowed(token_configured):
    principal = _run(deps.require_auth(authorization=None, x_api_key=token_configured))
    assert principal == "api-token"


def test_missing_credential_rejected(token_configured):
    with pytest.raises(HTTPException) as exc_info:
        _run(deps.require_auth(authorization=None, x_api_key=None))
    assert exc_info.value.status_code == 401


def test_wrong_bearer_token_rejected(token_configured):
    with pytest.raises(HTTPException) as exc_info:
        _run(deps.require_auth(authorization="Bearer wrong-token", x_api_key=None))
    assert exc_info.value.status_code == 401


def test_wrong_x_api_key_rejected(token_configured):
    with pytest.raises(HTTPException) as exc_info:
        _run(deps.require_auth(authorization=None, x_api_key="wrong-token"))
    assert exc_info.value.status_code == 401


def test_malformed_authorization_header_rejected(token_configured):
    """A non-Bearer scheme (or bare token with no scheme) must not be
    treated as a credential."""
    with pytest.raises(HTTPException) as exc_info:
        _run(deps.require_auth(authorization=token_configured, x_api_key=None))
    assert exc_info.value.status_code == 401


def test_no_token_configured_allows_and_warns():
    """Explicit dev fallback: empty settings.parity_api_token means
    auth is disabled and every request is allowed through."""
    original = settings.parity_api_token
    settings.parity_api_token = ""
    try:
        principal = _run(deps.require_auth(authorization=None, x_api_key=None))
        assert principal == "anonymous (no-auth-configured)"
        assert deps._warned_no_token is True
    finally:
        settings.parity_api_token = original
