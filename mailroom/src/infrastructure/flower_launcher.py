from src.core.config import settings
from src.infrastructure.celery_app import celery_app


class FlowerLauncher:
    """Starts Flower only when dashboard authentication is configured."""

    MIN_PASSWORD_LENGTH = 8

    def __init__(
        self,
        user: str,
        password: str,
        port: int = 5555,
        db_path: str = "flower.db",
        max_tasks: int = 5000,
    ) -> None:
        self._user = self._validated_user(user)
        self._password = self._validated_password(password)
        if not 1024 <= port <= 65535:
            raise ValueError("FLOWER_PORT must be between 1024 and 65535")
        self._port = port
        self._db_path = db_path
        self._max_tasks = max_tasks

    @classmethod
    def from_settings(cls) -> "FlowerLauncher":
        return cls(settings.FLOWER_USER, settings.FLOWER_PASSWORD, settings.FLOWER_PORT)

    @property
    def port(self) -> int:
        return self._port

    def build_args(self) -> list[str]:
        return [
            "flower",
            f"--port={self._port}",
            f"--basic-auth={self._user}:{self._password}",
            "--persistent=True",
            f"--db={self._db_path}",
            f"--max_tasks={self._max_tasks}",
        ]

    def start(self) -> None:
        celery_app.start(self.build_args())  # type: ignore[reportUnknownMemberType]

    @staticmethod
    def _validated_user(user: str) -> str:
        if not user or ":" in user or "," in user:
            raise ValueError("FLOWER_USER must be set and must not contain ':' or ','")
        return user

    @classmethod
    def _validated_password(cls, password: str) -> str:
        if len(password) < cls.MIN_PASSWORD_LENGTH or "," in password:
            raise ValueError(
                f"FLOWER_PASSWORD must be at least {cls.MIN_PASSWORD_LENGTH} "
                "characters and must not contain ','"
            )
        return password


def main() -> None:
    try:
        launcher = FlowerLauncher.from_settings()
    except ValueError as error:
        raise SystemExit(f"Flower not started: {error}") from error
    launcher.start()


if __name__ == "__main__":
    main()
