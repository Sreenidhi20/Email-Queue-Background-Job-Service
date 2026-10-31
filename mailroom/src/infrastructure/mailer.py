import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from src.core.config import Settings, settings


class MailerError(Exception):
    """Raised when an email cannot be handed off to the configured mail service."""


class MailSender(Protocol):
    def send(self, to_email: str, subject: str, body: str) -> None: ...


class Mailer:
    """Sends through an SMTP server (Mailpit locally)."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str = "noreply@mailroom.local",
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender

    def send(self, to_email: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            raise MailerError(str(error)) from error


class HttpApiMailer:
    """Sends through Resend's HTTPS API (hosts such as Render's free tier block SMTP)."""

    DEFAULT_URL = "https://api.resend.com/emails"

    def __init__(
        self,
        api_key: str,
        sender: str,
        api_url: str = DEFAULT_URL,
        timeout_seconds: int = 10,
    ) -> None:
        if not api_key:
            raise ValueError("RESEND_API_KEY is required when MAIL_BACKEND=resend")
        self._api_key = api_key
        self._sender = sender
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds

    def send(self, to_email: str, subject: str, body: str) -> None:
        payload = json.dumps(
            {"from": self._sender, "to": [to_email], "subject": subject, "text": body}
        ).encode()
        request = urllib.request.Request(
            self._api_url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "mailroom/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds):
                return
        except urllib.error.HTTPError as error:
            detail = error.read(300).decode(errors="replace")
            raise MailerError(f"Mail API returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, OSError) as error:
            raise MailerError(str(error)) from error


def build_mailer(config: Settings) -> MailSender:
    if config.MAIL_BACKEND == "resend":
        return HttpApiMailer(config.RESEND_API_KEY, config.MAIL_FROM)
    return Mailer(config.SMTP_HOST, config.SMTP_PORT, config.MAIL_FROM)


mailer = build_mailer(settings)
