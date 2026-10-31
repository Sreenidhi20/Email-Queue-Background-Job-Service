#!/bin/sh
# Runs migrations, the Celery worker, Celery Beat and the API in ONE container.
# For single-instance hosts (e.g. Render's free tier, which has no background workers).
# Not for production scale: if the worker or Beat crashes nothing restarts it, and you
# must never run more than one instance (two Beats would send every cron job twice).
set -e

alembic upgrade head

celery -A src.infrastructure.celery_app worker --loglevel=info --concurrency=2 &
celery -A src.infrastructure.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule &

exec uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}"
