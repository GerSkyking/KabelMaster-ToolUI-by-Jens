#!/bin/sh
set -e
cd /srv/server
# Datenbank-Schema auf den aktuellen Stand bringen (idempotent)
alembic upgrade head
exec uvicorn wtserver.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --workers "${WEB_CONCURRENCY:-1}"
