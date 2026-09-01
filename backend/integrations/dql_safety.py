"""Shared validation for user-influenced Grail DQL query fragments.

Every DQL string in this codebase is built by f-string interpolation
(see ``routes.dynatrace.dynatrace_davis_problems`` and
``DynatraceWriter.query_parity_events``). None of the values that
flow into those f-strings may ever be trusted as-is — a caller who
controls ``lookback``, ``limit``, or ``sources`` could otherwise close
the intended clause and append an arbitrary ``fetch``/``filter``
against any other Grail bucket the platform token can read.

These helpers are the single point every call site routes through:
reject anything that doesn't match a strict allowlist rather than
trying to escape or sanitize free-form input.
"""

from __future__ import annotations

import re

# Relative Grail time token: a leading "-", 1-4 digits, then a single
# m(inute)/h(our)/d(ay)/w(eek) unit. Matches what any caller legitimately
# sends (``-1h``, ``-24h``, ``-7d``, ...) and nothing else — in
# particular, no whitespace or pipe characters can sneak through.
_LOOKBACK_RE = re.compile(r"^-\d{1,4}[mhdw]$")

# Grail `source` values Parity itself ever emits or queries for.
KNOWN_SOURCES = {"parity", "parity-self", "parity-capability-probe"}

DEFAULT_MAX_LIMIT = 1000


class DQLValidationError(ValueError):
    """Raised when a caller-supplied value can't be safely used in DQL."""


def validate_lookback(lookback: str) -> str:
    """Validate a relative-time token like ``-24h``.

    Raises ``DQLValidationError`` for anything else, including a
    payload that tries to break out of the clause (e.g.
    ``-24h | fetch security.events``).
    """
    if not isinstance(lookback, str) or not _LOOKBACK_RE.match(lookback):
        raise DQLValidationError(
            f"invalid lookback {lookback!r}; expected a relative time "
            "token such as -24h, -7d, -30m"
        )
    return lookback


def validate_limit(limit, max_limit: int = DEFAULT_MAX_LIMIT) -> int:
    """Coerce ``limit`` to a positive int, clamped to ``max_limit``."""
    try:
        # Reject bools (int subclass) and floats-as-strings like "1.5"
        # by requiring the coercion to round-trip cleanly.
        value = int(str(limit))
    except (TypeError, ValueError):
        raise DQLValidationError(f"invalid limit {limit!r}; expected an integer")
    if value <= 0:
        raise DQLValidationError(f"invalid limit {limit!r}; must be positive")
    return min(value, max_limit)


def validate_sources(sources, allowed: set[str] = KNOWN_SOURCES) -> list[str]:
    """Validate a list of Grail ``source`` values against an allowlist.

    Values are already double-quoted before use in DQL, but we
    validate rather than trust them so an unexpected value can't
    smuggle a `"` or other DQL-meaningful character through.
    """
    if not sources:
        return []
    bad = [s for s in sources if s not in allowed]
    if bad:
        raise DQLValidationError(
            f"unknown source(s) {bad!r}; expected one of {sorted(allowed)}"
        )
    return list(sources)
