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

# Read a single dotenv value without sourcing the file. Safe here because the
# keys we use (TELEGRAM_TOKEN, ADMIN_CHAT_IDS) hold no spaces or shell metachars.
dotenv_get() { grep -oE "^$1=.*" .env 2>/dev/null | head -n1 | cut -d= -f2-; }

# Best-effort Telegram alert to every admin chat. Never fails the deploy: the
# deploy outcome is already decided by the time we notify. Runs in the deploy
# layer (not via the app) so it stays usable even when the new container is broken.
notify_admins() {
  local msg="$1" token ids id
  token="$(dotenv_get TELEGRAM_TOKEN)"
  ids="$(dotenv_get ADMIN_CHAT_IDS)"
  [ -n "${token}" ] && [ -n "${ids}" ] || { echo "notify skipped: token or ADMIN_CHAT_IDS missing"; return 0; }
  IFS=',' read -ra id <<< "${ids}"
  for chat in "${id[@]}"; do
    chat="$(printf '%s' "${chat}" | tr -d '[:space:]')"
    [ -n "${chat}" ] || continue
    curl -fsS -o /dev/null --max-time 10 \
      "https://api.telegram.org/bot${token}/sendMessage" \
      --data-urlencode "chat_id=${chat}" \
      --data-urlencode "text=[Pressmuenzen] ${msg}" \
      || echo "notify failed for chat ${chat}"
  done
}

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
  prev_short="${PREV_TAG:0:7}"
  notify_admins "Deploy FEHLGESCHLAGEN fuer ${TAG:0:7}; Rollback auf ${prev_short:-none}. Health-Check nicht bestanden."
  exit 1
fi

echo "deploy ok: ${TAG}"
notify_admins "Deploy erfolgreich: ${TAG:0:7}"
