#!/usr/bin/env bash
# Generate a random ALERT_WEBHOOK_SECRET into the gitignored .env that
# docker compose reads, so the local alert webhook is never left open or on a
# shared default. An exported value or an existing .env entry wins.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -n "${ALERT_WEBHOOK_SECRET:-}" ] && exit 0
if [ -f .env ] && grep -qE '^ALERT_WEBHOOK_SECRET=.+' .env; then exit 0; fi
umask 077
printf 'ALERT_WEBHOOK_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env
echo "Generated ALERT_WEBHOOK_SECRET in .env"
