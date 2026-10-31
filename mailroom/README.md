# Mailroom: Email Queue & Background Job Service

A small service other applications call to send email without waiting for it. `POST /emails`
saves the job, puts it on a Redis queue and answers `202` in milliseconds. A separate Celery
worker sends the email in the background, retries failures with exponential backoff, and parks
emails that keep failing in a dead-letter table you can inspect and replay through the API.

Built with FastAPI, SQLAlchemy, Alembic, Postgres, Celery, Redis, Celery Beat and Flower.

## Architecture

```mermaid
flowchart LR
    Client["Calling app<br/>(X-API-Key)"] -->|POST /emails| API["FastAPI API"]
    API -->|1. INSERT job: queued| DB[("Postgres")]
    API -->|2. publish job id| Redis[("Redis queue")]
    Redis --> Worker["Celery worker"]
    Worker -->|send| Mail["Mail server<br/>SMTP or HTTP API"]
    Worker -->|status, attempts, errors| DB
    Worker -->|out of attempts: dead + dead_letters row| DB
    Beat["Celery Beat (cron)"] -->|nightly cleanup, daily digest| Redis
    Flower["Flower dashboard"] -.->|watches| Redis
    Client -->|GET /emails, /dead-letters, replay| API
```

Layout (feature-sliced, every component is a class; see `.github/docs/architecture-standard.md`):

```
src/
  core/            config, errors + catalog, enums, ApiResponse envelope, API-key auth, DB
  domain/          table definitions (EmailJob, DeadLetter, HealthCheck)
  infrastructure/  Redis, Celery, mailers, retry policy, rate limiter, Flower launcher
  features/
    emails/        query -> service -> router (+ worker task)
    dead_letters/  query -> service -> router
    maintenance/   scheduled cleanup and digest
    health/        /health
```

Every response uses the same envelope: `{ statusCode, isSuccess, data, detail, error }`.

## Features

| Feature | How it works |
| --- | --- |
| Instant, non-blocking send | API stores the job, publishes its id, returns `202`. |
| Status lifecycle | `queued → sending → sent`, or `retrying`, or `dead`; `attempts` and `lastError` are tracked. |
| Retries with backoff | Delay doubles each retry (base 10s, cap 600s) with jitter, up to `max_attempts` (default 5). |
| Delayed emails | `sendAt` (timezone-aware, at most `MAX_SEND_AHEAD_DAYS` ahead). |
| Dead-letter queue + replay | After the last attempt a `dead_letters` row is written in the same transaction as the `dead` status. `POST /dead-letters/{id}/replay` re-queues it. |
| Idempotency | `Idempotency-Key` header: the same key returns the same job and never sends twice, even for simultaneous requests. |
| Cron jobs | Celery Beat: nightly cleanup of old `sent` jobs, daily digest email. |
| Auth | `X-API-Key` required on `/emails` and `/dead-letters`; each key belongs to a named client. |
| Rate limiting | `POST /emails` limited per API key per minute (default 60), `429` with `Retry-After`. |
| Monitoring | Flower dashboard (password enforced), `/health` probing Postgres and Redis. |

## Run it locally

