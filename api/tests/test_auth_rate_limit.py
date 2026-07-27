import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.auth.rate_limit import (
    ensure_login_allowed,
    record_login_failure,
)
from app.config import settings


class LoginRateLimitTest(unittest.TestCase):
    def test_blocks_an_account_after_the_configured_attempts(self) -> None:
        connection = Mock()
        connection.mget.return_value = [
            str(settings.login_rate_limit_attempts),
            "0",
        ]
        with (
            patch.object(settings, "login_rate_limit_enabled", True),
            patch("app.auth.rate_limit._connection", return_value=connection),
            self.assertRaises(HTTPException) as raised,
        ):
            ensure_login_allowed("agent@example.com", "203.0.113.10")
        self.assertEqual(raised.exception.status_code, 429)
        connection.close.assert_called_once()

    def test_records_account_and_ip_failures_with_expiration(self) -> None:
        connection = Mock()
        pipeline = connection.pipeline.return_value
        with (
            patch.object(settings, "login_rate_limit_enabled", True),
            patch("app.auth.rate_limit._connection", return_value=connection),
        ):
            record_login_failure("agent@example.com", "203.0.113.10")
        self.assertEqual(pipeline.incr.call_count, 2)
        self.assertEqual(pipeline.expire.call_count, 2)
        pipeline.execute.assert_called_once()
        connection.close.assert_called_once()
