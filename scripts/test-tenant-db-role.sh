#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# Integration test for scripts/lib/tenant-db-role.sql against a real Postgres.
#
# Mimics RDS: the "master" is a non-superuser with CREATEROLE/CREATEDB that owns
# the golden database. Two tenant databases are provisioned (one of them already
# populated by the master, as every pre-existing tenant is), and each tenant role
# must reach only its own database. Needs docker; skipped without it.
# ------------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SQL="${SCRIPT_DIR}/lib/tenant-db-role.sql"
IMAGE="${PG_TEST_IMAGE:-postgres:15}"
NAME="tenant-db-role-test-$$"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
nope() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

command -v docker >/dev/null 2>&1 || { echo "SKIP: docker not available"; exit 0; }
docker run -d --rm --name "${NAME}" -e POSTGRES_PASSWORD=super "${IMAGE}" >/dev/null || { echo "SKIP: cannot start ${IMAGE}"; exit 0; }
trap 'docker rm -f "${NAME}" >/dev/null 2>&1' EXIT
for _ in $(seq 1 60); do docker exec "${NAME}" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1 && break; sleep 1; done

# psql inside the container over its pod IP rather than loopback: the image
# trusts 127.0.0.1, and the point is to exercise password auth.
HOST="$(docker exec "${NAME}" hostname -i | awk '{print $1}')"
q() { # user password db sql...
  local u="$1" p="$2" d="$3"; shift 3
  docker exec -i -e PGPASSWORD="${p}" "${NAME}" psql -X -q -tA -v ON_ERROR_STOP=1 \
    "host=${HOST} user=${u} dbname=${d}" "$@"
}
provision() { # db role password
  docker exec -i -e PGPASSWORD=master -e TENANT_DB_PASSWORD="$3" "${NAME}" \
    psql -X -q "host=${HOST} user=master dbname=otterworks" -v db="$1" -v role="$2" -f - <"${SQL}"
}
expect_ok()   { if q "$@" >/dev/null 2>&1; then ok "${*: -1}"; else nope "${*: -1}"; fi; }
expect_fail() { if q "$@" >/dev/null 2>&1; then nope "denied: ${*: -1}"; else ok "denied: ${*: -1}"; fi; }

q postgres super postgres -c "CREATE ROLE master LOGIN CREATEROLE CREATEDB PASSWORD 'master'" >/dev/null
q postgres super postgres -c "CREATE DATABASE otterworks OWNER master" >/dev/null
q master master otterworks -c "CREATE TABLE golden_secret (v text); INSERT INTO golden_secret VALUES ('golden')" >/dev/null
q master master otterworks -c 'CREATE DATABASE otterworks_alice' >/dev/null
q master master otterworks -c 'CREATE DATABASE otterworks_bob' >/dev/null
# alice is a pre-existing tenant: the master already ran its migrations.
q master master otterworks_alice -c "
  CREATE SCHEMA analytics;
  CREATE TYPE mood AS ENUM ('ok', 'bad');
  CREATE TABLE docs (id serial PRIMARY KEY, title text, m mood);
  CREATE TABLE analytics.events (id bigint GENERATED ALWAYS AS IDENTITY, name text);
  CREATE VIEW doc_titles AS SELECT title FROM docs;
  CREATE FUNCTION doc_count() RETURNS bigint LANGUAGE sql AS 'SELECT count(*) FROM docs';
  INSERT INTO docs (title) VALUES ('alice-doc');" >/dev/null

echo "provisioning..."
if provision otterworks_alice otterworks_alice_app alicepw >/dev/null && provision otterworks_bob otterworks_bob_app bobpw >/dev/null; then
  ok "provisioning succeeds"
else
  nope "provisioning succeeds"
fi
if provision otterworks_alice otterworks_alice_app alicepw >/dev/null; then ok "re-provisioning is idempotent"; else nope "re-provisioning is idempotent"; fi
if docker exec -i -e PGPASSWORD=master "${NAME}" \
     psql -X -q "host=${HOST} user=master dbname=otterworks" -v db=otterworks_bob -v role=otterworks_bob_app -f - <"${SQL}" >/dev/null 2>&1; then
  nope "missing TENANT_DB_PASSWORD is rejected"
else
  ok "missing TENANT_DB_PASSWORD is rejected"
fi

echo "tenant role reaches its own database:"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "SELECT title FROM docs"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "ALTER TABLE docs ADD COLUMN body text"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "INSERT INTO docs (title, m) VALUES ('x', 'ok')"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "ALTER TABLE analytics.events ADD COLUMN at timestamptz"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "CREATE OR REPLACE VIEW doc_titles AS SELECT title, body FROM docs"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "ALTER TYPE mood ADD VALUE 'great'"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "SELECT doc_count()"
expect_ok otterworks_alice_app alicepw otterworks_alice -c "CREATE TABLE new_tbl (id int)"
expect_ok otterworks_bob_app bobpw otterworks_bob -c "CREATE TABLE bob_tbl (id int)"

echo "tenant role is confined to it:"
expect_fail otterworks_alice_app alicepw otterworks_bob -c "SELECT 1"
expect_fail otterworks_alice_app alicepw otterworks -c "SELECT * FROM golden_secret"
expect_fail otterworks_bob_app bobpw otterworks_alice -c "SELECT 1"
expect_fail otterworks_alice_app alicepw otterworks_alice -c "CREATE DATABASE sneaky"
expect_fail otterworks_alice_app alicepw otterworks_alice -c "CREATE ROLE sneaky"
expect_fail otterworks_alice_app alicepw otterworks_alice -c "SET ROLE otterworks_bob_app"
expect_fail otterworks_alice_app wrongpw otterworks_alice -c "SELECT 1"

echo "master keeps admin access:"
expect_ok master master otterworks -c "SELECT * FROM golden_secret"
expect_ok master master otterworks_alice -c "SELECT title FROM docs"
expect_ok master master otterworks -c 'DROP DATABASE otterworks_bob WITH (FORCE)'
expect_ok master master otterworks -c 'DROP ROLE otterworks_bob_app'

echo "${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ]
