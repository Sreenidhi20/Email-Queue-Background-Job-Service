from datetime import datetime

from src.core.dto import BaseDto


class HealthResponseDto(BaseDto):
    database: bool
    redis: bool
    checked_at: datetime
