# Single image for all three roles (bot | web | scrape). The container command
# selects the role; this keeps deps/code identical across processes (lean ops).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer — only re-runs when pyproject.toml/README.md changes.
# A stub package satisfies hatchling so the full dep graph is resolved and
# downloaded here, before the real source is ever copied in.
COPY pyproject.toml README.md ./
RUN mkdir -p src/pressmuenzen && touch src/pressmuenzen/__init__.py && \
    uv pip install --system --no-cache .

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
