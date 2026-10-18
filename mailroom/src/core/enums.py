from enum import Enum


class EmailStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    RETRYING = "retrying"
    DEAD = "dead"
