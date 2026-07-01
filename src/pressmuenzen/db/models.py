"""SQLAlchemy ORM models -- the PostGIS schema from the rewrite plan (section 2.2).

Geometry is stored as ``geometry(Point, 4326)``; distance queries cast to
``geography`` so we get metres without projection headaches. Alembic owns the
schema; this module is the single source of truth the migrations track.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pressmuenzen.domain.models import (
    CorrectionStatus,
    CorrectionType,
    GpsSource,
    MachineStatus,
)

# Reusable Enum column factories (native PG enums, named for Alembic stability).
_gps_source_enum = Enum(
    GpsSource, name="gps_source", values_callable=lambda e: [m.value for m in e]
)
_status_enum = Enum(
    MachineStatus, name="machine_status", values_callable=lambda e: [m.value for m in e]
)
_corr_type_enum = Enum(
    CorrectionType, name="correction_type", values_callable=lambda e: [m.value for m in e]
)
_corr_status_enum = Enum(
    CorrectionStatus, name="correction_status", values_callable=lambda e: [m.value for m in e]
)


def _point() -> Geometry:
    """A fresh PostGIS POINT type for one column.

    geoalchemy2's ``Geometry`` propagates its own ``nullable`` onto the column
    when it is attached. Sharing a single instance across columns therefore lets
    a ``NOT NULL`` geometry column (e.g. ``coordinate_candidates.geom``) flip the
    nullability of every other geometry column, including the nullable ones like
    ``users.home_geom``. A new instance per column keeps them isolated so the
    per-column ``nullable=`` actually holds.
    """
    return Geometry(geometry_type="POINT", srid=4326, spatial_index=False)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Region(Base, TimestampMixin):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), default="elongated_coin", nullable=False)
    source_forum_url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_limited_section: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interesting: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    machines: Mapped[list[Machine]] = relationship(back_populates="region")


class Machine(Base):
    __tablename__ = "machines"

    # NB: id reuses the legacy loc_ID so existing /details <id> keeps working.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    source: Mapped[str] = mapped_column(String(64), default="elongated_coin", nullable=False)
    # Not unique: the legacy data lists the same forum topic under two regions
    # (e.g. a machine in both its region and the time-limited section), and we
    # preserve both legacy loc_IDs. Indexed for upsert-by-url lookups.
    source_url: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entry_date_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[MachineStatus] = mapped_column(
        _status_enum, default=MachineStatus.ACTIVE, nullable=False
    )
    is_limited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    geom: Mapped[str | None] = mapped_column(_point(), nullable=True)
    gps_source: Mapped[GpsSource] = mapped_column(
        _gps_source_enum, default=GpsSource.NONE, nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # AI extraction fields (populated by the nightly ai-extract job)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Bespoke JSON spec: {"periods": [{"days": [...], "open": "HH:MM", "close": "HH:MM"}], "notes": "..."}
    opening_hours: Mapped[str | None] = mapped_column(Text, nullable=True)
    thread_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_message_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_ai_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    region: Mapped[Region | None] = relationship(back_populates="machines")
    candidates: Mapped[list[CoordinateCandidate]] = relationship(
        back_populates="machine", cascade="all, delete-orphan"
    )


class CoordinateCandidate(Base, TimestampMixin):
    """Every coordinate we ever derive, kept so precedence is recomputed not lost."""

    __tablename__ = "coordinate_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[GpsSource] = mapped_column(_gps_source_enum, nullable=False)
    geom: Mapped[str] = mapped_column(_point(), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    machine: Mapped[Machine] = relationship(back_populates="candidates")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    home_geom: Mapped[str | None] = mapped_column(_point(), nullable=True)
    notify_radius_km: Mapped[float] = mapped_column(Float, default=25.0, nullable=False)
    muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    visited: Mapped[list[Visited]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    watches: Mapped[list[Watch]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Visited(Base):
    __tablename__ = "visited"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    visited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="visited")


class Watch(Base, TimestampMixin):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    center_geom: Mapped[str] = mapped_column(_point(), nullable=False)
    radius_km: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="watches")


class Correction(Base, TimestampMixin):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[CorrectionType] = mapped_column(_corr_type_enum, nullable=False)
    proposed_geom: Mapped[str | None] = mapped_column(_point(), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CorrectionStatus] = mapped_column(
        _corr_status_enum, default=CorrectionStatus.PENDING, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    machines_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    machines_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    machines_unchanged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class GeocodeCache(Base, TimestampMixin):
    __tablename__ = "geocode_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    geom: Mapped[str | None] = mapped_column(_point(), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="nominatim", nullable=False)


class NotificationSent(Base):
    __tablename__ = "notifications_sent"
    __table_args__ = (
        UniqueConstraint("user_id", "machine_id", "kind", name="uq_notification_idem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiExtractRun(Base):
    """Audit log for each nightly AI extraction run, mirroring scrape_runs."""

    __tablename__ = "ai_extract_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    budget: Mapped[int] = mapped_column(Integer, nullable=False)
    threads_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_calls_made: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    candidates_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    corrections_enqueued: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
