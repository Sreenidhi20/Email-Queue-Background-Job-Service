from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Mailroom"
    DATABASE_URL: str = Field(default="", min_length=1, validate_default=True)
    REDIS_URL: str = "redis://localhost:6379/0"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    RETRY_BASE_SECONDS: int = 10
    RETRY_MAX_SECONDS: int = 600
    MAX_SEND_AHEAD_DAYS: int = Field(default=7, ge=1, le=30)

    @property
    def redis_visibility_timeout_seconds(self) -> int:
        """Must exceed the longest delay we accept, or Redis re-delivers waiting jobs."""
        return (self.MAX_SEND_AHEAD_DAYS + 1) * 24 * 60 * 60


settings = Settings()
