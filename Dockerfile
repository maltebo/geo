# Single image for all three roles (bot | web | scrape). The container command
# selects the role; this keeps deps/code identical across processes (lean ops).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer — only re-runs when pyproject.toml/uv.lock changes.
# Install the exact versions from uv.lock; a plain `uv pip install .` resolves afresh.
COPY pyproject.toml uv.lock README.md ./
RUN uv export --frozen --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Application code — fast reinstall, no network (deps already present above).
COPY src ./src
RUN uv pip install --system --no-cache --no-deps --reinstall .

# Migrations + helper scripts.
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

# Non-root runtime user.
RUN useradd --system --create-home --uid 10001 appuser
USER appuser

# Entrypoint dispatches on the first argument: bot | web | scrape.
ENTRYPOINT ["python", "-m", "pressmuenzen"]
CMD ["bot"]
