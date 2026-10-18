from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import settings


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        connect_args = (
            {"check_same_thread": False}
            if url.startswith("sqlite")
            else {"connect_timeout": 3}
        )
        self._engine: Engine = create_engine(
            url, echo=echo, pool_pre_ping=True, connect_args=connect_args
        )
        self._session_factory = sessionmaker(
            bind=self._engine, autoflush=False, expire_on_commit=False
        )

    @property
    def engine(self) -> Engine:
        return self._engine

    def get_session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    def ping(self) -> bool:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def dispose(self) -> None:
        self._engine.dispose()


db = Database(settings.DATABASE_URL)
