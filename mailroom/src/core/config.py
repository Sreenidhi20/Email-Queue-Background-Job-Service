from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Mailroom"
    DATABASE_URL: str = Field(default="", min_length=1, validate_default=True)
    REDIS_URL: str = "redis://localhost:6379/0"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025


settings = Settings()
