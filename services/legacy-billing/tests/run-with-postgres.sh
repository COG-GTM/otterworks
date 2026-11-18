#!/usr/bin/env bash
# Runs the full suite (unit + DB) against a throwaway postgres:16 container.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${LEGACY_BILLING_PG_IMAGE:-postgres:16}"
PORT="${LEGACY_BILLING_PG_PORT:-55497}"
NAME="legacy-billing-test-pg-$$"
docker run -d --rm --name "$NAME" -e POSTGRES_USER=billing -e POSTGRES_PASSWORD=billing \
  -e POSTGRES_DB=billing_test -p "127.0.0.1:${PORT}:5432" "$IMAGE" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U billing -d billing_test -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done
export LEGACY_BILLING_TEST_DSN="host=127.0.0.1 port=${PORT} dbname=billing_test user=billing password=billing"
export LEGACY_BILLING_REQUIRE_DB=1
python -m pytest --cov --cov-report=term-missing "$@"
