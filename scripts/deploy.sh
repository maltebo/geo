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

echo "IMAGE_TAG=${TAG}" > .env.deploy
set -a; . ./.env; . ./.env.deploy; set +a

# GHCR image is public; pulls are anonymous, no docker login required.
docker compose --env-file .env --env-file .env.deploy pull
# Migrate BEFORE swapping running services.
docker compose --env-file .env --env-file .env.deploy run --rm migrate
docker compose --env-file .env --env-file .env.deploy up -d
docker image prune -f

# Health gate: roll back to the previous tag if the new web is unhealthy.
if ! curl -fsS --retry 5 --retry-delay 3 http://127.0.0.1:8000/health; then
  echo "health check failed, rolling back to ${PREV_TAG:-none}"
  if [ -n "${PREV_TAG:-}" ]; then
    echo "IMAGE_TAG=${PREV_TAG}" > .env.deploy
    docker compose --env-file .env --env-file .env.deploy up -d
  fi
  exit 1
fi

echo "deploy ok: ${TAG}"
