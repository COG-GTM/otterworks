#!/usr/bin/env bash
# Ensure .env carries a private JWT_SECRET for docker-compose.yml, which has no default.
# Drops empty JWT_SECRET entries and any whose value is a signing key that was once
# committed to this repo, keeps every other entry, and appends a random key only if none remains.
set -euo pipefail

ENV_FILE="${1:-.env}"
PUBLIC_JWT_SECRETS=(
  otterworks-local-dev-jwt-secret-change-me-in-production
  dev-jwt-secret-otterworks-2024-change-in-production
  otterworks-dev-secret
)

is_public() {
  local candidate="$1" s
  for s in "${PUBLIC_JWT_SECRETS[@]}"; do
    [ "$candidate" = "$s" ] && return 0
  done
  return 1
}

# Value as docker compose reads it: optional `export`, surrounding quotes, trailing ` # comment`.
entry_value() {
  local v="${1#*=}"
  v="${v#"${v%%[![:space:]]*}"}"
  case "$v" in
    \"*) v="${v#\"}"; v="${v%%\"*}" ;;
    \'*) v="${v#\'}"; v="${v%%\'*}" ;;
    \#*) v="" ;;
    *) v="${v%%[[:space:]]#*}"; v="${v%"${v##*[![:space:]]}"}" ;;
  esac
  printf '%s' "$v"
}

if [ -n "${JWT_SECRET:-}" ] && is_public "$JWT_SECRET"; then
  echo "JWT_SECRET exported in this shell is a publicly known key; unset it or export a new one (openssl rand -hex 32)." >&2
  exit 1
fi

entry_re='^[[:space:]]*(export[[:space:]]+)?JWT_SECRET[[:space:]]*='
has_private=false
if [ -f "$ENV_FILE" ]; then
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  removed=false
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ $entry_re ]]; then
      value="$(entry_value "$line")"
      if [ -z "$value" ]; then
        continue
      fi
      if is_public "$value"; then
        removed=true
        continue
      fi
      has_private=true
    fi
    printf '%s\n' "$line" >> "$tmp"
  done < "$ENV_FILE"
  mv "$tmp" "$ENV_FILE"
  if [ "$removed" = true ]; then echo "Removed a publicly known JWT_SECRET from $ENV_FILE"; fi
fi

if [ "$has_private" = false ]; then
  echo "JWT_SECRET=$(openssl rand -hex 32)" >> "$ENV_FILE"
  echo "Wrote a random JWT_SECRET to $ENV_FILE"
fi
