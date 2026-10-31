# Mailroom

Mailroom uses the feature-sliced layout in `src/`. SQL health-check history is
stored in `health_checks`; `/health` probes SQL and Redis, records the result
when SQL is available, and returns HTTP 503 if either dependency is unavailable.

## Local setup

Run these commands from the `mailroom` directory with Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`mailroom\.env` contains the `DATABASE_URL` copied from the workspace's existing
environment file. Keep it local and do not commit it. For a fresh setup without
that file, copy `.env.example` to `.env`; it uses local SQLite. Set `REDIS_URL`
in `.env` if Redis is not running at its default local address.

Start Docker Desktop, then from the `mailroom` directory start Redis and Mailpit:

```powershell
docker compose up -d redis mailpit
docker compose ps
```

Wait until both containers show as running. If Docker reports that it cannot
connect to the Docker API, start Docker Desktop and retry. The Compose file
starts Redis and Mailpit only; run the API and Celery worker as local processes.

Apply the database migration and run the API:

```powershell
alembic upgrade head
uvicorn src.main:app --reload
```

Open `http://localhost:8000/health` to check SQL and Redis. Responses use the
project's standard `ApiResponse` envelope.

## Queue and send an email

Apply migrations after installing requirements; this creates the `email_jobs`
table. Keep Redis and Mailpit running in Docker. Run the API and Celery worker
in separate terminals from `mailroom` (with the virtual environment activated):

```powershell
alembic upgrade head
uvicorn src.main:app --reload
```

```powershell
celery -A src.infrastructure.celery_app worker --loglevel=info --pool=solo
```

Submit an email from another PowerShell terminal:

```powershell
$body = @{ toEmail = "test@example.com"; subject = "Hello"; body = "First queued email" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri "http://localhost:8000/emails" -Method Post -Headers @{ "Idempotency-Key" = "demo-1" } -ContentType "application/json" -Body $body
$response
```

The API returns HTTP 202 and a job ID. Check its status at
`http://localhost:8000/emails/<job-id>` and view captured messages in Mailpit at
`http://localhost:8025`. Reusing the same idempotency key returns the original
job rather than enqueueing another email. List jobs with
`GET /emails?page=1&pageSize=20`; add a `status` query parameter to filter by
`queued`, `sending`, `sent`, `retrying`, or `dead`.

## Scheduled (delayed) emails

Add `sendAt` to `POST /emails` to send later, for example
`"sendAt": "2026-10-25T09:00:00+05:30"`. The job is saved with status `queued` and
`scheduledFor` set, and the worker holds it until that time. Rules:

- Always include a timezone offset or `Z`. A `sendAt` without one is treated as **UTC**.
- It must be in the future and at most `MAX_SEND_AHEAD_DAYS` (default 7, allowed 1 to 30)
  days ahead. Otherwise the API returns 400 with `INVALID_SEND_AT` or `SEND_AT_TOO_FAR`.
- Redis re-delivers messages that stay unacknowledged longer than its visibility timeout,
  so Mailroom sets that timeout to `MAX_SEND_AHEAD_DAYS + 1` days (see `celery_app.py`).
  The worker also never sends a job that is already `sent`.

## Dead letters and replay

When a job uses up its `max_attempts`, it becomes `dead` and a row is written to
`dead_letters` (a snapshot of the recipient, subject, last error and attempt count) in
the same database transaction.

| Request | Purpose |
| --- | --- |
| `GET /dead-letters?replayed=false&page=1&pageSize=20` | List dead letters; `replayed` filter is optional |
| `GET /dead-letters/{id}` | One dead letter |
| `POST /dead-letters/{id}/replay` | Reset the job to `queued` (attempts back to 0) and publish it again; returns 202 |

Replay returns 409 if the letter was already replayed (`DEAD_LETTER_ALREADY_REPLAYED`) or
the job is no longer `dead` (`EMAIL_JOB_NOT_DEAD`), and 503 if Redis is unreachable (nothing
is changed in that case). Run `alembic upgrade head` to create the new table.

## Scheduled jobs (Celery Beat)

Two cron jobs run in **UTC** (defaults shown with their IST equivalent):

| Task | Default time | What it does |
| --- | --- | --- |
| `maintenance.cleanup_sent_jobs` | 21:30 UTC (03:00 IST) | Deletes `sent` jobs older than `SENT_RETENTION_DAYS` (default 30). Jobs in any other status, including `dead`, are never deleted. |
| `maintenance.daily_digest` | 02:30 UTC (08:00 IST) | Queues an email to `DIGEST_TO_EMAIL` with counts for the last 24 hours (sent, died, queued, retrying, dead letters to review). Skipped if `DIGEST_TO_EMAIL` is empty. |

The digest goes through the normal email queue, so it is retried, dead-lettered and
replayable like any other email. It uses the idempotency key `daily-digest-<date>`, so it
is sent at most once per UTC day even if Beat fires twice. Change the times with the
`*_HOUR_UTC` / `*_MINUTE_UTC` settings.

Run Beat in a third terminal, next to the API and the worker (run **exactly one** Beat):

```powershell
celery -A src.infrastructure.celery_app beat --loglevel=info
```

Beat writes a local `celerybeat-schedule` file (already git-ignored).

## Retry behavior

If sending fails, the worker retries with exponential backoff and jitter. After
`max_attempts` is reached (5 by default), the job is marked `dead` and is not
retried again. Configure the backoff in `.env` with `RETRY_BASE_SECONDS` (default
`10`) and `RETRY_MAX_SECONDS` (default `600`).

## Celery smoke test

In a second terminal (also from `mailroom`), start the worker:

```powershell
celery -A src.infrastructure.celery_app worker --loglevel=info --pool=solo
```

Enqueue and wait for the sample task:

```powershell
python -c "from src.features.health.health_tasks import ping; result = ping.delay('hello'); print(result.id); print(result.get(timeout=10))"
```

The result should be `pong: hello`. Run the focused test suite with:

```powershell
python -m unittest discover -s tests -v
```

See [../.github/docs/python-type-checking-checklist.md](../.github/docs/python-type-checking-checklist.md)
for the Pylance checklist and the current test diagnostics audit.
