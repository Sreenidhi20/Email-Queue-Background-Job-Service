from src.core.dto import BaseDto


class DigestStatsDto(BaseDto):
    sent_last_24h: int
    dead_last_24h: int
    queued_now: int
    retrying_now: int
    unreplayed_dead_letters: int
