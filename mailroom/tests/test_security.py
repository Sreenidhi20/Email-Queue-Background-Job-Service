import asyncio
import json
import unittest

from fastapi import Request

from src.core.errors import ErrorCode, TooManyRequestsError, UnauthorizedError
from src.core.exception_handlers import ExceptionHandlers
from src.core.security import ApiKeyAuth, ApiKeyRegistry

KEY_A = "alpha-key-0123456789"
KEY_B = "beta-key-9876543210:with-colon"


class ApiKeyRegistryTests(unittest.TestCase):
    def test_parses_multiple_clients_and_keeps_colons_in_keys(self) -> None:
        registry = ApiKeyRegistry.parse(f"auth-service:{KEY_A}, chat-app:{KEY_B}")

        self.assertEqual(registry.client_names, ["auth-service", "chat-app"])
        self.assertEqual(registry.client_for(KEY_B), "chat-app")

    def test_unknown_missing_and_empty_keys_are_rejected(self) -> None:
        registry = ApiKeyRegistry.parse(f"a:{KEY_A}")

        self.assertIsNone(registry.client_for("wrong-key-0123456789"))
        self.assertIsNone(registry.client_for(None))
        self.assertIsNone(registry.client_for(""))
        self.assertIsNone(registry.client_for(KEY_A[:-1]))

    def test_empty_string_means_no_keys(self) -> None:
        self.assertEqual(len(ApiKeyRegistry.parse("")), 0)
        self.assertEqual(len(ApiKeyRegistry.parse(" , ")), 0)

    def test_rejects_malformed_short_and_duplicate_entries(self) -> None:
        with self.assertRaises(ValueError):
            ApiKeyRegistry.parse("no-separator")
        with self.assertRaises(ValueError):
            ApiKeyRegistry.parse(":" + KEY_A)
        with self.assertRaises(ValueError):
            ApiKeyRegistry.parse("a:short")
        with self.assertRaises(ValueError):
            ApiKeyRegistry.parse(f"a:{KEY_A},a:{KEY_B}")


class ApiKeyAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = ApiKeyAuth(ApiKeyRegistry.parse(f"auth-service:{KEY_A}"))

    def test_valid_key_returns_client_name(self) -> None:
        self.assertEqual(self.auth(KEY_A), "auth-service")

    def test_missing_or_wrong_key_raises_401(self) -> None:
        for presented in (None, "nope-nope-nope-nope"):
            with self.assertRaises(UnauthorizedError) as raised:
                self.auth(presented)
            self.assertEqual(raised.exception.status_code, 401)
            self.assertEqual(raised.exception.code, ErrorCode.INVALID_API_KEY)

    def test_startup_check_fails_when_required_but_no_keys(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "API_KEYS is empty"):
            ApiKeyAuth(ApiKeyRegistry.parse(""), required=True).assert_configured()

    def test_startup_check_allows_open_mode_only_when_explicitly_disabled(self) -> None:
        open_auth = ApiKeyAuth(ApiKeyRegistry.parse(""), required=False)

        open_auth.assert_configured()
        self.assertEqual(open_auth(None), ApiKeyAuth.ANONYMOUS)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


class ErrorHeadersTests(unittest.TestCase):
    def test_rate_limit_error_sends_retry_after_header_and_envelope(self) -> None:
        error = TooManyRequestsError(17, "Limit is 5 requests per minute per API key")

        response = asyncio.run(ExceptionHandlers._on_app_error(_request(), error))
        body = json.loads(bytes(response.body))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "17")
        self.assertFalse(body["isSuccess"])
        self.assertEqual(body["error"], "Too many requests")
        self.assertIn("5 requests per minute", body["detail"])

    def test_unauthorized_error_sends_www_authenticate_header(self) -> None:
        error = UnauthorizedError(ErrorCode.INVALID_API_KEY)

        response = asyncio.run(ExceptionHandlers._on_app_error(_request(), error))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "ApiKey")


if __name__ == "__main__":
    unittest.main()
