import hmac

from fastapi import Header

from src.core.config import settings
from src.core.errors import ErrorCode, UnauthorizedError


class ApiKeyRegistry:
    """The API keys Mailroom accepts, one per calling application."""

    MIN_KEY_LENGTH = 16

    def __init__(self, keys: dict[str, str]) -> None:
        for name, key in keys.items():
            if not name or len(key) < self.MIN_KEY_LENGTH:
                raise ValueError(
                    f"API key for '{name}' must be at least {self.MIN_KEY_LENGTH} characters"
                )
        self._keys = dict(keys)

    @classmethod
    def parse(cls, raw: str) -> "ApiKeyRegistry":
        """Parse 'name:key,name2:key2'. The key is everything after the first ':'."""
        keys: dict[str, str] = {}
        for entry in (part.strip() for part in raw.split(",")):
            if not entry:
                continue
            name, separator, key = entry.partition(":")
            if not separator or not name.strip():
                raise ValueError("API_KEYS entries must look like name:key")
            if name.strip() in keys:
                raise ValueError(f"Duplicate API key name '{name.strip()}'")
            keys[name.strip()] = key.strip()
        return cls(keys)

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def client_names(self) -> list[str]:
        return sorted(self._keys)

    def client_for(self, presented_key: str | None) -> str | None:
        """Return the client name that owns `presented_key`, or None.

        Every stored key is compared (in constant time per key) so the response
        time does not reveal which key, or how much of one, was correct.
        """
        if not presented_key:
            return None
        match: str | None = None
        for name, key in self._keys.items():
            if hmac.compare_digest(key.encode(), presented_key.encode()):
                match = name
        return match


class ApiKeyAuth:
    """FastAPI dependency: reads X-API-Key and returns the calling client's name."""

    ANONYMOUS = "anonymous"

    def __init__(self, registry: ApiKeyRegistry, required: bool = True) -> None:
        self._registry = registry
        self._required = required

    @property
    def required(self) -> bool:
        return self._required

    def assert_configured(self) -> None:
        """Called at startup so a missing key list fails loudly, not silently open."""
        if self._required and len(self._registry) == 0:
            raise RuntimeError(
                "API_KEYS is empty. Set API_KEYS=name:key (key of 16+ characters), "
                "or set REQUIRE_API_KEY=false for local experiments only."
            )

    def __call__(
        self, x_api_key: str | None = Header(default=None, alias="X-API-Key")
    ) -> str:
        if not self._required:
            return self.ANONYMOUS
        client = self._registry.client_for(x_api_key)
        if client is None:
            raise UnauthorizedError(
                ErrorCode.INVALID_API_KEY, "Send a valid key in the X-API-Key header"
            )
        return client


api_key_auth = ApiKeyAuth(
    ApiKeyRegistry.parse(settings.API_KEYS), settings.REQUIRE_API_KEY
)