Python 3.12, Docker Desktop. From the `mailroom` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then set FLOWER_PASSWORD and your own API key
docker compose up -d redis mailpit
alembic upgrade head
```

Then start each in its own terminal (Celery on Windows needs `--pool=solo`):

```powershell
uvicorn src.main:app --reload
celery -A src.infrastructure.celery_app worker --loglevel=info --pool=solo
celery -A src.infrastructure.celery_app beat --loglevel=info
python -m src.infrastructure.flower_launcher
```

| URL | What |
| --- | --- |
| http://localhost:8000/docs | Swagger UI (use **Authorize** with your API key) |
| http://localhost:8025 | Mailpit inbox: every email the worker sends locally |
| http://localhost:5555 | Flower (user and password from `.env`) |

Send one:

```powershell
curl.exe -X POST http://localhost:8000/emails -H "X-API-Key: dev-key-change-me-0123456789" -H "Content-Type: application/json" -d "{\"toEmail\":\"test@example.com\",\"subject\":\"Hello\",\"body\":\"First queued email\"}"
```

A Postman collection is in `API collection/` (set the `apiKey` collection variable).

### Everything in containers

```powershell
docker compose --profile app up --build
```

Starts Postgres, runs migrations, then the API (`:8000`), worker, Beat, Flower (`:5555`), Redis and Mailpit. Override the dev defaults with `API_KEYS`, `FLOWER_USER`, `FLOWER_PASSWORD` and `DIGEST_TO_EMAIL` in your shell or a `.env` next to the compose file.

## API

| Method and path | Purpose |
| --- | --- |
| `POST /emails` | Queue an email (`202`). Body: `toEmail`, `subject`, `body`, optional `sendAt`. Header `Idempotency-Key` optional. |
| `GET /emails/{id}` | Job status, attempts, last error. |
| `GET /emails?status=&page=&pageSize=` | List jobs. |
| `GET /dead-letters?replayed=&page=&pageSize=` | Emails that failed for good. |
| `GET /dead-letters/{id}` | One dead letter. |
| `POST /dead-letters/{id}/replay` | Re-queue a dead email from attempt 0 (`202`). |
| `GET /health` | Postgres and Redis check (no key needed). |

Error responses use the same envelope. Notable codes: `401` missing or invalid key, `400` bad `sendAt`, `404` unknown id, `409` dead letter already replayed or job no longer dead, `429` rate limited (`Retry-After` header), `503` queue (Redis) unavailable, in which case nothing is saved.

### Scheduled (delayed) emails

Add `sendAt`, for example `"sendAt": "2026-10-25T09:00:00+05:30"`. Always include a timezone offset or `Z`: a value without one is treated as **UTC**. It must be in the future and at most `MAX_SEND_AHEAD_DAYS` (default 7, allowed 1 to 30) ahead (`INVALID_SEND_AT`, `SEND_AT_TOO_FAR`). Redis re-delivers messages that stay unacknowledged longer than its visibility timeout, so Mailroom sets that timeout to `MAX_SEND_AHEAD_DAYS + 1` days, and the worker never sends a job that is already `sent`.

### Retry behavior

On failure the job becomes `retrying` and Celery retries after `RETRY_BASE_SECONDS × 2^n` (capped at `RETRY_MAX_SECONDS`, then randomised between half and full). When `attempts` reaches `max_attempts` (5 by default) the job becomes `dead` and stops retrying. If Redis is down when you queue an email, the API returns `503` and removes the row, so a client retry (even with the same `Idempotency-Key`) starts clean.

### Dead letters and replay

A dead letter is a snapshot (recipient, subject, last error, attempts) written in the same transaction that marks the job `dead`. Replay resets the job to `queued` with attempts 0 and publishes it again. Marking the letter replayed and resetting the job are two conditional updates in one transaction, so two simultaneous replays cannot both succeed (`409 DEAD_LETTER_ALREADY_REPLAYED`). If Redis is down during replay, the letter and job are restored.

### Scheduled jobs (Celery Beat, UTC)

| Task | Default | What it does |
| --- | --- | --- |
| `maintenance.cleanup_sent_jobs` | 21:30 UTC (03:00 IST) | Deletes `sent` jobs older than `SENT_RETENTION_DAYS` (30). Never deletes `dead`, `queued` or `retrying` jobs. |
| `maintenance.daily_digest` | 02:30 UTC (08:00 IST) | Queues a summary email to `DIGEST_TO_EMAIL` (sent, died, queued, retrying, dead letters to review). Idempotency key `daily-digest-<date>`: at most one per UTC day. |

Run exactly **one** Beat, or every cron job fires twice.

### Flower

Flower refuses to start unless `FLOWER_USER` and a `FLOWER_PASSWORD` of 8+ characters are set. The dashboard and `/api/*` need the password; Flower's Prometheus `/metrics` page is public by design and exposes only task names, worker names and event counts. Block it at your proxy if you do not scrape it. Task history is kept in `flower.db`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | none (required) | SQLAlchemy URL, e.g. `postgresql+psycopg://user:pass@host:5432/db` (add `?sslmode=require` for Aiven) |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue broker |
| `API_KEYS` | empty | `name:key,name2:key2`, keys 16+ chars. The app refuses to start with none unless `REQUIRE_API_KEY=false` |
| `REQUIRE_API_KEY` | `true` | Set `false` only for throwaway local experiments |
| `RATE_LIMIT_PER_MINUTE` | `60` | Per API key, `POST /emails` |
| `MAIL_BACKEND` | `smtp` | `smtp` (Mailpit) or `resend` (HTTPS API) |
| `MAIL_FROM` | `noreply@mailroom.local` | Sender address |
| `SMTP_HOST` / `SMTP_PORT` | `localhost` / `1025` | SMTP server |
| `RESEND_API_KEY` | empty | Required when `MAIL_BACKEND=resend` |
| `RETRY_BASE_SECONDS` / `RETRY_MAX_SECONDS` | `10` / `600` | Backoff |
| `MAX_SEND_AHEAD_DAYS` | `7` | Furthest `sendAt` accepted (1 to 30) |
| `SENT_RETENTION_DAYS` | `30` | Cleanup window |
| `DIGEST_TO_EMAIL` | empty | Digest recipient; empty disables the digest |
| `CLEANUP_*` / `DIGEST_*` `_HOUR_UTC` / `_MINUTE_UTC` | see above | Cron times |
| `FLOWER_USER` / `FLOWER_PASSWORD` / `FLOWER_PORT` | empty / empty / `5555` | Flower login and port |

## Tests

```powershell
python -m unittest discover -s tests -v
```

Unit tests use fakes and in-memory SQLite (no Redis or SMTP needed). GitHub Actions (`Mailroom CI`) runs them on Python 3.12, applies and rolls back the Alembic migrations on SQLite, and builds the Docker image.

## Deploy (Render + Aiven Postgres, free tiers)

Render's free tier has no background workers and, as far as I know, blocks outbound SMTP, so:

1. **Database:** an Aiven Postgres service. `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:PORT/DB?sslmode=require`.
2. **Redis:** a Render Key Value instance. Use its **internal** `redis://` URL as `REDIS_URL` (the external `rediss://` URL needs extra TLS settings for Celery).
3. **Email:** a Resend account. Set `MAIL_BACKEND=resend`, `RESEND_API_KEY`, and `MAIL_FROM`. Until you verify a domain in Resend, only its test sender (`onboarding@resend.dev`) works and it can deliver only to your own address.
4. **Web service:** runtime Docker, root directory `mailroom`, **Docker Command** `./scripts/start_all_in_one.sh`. It runs migrations, then the worker, Beat and the API inside the one container. Add `API_KEYS`, `DIGEST_TO_EMAIL` and the variables above, and keep the instance count at **1** (two instances would run Beat twice).
5. Check `https://<service>.onrender.com/health`, then queue an email with your API key.

The all-in-one script is a free-tier compromise: if the worker or Beat process dies nothing restarts it. For anything real, run `api`, `worker`, `beat` as separate services (as in `docker-compose.yml`). Free instances sleep when idle, which also pauses the worker and cron jobs. Flower is not part of the free deployment; run it locally against the same Redis if you need it.

## Design decisions and known limits

- **Delivery is at-least-once.** A worker crash after SMTP accepted the message but before the status update can cause a resend. The `sent` check prevents most duplicates but cannot remove this window; true exactly-once email delivery is not possible.
- **Rate limiter is a fixed window**: a client can burst up to 2× the limit across a window boundary. It fails open if Redis is down.
- **API keys live in an environment variable**, compared in constant time. There is no key rotation endpoint or per-key permissions; adding an `api_clients` table would be the next step.
- **Cleanup never deletes dead jobs**, because their dead letters (which cascade with the job) must stay replayable.
- Possible next steps: per-key quotas, webhooks on `dead`, HTML templates, a small React admin page over the existing API.
