"""Baseline schema: PostGIS extension, enums, all tables and spatial indexes.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


gps_source = postgresql.ENUM(
    "corrected",
    "forum_gps",
    "full_name_geocode",
    "partial_name_geocode",
    "none",
    name="gps_source",
    create_type=False,
)
machine_status = postgresql.ENUM(
    "active", "gone", "unknown", name="machine_status", create_type=False
)
correction_type = postgresql.ENUM(
    "gps", "gone", "moved", "name", "other", name="correction_type", create_type=False
)
correction_status = postgresql.ENUM(
    "pending", "approved", "rejected", name="correction_status", create_type=False
)


def _point() -> geoalchemy2.Geometry:
    # spatial_index=False: indexes are created explicitly below where wanted.
    return geoalchemy2.Geometry(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    bind = op.get_bind()
    for enum in (gps_source, machine_status, correction_type, correction_status):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="elongated_coin"),
        sa.Column("source_forum_url", sa.String(512), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("is_limited_section", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interesting", sa.Boolean(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "machines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="elongated_coin"),
        sa.Column("source_url", sa.String(512), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("region_id", sa.Integer(), sa.ForeignKey("regions.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("entry_date_text", sa.String(128), nullable=True),
        sa.Column("status", machine_status, nullable=False, server_default="active"),
        sa.Column("is_limited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("geom", _point(), nullable=True),
        sa.Column("gps_source", gps_source, nullable=False, server_default="none"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index("idx_machines_geom", "machines", ["geom"], postgresql_using="gist")
    op.create_index("ix_machines_source_url", "machines", ["source_url"])

    op.create_table(
        "coordinate_candidates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "machine_id",
            sa.Integer(),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source", gps_source, nullable=False),
        sa.Column("geom", _point(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.String(256), nullable=True),
        sa.Column("home_geom", _point(), nullable=True),
        sa.Column("notify_radius_km", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "visited",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "machine_id",
            sa.Integer(),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "visited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "watches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("center_geom", _point(), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "machine_id",
            sa.Integer(),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("type", correction_type, nullable=False),
        sa.Column("proposed_geom", _point(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("status", correction_status, nullable=False, server_default="pending"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_success_rate", sa.Float(), nullable=True),
        sa.Column("machines_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("machines_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("machines_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "geocode_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("query", sa.String(512), nullable=False, unique=True),
        sa.Column("geom", _point(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default="nominatim"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "notifications_sent",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "machine_id",
            sa.Integer(),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "machine_id", "kind", name="uq_notification_idem"),
    )


def downgrade() -> None:
    op.drop_table("notifications_sent")
    op.drop_table("geocode_cache")
    op.drop_table("scrape_runs")
    op.drop_table("corrections")
    op.drop_table("watches")
    op.drop_table("visited")
    op.drop_table("users")
    op.drop_table("coordinate_candidates")
    op.drop_index("ix_machines_source_url", table_name="machines")
    op.drop_index("idx_machines_geom", table_name="machines")
    op.drop_table("machines")
    op.drop_table("regions")
    for enum in (correction_status, correction_type, machine_status, gps_source):
        enum.drop(op.get_bind(), checkfirst=True)
