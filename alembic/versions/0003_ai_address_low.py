"""Add ai_address_geocode_low to gps_source enum.

Revision ID: 0003_ai_address_low
Revises: 0002_ai_extract
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_ai_address_low"
down_revision: str | None = "0002_ai_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE gps_source ADD VALUE IF NOT EXISTS"
        " 'ai_address_geocode_low' AFTER 'full_name_geocode'"
    )


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; the value is left in place.
    pass
