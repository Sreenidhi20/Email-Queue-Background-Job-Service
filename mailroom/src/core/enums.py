from enum import Enum


class EmailStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    RETRYING = "retrying"
    DEAD = "dead"


class ReplayOutcome(str, Enum):
    REPLAYED = "replayed"
    ALREADY_REPLAYED = "already_replayed"
    JOB_NOT_DEAD = "job_not_dead"
