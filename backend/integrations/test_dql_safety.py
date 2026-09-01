"""Unit tests for the DQL input validators (issue #9).

Stdlib-only (``unittest``) so they run without a test-runner
dependency:

    python -m unittest backend.integrations.test_dql_safety -v

or, from inside ``backend/``:

    python -m unittest integrations.test_dql_safety -v
"""

from __future__ import annotations

import unittest

from dql_safety import (
    DQLValidationError,
    validate_lookback,
    validate_limit,
    validate_sources,
)


class ValidateLookbackTests(unittest.TestCase):
    def test_accepts_valid_relative_windows(self):
        for value in ("-1h", "-24h", "-7d", "-30m", "-2w", "-1m"):
            self.assertEqual(validate_lookback(value), value)

    def test_rejects_injection_payload_with_pipe(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback("-24h | fetch security.events")

    def test_rejects_injection_payload_with_quote(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback('-24h" | fetch security.events, from:-1h')

    def test_rejects_non_string(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback(None)

    def test_rejects_missing_sign(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback("24h")

    def test_rejects_bad_unit(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback("-24x")

    def test_rejects_empty_string(self):
        with self.assertRaises(DQLValidationError):
            validate_lookback("")


class ValidateLimitTests(unittest.TestCase):
    def test_accepts_valid_int(self):
        self.assertEqual(validate_limit(50), 50)

    def test_coerces_numeric_string(self):
        self.assertEqual(validate_limit("50"), 50)

    def test_clamps_to_max(self):
        self.assertEqual(validate_limit(1_000_000), 1000)
        self.assertEqual(validate_limit(1_000_000, max_limit=10), 10)

    def test_rejects_zero_and_negative(self):
        with self.assertRaises(DQLValidationError):
            validate_limit(0)
        with self.assertRaises(DQLValidationError):
            validate_limit(-5)

    def test_rejects_non_numeric(self):
        with self.assertRaises(DQLValidationError):
            validate_limit("50 | fetch security.events")
        with self.assertRaises(DQLValidationError):
            validate_limit(None)


class ValidateSourcesTests(unittest.TestCase):
    def test_accepts_known_sources(self):
        self.assertEqual(
            validate_sources(["parity", "parity-self"]),
            ["parity", "parity-self"],
        )

    def test_empty_or_none_returns_empty_list(self):
        self.assertEqual(validate_sources(None), [])
        self.assertEqual(validate_sources([]), [])

    def test_rejects_unknown_source(self):
        with self.assertRaises(DQLValidationError):
            validate_sources(["parity", "not-a-real-source"])

    def test_rejects_quote_injection_in_source(self):
        with self.assertRaises(DQLValidationError):
            validate_sources(['parity", source == "security.events'])


if __name__ == "__main__":
    unittest.main()
