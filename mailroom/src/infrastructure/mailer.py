import smtplib
from email.message import EmailMessage

from src.core.config import settings


class MailerError(Exception):
    """Raised when an email cannot be handed off to the configured mail server."""


class Mailer:
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


mailer = Mailer(settings.SMTP_HOST, settings.SMTP_PORT)
