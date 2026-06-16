# Single image for all three roles (bot | web | scrape). The container command
# selects the role; this keeps deps/code identical across processes (lean ops).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer (cached unless pyproject changes).
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# Application code + migrations.
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

# Non-root runtime user.
RUN useradd --system --create-home --uid 10001 appuser
USER appuser

# Entrypoint dispatches on the first argument: bot | web | scrape.
ENTRYPOINT ["python", "-m", "pressmuenzen"]
CMD ["bot"]
