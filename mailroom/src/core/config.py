from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Mailroom"
    DATABASE_URL: str = Field(default="", min_length=1, validate_default=True)
    REDIS_URL: str = "redis://localhost:6379/0"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    MAIL_BACKEND: Literal["smtp", "resend"] = "smtp"
    MAIL_FROM: str = "noreply@mailroom.local"
    RESEND_API_KEY: str = ""
    # "name:key,name2:key2". Each key must be at least 16 characters.
    API_KEYS: str = ""
    REQUIRE_API_KEY: bool = True
    RATE_LIMIT_PER_MINUTE: int = Field(default=60, ge=1, le=100_000)
    RETRY_BASE_SECONDS: int = 10
    RETRY_MAX_SECONDS: int = 600
    MAX_SEND_AHEAD_DAYS: int = Field(default=7, ge=1, le=30)
    FLOWER_USER: str = ""
    FLOWER_PASSWORD: str = ""
    FLOWER_PORT: int = Field(default=5555, ge=1024, le=65535)
    SENT_RETENTION_DAYS: int = Field(default=30, ge=1, le=365)
    DIGEST_TO_EMAIL: str | None = None
    # Beat runs in UTC. 21:30 UTC = 03:00 IST, 02:30 UTC = 08:00 IST.
    CLEANUP_HOUR_UTC: int = Field(default=21, ge=0, le=23)
    CLEANUP_MINUTE_UTC: int = Field(default=30, ge=0, le=59)
    DIGEST_HOUR_UTC: int = Field(default=2, ge=0, le=23)
    DIGEST_MINUTE_UTC: int = Field(default=30, ge=0, le=59)

    @property
    def redis_visibility_timeout_seconds(self) -> int:
        """Must exceed the longest delay we accept, or Redis re-delivers waiting jobs."""
        return (self.MAX_SEND_AHEAD_DAYS + 1) * 24 * 60 * 60


settings = Settings()
