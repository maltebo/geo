#!/usr/bin/env bash
# Server-side deploy script. Installed at /srv/geo/deploy.sh (owned by
# deploy-geo, mode 0750). Invoked ONLY via the SSH forced command; the requested
# git SHA arrives in $SSH_ORIGINAL_COMMAND. See README "Deployment".
set -euo pipefail
cd /srv/geo

# Validate the tag is a 40-hex git SHA (never trust the channel blindly).
REQ="${SSH_ORIGINAL_COMMAND:-}"
TAG="$(printf '%s' "$REQ" | grep -oE '[0-9a-f]{40}')" || { echo "no valid tag"; exit 2; }

# Persist previous tag for rollback before swapping.
PREV_TAG="$(grep -oE '[0-9a-f]{40}' .env.deploy 2>/dev/null || true)"

# Write IMAGE_TAG atomically via a temp file + rename (we own the directory, so
# this works even if .env.deploy was created root-owned at bootstrap, and a crash
# can never leave a half-written file).
write_image_tag() {
  local tmp
  tmp="$(mktemp ./.env.deploy.XXXXXX)"
  printf 'IMAGE_TAG=%s\n' "$1" > "$tmp"
  mv -f "$tmp" .env.deploy
}
write_image_tag "${TAG}"

# Do NOT `source` .env: it is a dotenv file, not a shell script. Values such as
# NOMINATIM_USER_AGENT contain spaces/parens and break bash's `.`. Compose reads
# the files itself via the --env-file flags below (for ${...} interpolation) and
# injects container env via `env_file:` -- neither needs shell sourcing.

# GHCR image is public; pulls are anonymous, no docker login required.
docker compose --env-file .env --env-file .env.deploy pull
# Migrate BEFORE swapping running services.
docker compose --env-file .env --env-file .env.deploy run --rm migrate
docker compose --env-file .env --env-file .env.deploy up -d
docker image prune -f

# Health gate: poll until the new web is ready, then roll back if it never is.
# Docker publishes 127.0.0.1:8000 the instant the container starts, so an early
# probe is accepted by docker-proxy and reset upstream (curl error 56) before
# uvicorn binds. `curl --retry` does NOT retry connection-level errors, so we
# poll in a loop instead -- ~40s budget covers a cold start plus the first DB
# connection.
health_ok() { curl -fsS -o /dev/null http://127.0.0.1:8000/health; }
ready=
for _ in $(seq 1 20); do
  if health_ok; then ready=1; break; fi
  sleep 2
done

if [ -z "${ready}" ]; then
  echo "health check failed, rolling back to ${PREV_TAG:-none}"
  if [ -n "${PREV_TAG:-}" ]; then
    write_image_tag "${PREV_TAG}"
    docker compose --env-file .env --env-file .env.deploy up -d
  fi
  exit 1
fi

echo "deploy ok: ${TAG}"
