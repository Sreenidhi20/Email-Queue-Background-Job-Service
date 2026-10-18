import redis

from src.core.config import settings


class RedisClient:
    def __init__(self, url: str) -> None:
        self._client = redis.Redis.from_url(  # type: ignore[reportUnknownMemberType]  # redis-py's from_url kwargs are untyped
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    @property
    def client(self) -> redis.Redis:
        return self._client

    def ping(self) -> bool:
        try:
            return bool(
                self._client.ping()  # type: ignore[reportUnknownMemberType]  # sync Redis ping is boolean
            )
        except redis.RedisError:
            return False

    def close(self) -> None:
        self._client.close()


redis_client = RedisClient(settings.REDIS_URL)
