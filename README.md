# Pressmünzen-Bot

Telegram bot, scraper, and public web map for elongated-coin ("Pressmünzen")
machines, sourced from the phpBB3 forum at elongated-coin.de.

## Architecture

Three roles share one PostGIS database and one Docker image:

- **bot** — long-polling Telegram bot (`/suche`, `/details`, `/besucht`, watches,
  corrections). No public inbound endpoint.
- **web** — FastAPI behind Caddy: public read-only map (`/`), GeoJSON API
  (`/api/machines`), hosted per-search maps (`/map/{token}`), admin moderation
  panel (`/admin`).
- **scraper** — one-shot, run from a host systemd timer: fetch → parse → geocode
  → upsert (content-hash change detection) → recompute coordinate precedence →
  notify watchers. A parse-rate canary aborts the run on forum HTML drift.

```
src/pressmuenzen/
  config.py logging.py __main__.py   # role dispatch: bot|web|scrape|migrate
  domain/    gps_parser.py precedence.py models.py   # pure, heavily tested
  db/        engine.py models.py geo.py repositories/
  scraper/   source.py elongated_coin.py geocoding.py canary.py pipeline.py
  services/  search.py maps.py notifications.py corrections.py
  bot/       app.py texts.py keyboards.py handlers/
  web/       app.py routes/ templates/ static/
scripts/     import_legacy_json.py deploy.sh
alembic/     versions/0001_baseline.py
tests/       unit/ integration/ fixtures/gps_strings.json
```

The **GPS parser** (`domain/gps_parser.py`) is pinned by a 618-entry regression
corpus (`tests/fixtures/gps_strings.json`) extracted from production. That corpus
is a contract — never change the parser without keeping every entry green.

## Local development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```sh
cp .env.example .env          # then fill in the values (see below)
uv sync --extra dev           # create venv + install deps

# Start only the database for local work:
docker compose up -d db

# Run migrations, import legacy data, run a role:
uv run python -m pressmuenzen migrate
uv run python -m scripts.import_legacy_json     # one-time, idempotent + parity check
uv run python -m pressmuenzen bot
uv run python -m pressmuenzen web               # http://localhost:8000
uv run python -m pressmuenzen scrape --mode incremental
```

Quality gates (run before pushing):

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q                                # unit suite (no DB needed)
TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:5432/test uv run pytest -q  # + integration
```

## Configuration

All config is environment-only (`.env`, git-ignored). See `.env.example` for the
full annotated template. The essentials:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_TOKEN` | Bot token from @BotFather |
| `ADMIN_CHAT_IDS` | Comma-separated admin chat IDs (single source of truth for admin rights) |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@db:5432/db` |
| `PUBLIC_BASE_URL` | Public URL used to build hosted-map links |
| `MAP_TOKEN_SECRET` | HMAC secret for `/map/{token}` |
| `NOMINATIM_USER_AGENT` | Identifying UA with contact (Nominatim ToS) |

To find your chat id: message the bot and send `/whoami`.

## Migration from the legacy JSON

`scripts/import_legacy_json.py` reads `data/url_database.json`,
`data/clean_database.json` and (optionally) `private/user_data.json`, then:

- creates machines **preserving the legacy `loc_ID` as `machines.id`** (so
  existing `/details <id>` keeps working);
- inserts a `coordinate_candidate` for every coordinate flavour and recomputes
  precedence (reproducing today's chosen coordinate);
- carries over the 2 manual corrections;
- migrates per-user visited lists;
- runs a **parity check** asserting every machine's computed geom/source equals
  the legacy value, and exits non-zero on any mismatch.

## Deployment (Hetzner, single box)

Push-based: CI builds a SHA-tagged image to GHCR; the Deploy workflow invokes the
server's SSH forced command with the SHA; `/srv/geo/deploy.sh` pulls, migrates,
swaps, and health-gates with auto-rollback.

### One-time server bootstrap (over your existing admin SSH)

Done once, manually, as documented here — not part of the automated pipeline.

```sh
# As root / sudo on the Hetzner box:
adduser --system --group --shell /usr/sbin/nologin deploy-geo
usermod -aG docker deploy-geo
mkdir -p /srv/geo && chown deploy-geo:deploy-geo /srv/geo

# Copy docker-compose.yml, Caddyfile into /srv/geo and create /srv/geo/.env
# (from .env.example, with real secrets). chmod 600 /srv/geo/.env.

# Install deploy.sh:
install -o deploy-geo -g deploy-geo -m 0750 scripts/deploy.sh /srv/geo/deploy.sh

# Install the CI deploy public key with a forced command (single highest-value
# control: a leaked CI key can only redeploy, never open a shell):
mkdir -p ~deploy-geo/.ssh && chmod 700 ~deploy-geo/.ssh
cat >> ~deploy-geo/.ssh/authorized_keys <<'EOF'
command="/srv/geo/deploy.sh",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA...PUBLIC_HALF... github-actions-geo-deploy
EOF
chown -R deploy-geo:deploy-geo ~deploy-geo/.ssh
chmod 600 ~deploy-geo/.ssh/authorized_keys

# Firewall + first boot:
ufw allow 22,80,443/tcp && ufw enable
cd /srv/geo && docker compose run --rm migrate && docker compose up -d
docker compose run --rm scraper --mode full   # initial data load (or import legacy)
```

### Scrape schedule (host systemd timer)

```ini
# /etc/systemd/system/geo-scrape.service
[Service]
Type=oneshot
User=deploy-geo
WorkingDirectory=/srv/geo
ExecStart=/usr/bin/docker compose run --rm scraper --mode incremental

# /etc/systemd/system/geo-scrape.timer
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
[Install]
WantedBy=timers.target
```
Add a second service/timer with `--mode full` on a monthly `OnCalendar` for the
full reconciliation sweep.

### Backups

`pg_dump | gzip` nightly, ~14 days local + weekly copy to a Hetzner Storage Box.
Test a restore once. Backups are the real insurance on a single box.

## GitHub secrets required

`DEPLOY_SSH_KEY` (CI deploy private key), `DEPLOY_HOST` (178.105.46.228),
`DEPLOY_USER` (`deploy-geo`), `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan` output for the
host). `GITHUB_TOKEN` is provided automatically for the GHCR push.
