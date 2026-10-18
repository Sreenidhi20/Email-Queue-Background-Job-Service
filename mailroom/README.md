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

Start Redis and Mailpit using the Docker commands in the project build plan, then
apply the database migration and run the API:

```powershell
alembic upgrade head
uvicorn src.main:app --reload
```

Open `http://localhost:8000/health` to check SQL and Redis. Responses use the
project's standard `ApiResponse` envelope.

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

See [docs/python-type-checking-checklist.md](docs/python-type-checking-checklist.md)
for the Pylance checklist and the current test diagnostics audit.
