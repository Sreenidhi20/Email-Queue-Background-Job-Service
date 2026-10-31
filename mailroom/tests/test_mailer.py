import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.core.config import Settings
from src.infrastructure.mailer import (
    HttpApiMailer,
    Mailer,
    MailerError,
    build_mailer,
)


class MailApiHandler(BaseHTTPRequestHandler):
    received: list[dict[str, object]] = []
    status = 200

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        MailApiHandler.received.append(
            {
                "path": self.path,
                "auth": self.headers["Authorization"],
                "content_type": self.headers["Content-Type"],
                "user_agent": self.headers["User-Agent"],
                "body": json.loads(self.rfile.read(length)),
            }
        )
        self.send_response(MailApiHandler.status)
        self.end_headers()
        self.wfile.write(b'{"message":"nope"}' if MailApiHandler.status >= 400 else b"{}")

    def log_message(self, *_args: object) -> None:
        return


class HttpApiMailerTests(unittest.TestCase):
    def setUp(self) -> None:
        MailApiHandler.received = []
        MailApiHandler.status = 200
        self.server = HTTPServer(("127.0.0.1", 0), MailApiHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/emails"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_posts_expected_request_to_the_mail_api(self) -> None:
        mailer = HttpApiMailer("re_test_key", "Mailroom <a@b.com>", self.url)

        mailer.send("to@example.com", "Hello", "Body text")

        sent = MailApiHandler.received[0]
        self.assertEqual(sent["auth"], "Bearer re_test_key")
        self.assertEqual(sent["content_type"], "application/json")
        self.assertEqual(sent["user_agent"], "mailroom/1.0")
        self.assertEqual(
            sent["body"],
            {
                "from": "Mailroom <a@b.com>",
                "to": ["to@example.com"],
                "subject": "Hello",
                "text": "Body text",
            },
        )

    def test_http_error_becomes_mailer_error_without_leaking_the_key(self) -> None:
        MailApiHandler.status = 422
        mailer = HttpApiMailer("re_secret_key", "a@b.com", self.url)

        with self.assertRaises(MailerError) as raised:
            mailer.send("to@example.com", "Hi", "Body")

        self.assertIn("HTTP 422", str(raised.exception))
        self.assertNotIn("re_secret_key", str(raised.exception))

    def test_unreachable_api_becomes_mailer_error(self) -> None:
        mailer = HttpApiMailer("re_key", "a@b.com", "http://127.0.0.1:1/emails")

        with self.assertRaises(MailerError):
            mailer.send("to@example.com", "Hi", "Body")

    def test_requires_an_api_key(self) -> None:
        with self.assertRaises(ValueError):
            HttpApiMailer("", "a@b.com")


class BuildMailerTests(unittest.TestCase):
    def test_default_backend_is_smtp(self) -> None:
        config = Settings(DATABASE_URL="sqlite://")

        self.assertIsInstance(build_mailer(config), Mailer)

    def test_resend_backend_builds_the_http_mailer(self) -> None:
        config = Settings(
            DATABASE_URL="sqlite://", MAIL_BACKEND="resend", RESEND_API_KEY="re_x"
        )

        self.assertIsInstance(build_mailer(config), HttpApiMailer)

    def test_resend_backend_without_key_fails_at_startup(self) -> None:
        config = Settings(DATABASE_URL="sqlite://", MAIL_BACKEND="resend")

        with self.assertRaises(ValueError):
            build_mailer(config)


if __name__ == "__main__":
    unittest.main()
