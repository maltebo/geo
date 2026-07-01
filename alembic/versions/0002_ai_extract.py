"""Add AI extraction: new gps_source value, machine AI columns, ai_extract_runs table.

Revision ID: 0002_ai_extract
Revises: 0001_baseline
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_extract"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add the new enum value to the existing PostgreSQL enum type.
    # ALTER TYPE ... ADD VALUE cannot be rolled back in PG < 12; on PG 12+ it can
    # run inside a transaction. IF NOT EXISTS makes the migration idempotent.
    op.execute(
        "ALTER TYPE gps_source ADD VALUE IF NOT EXISTS 'ai_address_geocode' AFTER 'forum_gps'"
    )

    # AI extraction columns on machines (all nullable — populated by the nightly job).
    op.add_column("machines", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column("machines", sa.Column("opening_hours", sa.Text(), nullable=True))
    op.add_column("machines", sa.Column("thread_content_hash", sa.String(64), nullable=True))
    op.add_column("machines", sa.Column("last_message_count", sa.Integer(), nullable=True))
    op.add_column(
        "machines",
        sa.Column("last_ai_analyzed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Audit table for nightly AI extraction runs.
    op.create_table(
        "ai_extract_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("budget", sa.Integer(), nullable=False),
        sa.Column("threads_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_calls_made", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("corrections_enqueued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_extract_runs")
    op.drop_column("machines", "last_ai_analyzed_at")
    op.drop_column("machines", "last_message_count")
    op.drop_column("machines", "thread_content_hash")
    op.drop_column("machines", "opening_hours")
    op.drop_column("machines", "ai_summary")
    # Removing an enum value from PostgreSQL requires recreating the type.
    # We leave the 'ai_address_geocode' value in place — it is harmless when unused.
