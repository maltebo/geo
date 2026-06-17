"""Scraper orchestration: fetch -> parse -> geocode -> upsert -> notify.

Resilience is non-negotiable: per-topic failures are logged and counted, never
fatal. A parse-rate canary aborts the run (keeping previous data) if the forum
template appears to have drifted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

import httpx
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.models import Machine, ScrapeRun
from pressmuenzen.db.repositories.corrections import ScrapeRunRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.gps_parser import parse_gps_text
from pressmuenzen.domain.models import Coordinate, GpsSource
from pressmuenzen.domain.name_geocode import name_geocode_queries
from pressmuenzen.logging import configure_logging, get_logger
from pressmuenzen.scraper import canary
from pressmuenzen.scraper.elongated_coin import ElongatedCoinSource
from pressmuenzen.scraper.geocoding import Geocoder
from pressmuenzen.scraper.source import ScrapedMachine, ScrapeStats, Source

log = get_logger("scraper.pipeline")


def _content_hash(machine: ScrapedMachine) -> str:
    return sha256(machine.content_hash_input().encode("utf-8")).hexdigest()


async def run_scrape(mode: str = "incremental") -> ScrapeStats:
    configure_logging()
    stats = ScrapeStats()
    new_machine_ids: list[int] = []

    async with session_scope() as session:
        run = await ScrapeRunRepository(session).start(mode)
        run_id = run.id
        trailing = await ScrapeRunRepository(session).trailing_parse_rate()

    async with httpx.AsyncClient(timeout=20.0) as client:
        source: Source = ElongatedCoinSource(client=client)
        await _scrape_all(source, stats, new_machine_ids)

    # Canary gate: refuse to finalize if parsing looks broken.
    verdict = canary.check(stats.parse_rate, trailing, stats.topics_seen)
    status = "ok" if verdict.ok else "aborted"

    async with session_scope() as session:
        db_run = await session.get(ScrapeRun, run_id)
        if db_run is not None:
            db_run.finished_at = datetime.now(UTC)
            db_run.status = status
            db_run.pages_fetched = stats.pages_fetched
            db_run.parse_success_rate = stats.parse_rate
            db_run.machines_added = stats.machines_added
            db_run.machines_updated = stats.machines_updated
            db_run.machines_unchanged = stats.machines_unchanged
            db_run.errors_json = json.dumps(stats.errors[:200])

    log.info(
        "scrape finished",
        mode=mode,
        status=status,
        canary=verdict.reason,
        parse_rate=stats.parse_rate,
        added=stats.machines_added,
        updated=stats.machines_updated,
        unchanged=stats.machines_unchanged,
        errors=len(stats.errors),
    )

    if not verdict.ok:
        await _alert_admins(f"Scrape aborted ({mode}): {verdict.reason}")
        return stats

    if new_machine_ids:
        from pressmuenzen.services.notifications import (
            notify_admins_machines_added,
            notify_new_machines,
        )

        await notify_new_machines(new_machine_ids)
        # Admins always learn about catalogue growth, independent of any watch.
        await notify_admins_machines_added(new_machine_ids)

    return stats


async def _scrape_all(source: Source, stats: ScrapeStats, new_machine_ids: list[int]) -> None:
    regions = await source.discover_regions()
    stats.pages_fetched += 1
    for region in regions:
        try:
            topics = await source.list_topics(region)
        except Exception as exc:  # noqa: BLE001 - per-region isolation
            stats.errors.append(f"list_topics {region.name}: {exc}")
            log.warning("region listing failed", region=region.name, error=str(exc))
            continue
        for topic in topics:
            await _scrape_topic(source, region, topic, stats, new_machine_ids)


async def _scrape_topic(source, region, topic, stats, new_machine_ids) -> None:  # type: ignore[no-untyped-def]
    stats.topics_seen += 1
    try:
        machine = await source.fetch_machine(topic, region)
    except Exception as exc:  # noqa: BLE001 - per-topic isolation
        stats.errors.append(f"fetch {topic.url}: {exc}")
        log.warning("topic fetch failed", url=topic.url, error=str(exc))
        return
    if machine is None or not machine.is_location_entry:
        return
    stats.topics_parsed += 1
    await _upsert_machine(machine, stats, new_machine_ids)


async def _upsert_machine(
    machine: ScrapedMachine, stats: ScrapeStats, new_machine_ids: list[int]
) -> bool:
    """Insert or update one machine. Returns True if newly inserted."""
    content_hash = _content_hash(machine)

    async with session_scope() as session:
        repo = MachineRepository(session)
        existing = await repo.get_by_url(machine.source_url)

        if existing is not None:
            existing.last_seen_at = func.now()
            if existing.content_hash == content_hash:
                stats.machines_unchanged += 1
                return False
            # Changed: refresh fields and re-derive coordinates.
            existing.name = machine.name
            existing.description = machine.description
            existing.entry_date_text = machine.entry_date_text
            existing.content_hash = content_hash
            await session.flush()
            await _derive_coordinates(repo, session, existing.id, machine)
            stats.machines_updated += 1
            return False

        region_row = await repo.upsert_region(
            machine.region.forum_url, machine.region.name, machine.region.is_limited_section
        )
        new_id = await repo.next_id()
        session.add(
            Machine(
                id=new_id,
                source_url=machine.source_url,
                name=machine.name,
                region_id=region_row.id,
                description=machine.description,
                entry_date_text=machine.entry_date_text,
                is_limited=machine.region.is_limited_section,
                content_hash=content_hash,
            )
        )
        await session.flush()
        await _derive_coordinates(repo, session, new_id, machine)
        stats.machines_added += 1
        new_machine_ids.append(new_id)
        return True


async def _derive_coordinates(
    repo: MachineRepository,
    session: AsyncSession,
    machine_id: int,
    machine: ScrapedMachine,
) -> None:
    """Add forum-GPS and/or geocoded candidates, then recompute precedence."""
    # 1. Forum GPS text (highest non-corrected precedence).
    if machine.gps_text:
        parsed = parse_gps_text(machine.gps_text)
        if parsed is not None:
            await repo.clear_candidates_of_source(machine_id, GpsSource.FORUM_GPS)
            await repo.add_candidate(
                machine_id,
                GpsSource.FORUM_GPS,
                Coordinate(lat=parsed.lat, lon=parsed.lon),
                raw_text=machine.gps_text,
            )

    # 2. Name geocode fallback (only if we have no forum GPS, to respect Nominatim).
    candidates = await repo.list_candidates(machine_id)
    has_forum = any(c.source is GpsSource.FORUM_GPS for c in candidates)
    if not has_forum:
        await _geocode_name(repo, session, machine_id, machine.name)

    await repo.recompute_geom(machine_id)


async def _geocode_name(
    repo: MachineRepository, session: AsyncSession, machine_id: int, name: str
) -> None:
    """Geocode the machine name: full name first, then partial-name fallbacks.

    Port of the legacy ``find_name_gps`` cascade. The full name yields a
    FULL_NAME_GEOCODE candidate; if it does not resolve, the decoration-stripped
    variants (e.g. ``Bonn "Bonnshop"`` -> ``Bonn``) yield a PARTIAL_NAME_GEOCODE
    candidate. Both source tiers are cleared up front so a re-scrape never leaves
    a stale higher-precedence candidate from a previous run masking the new one.
    On a geocoder error the enclosing transaction rolls back, so the clear is not
    persisted -- existing candidates survive a transient Nominatim outage.
    """
    await repo.clear_candidates_of_source(machine_id, GpsSource.FULL_NAME_GEOCODE)
    await repo.clear_candidates_of_source(machine_id, GpsSource.PARTIAL_NAME_GEOCODE)

    geocoder = Geocoder(session)
    queries = name_geocode_queries(name)

    coord = await geocoder.geocode(queries.full)
    if coord is not None:
        await repo.add_candidate(
            machine_id, GpsSource.FULL_NAME_GEOCODE, coord, raw_text=queries.full
        )
        return

    for partial in queries.partials:
        coord = await geocoder.geocode(partial)
        if coord is not None:
            await repo.add_candidate(
                machine_id, GpsSource.PARTIAL_NAME_GEOCODE, coord, raw_text=partial
            )
            return


async def _alert_admins(message: str) -> None:
    from pressmuenzen.services.notifications import notify_admins

    await notify_admins(message)
