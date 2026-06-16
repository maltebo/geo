"""One-time, idempotent migration from the legacy JSON files into PostGIS.

Reads:
  - data/url_database.json   (region structure + every raw per-source coordinate)
  - data/clean_database.json (the flattened "truth" used for the parity check)
  - private/user_data.json   (per-user visited lists; optional)

Guarantees:
  - machines.id reuses the legacy loc_ID, so existing /details <id> keeps working.
  - every coordinate flavour present becomes a coordinate_candidate, then
    precedence is recomputed -> reproducing today's chosen coordinate exactly.
  - the 2 legacy manual corrections become approved corrections + CORRECTED
    candidates.
  - a final parity check asserts the new computed geom/gps_source equals the
    legacy clean_database value for every machine.

Run:  python -m scripts.import_legacy_json   (or python scripts/import_legacy_json.py)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import delete, select

from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.geo import lat_expr, lon_expr
from pressmuenzen.db.models import (
    CoordinateCandidate,
    Correction,
    Machine,
)
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.db.repositories.users import UserRepository
from pressmuenzen.domain.models import (
    Coordinate,
    CorrectionStatus,
    CorrectionType,
    GpsSource,
)
from pressmuenzen.logging import configure_logging, get_logger

log = get_logger("import_legacy")

ROOT = Path(__file__).resolve().parent.parent
URL_DB = ROOT / "data" / "url_database.json"
CLEAN_DB = ROOT / "data" / "clean_database.json"
USER_DB = ROOT / "private" / "user_data.json"

LIMITED_SECTION_NAME = "Zeitlich begrenzte Standorte"

# Legacy coordinate-flavour key -> new GpsSource.
FLAVOURS: list[tuple[str, GpsSource]] = [
    ("corrected_gps", GpsSource.CORRECTED),
    ("gps", GpsSource.FORUM_GPS),
    ("full_name_gps", GpsSource.FULL_NAME_GEOCODE),
    ("partial_name_gps", GpsSource.PARTIAL_NAME_GEOCODE),
]

# Legacy clean-db gps_source string -> new GpsSource (for the parity check).
LEGACY_SOURCE: dict[str | None, GpsSource] = {
    "corrected_gps": GpsSource.CORRECTED,
    "gps": GpsSource.FORUM_GPS,
    "full_name_gps": GpsSource.FULL_NAME_GEOCODE,
    "partial_name_gps": GpsSource.PARTIAL_NAME_GEOCODE,
    None: GpsSource.NONE,
}


def _parse_coord(raw: str) -> Coordinate | None:
    try:
        lat_s, lon_s = raw.split(",")
        return Coordinate(lat=float(lat_s), lon=float(lon_s))
    except (ValueError, AttributeError):
        return None


async def _import_machines(repo: MachineRepository) -> None:
    db = json.loads(URL_DB.read_text(encoding="utf-8"))

    for region_url, region in db.items():
        if not isinstance(region, dict) or "location_list" not in region:
            continue  # cat_ID / loc_ID counters

        region_name = region.get("name", "").strip()
        is_limited = region_name == LIMITED_SECTION_NAME
        region_row = await repo.upsert_region(region_url, region_name, is_limited)

        for loc in region["location_list"]:
            loc_id = loc.get("loc_ID")
            if loc_id is None:
                continue

            machine = await repo.get(loc_id)
            if machine is None:
                machine = Machine(id=loc_id, source_url=loc.get("url", f"legacy:{loc_id}"))
                repo.session.add(machine)
            machine.name = loc.get("name", "")
            machine.source_url = loc.get("url", f"legacy:{loc_id}")
            machine.region_id = region_row.id
            machine.description = loc.get("location_description", "") or ""
            machine.entry_date_text = loc.get("entry_date")
            machine.is_limited = is_limited
            await repo.session.flush()

            # Reset candidates so the import is idempotent.
            await repo.session.execute(
                delete(CoordinateCandidate).where(CoordinateCandidate.machine_id == loc_id)
            )

            for key, source in FLAVOURS:
                raw = loc.get(key)
                if not raw:
                    continue
                coord = _parse_coord(raw)
                if coord is None:
                    log.warning("unparseable legacy coord", loc_id=loc_id, key=key, raw=raw)
                    continue
                await repo.add_candidate(loc_id, source, coord, raw_text=loc.get("gps_text"))

                # Carry the 2 legacy manual corrections over as approved corrections.
                if source is GpsSource.CORRECTED:
                    repo.session.add(
                        Correction(
                            machine_id=loc_id,
                            user_id=None,
                            type=CorrectionType.GPS,
                            proposed_geom=None,
                            comment="Imported legacy manual correction",
                            status=CorrectionStatus.APPROVED,
                        )
                    )

            await repo.recompute_geom(loc_id)


async def _import_users(repo: UserRepository) -> None:
    if not USER_DB.exists():
        log.info("no legacy user_data.json, skipping user import")
        return
    data = json.loads(USER_DB.read_text(encoding="utf-8"))
    for chat_id_str, chat_data in data.items():
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            continue
        await repo.get_or_create(chat_id)
        for machine_id_str in chat_data.get("visited", []):
            try:
                await repo.add_visited(chat_id, int(machine_id_str))
            except ValueError:
                continue


async def _parity_check(session) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """Assert each machine's computed geom/source matches the legacy clean db."""
    clean = json.loads(CLEAN_DB.read_text(encoding="utf-8"))

    rows = (
        await session.execute(
            select(
                Machine.id,
                Machine.gps_source,
                lat_expr(Machine.geom),
                lon_expr(Machine.geom),
            )
        )
    ).all()

    checked = 0
    mismatches = 0
    for machine_id, gps_source, lat, lon in rows:
        legacy = clean.get(str(machine_id))
        if legacy is None:
            continue
        checked += 1

        expected_source = LEGACY_SOURCE.get(legacy.get("gps_source"), GpsSource.NONE)
        if gps_source != expected_source:
            log.error(
                "parity: source mismatch",
                machine_id=machine_id,
                got=gps_source,
                expected=expected_source,
            )
            mismatches += 1
            continue

        legacy_gps = legacy.get("gps")
        if legacy_gps is None:
            if lat is not None or lon is not None:
                log.error("parity: expected no coord", machine_id=machine_id)
                mismatches += 1
            continue

        exp = _parse_coord(legacy_gps)
        if exp is None or lat is None or lon is None:
            log.error("parity: coord presence mismatch", machine_id=machine_id)
            mismatches += 1
            continue
        if abs(lat - exp.lat) > 1e-6 or abs(lon - exp.lon) > 1e-6:
            log.error(
                "parity: coord mismatch",
                machine_id=machine_id,
                got=(lat, lon),
                expected=(exp.lat, exp.lon),
            )
            mismatches += 1

    return checked, mismatches


async def main() -> None:
    configure_logging()
    async with session_scope() as session:
        machine_repo = MachineRepository(session)
        user_repo = UserRepository(session)
        await _import_machines(machine_repo)
        await _import_users(user_repo)

    async with session_scope() as session:
        checked, mismatches = await _parity_check(session)

    log.info("import complete", machines_checked=checked, parity_mismatches=mismatches)
    if mismatches:
        raise SystemExit(f"PARITY CHECK FAILED: {mismatches} mismatches out of {checked}")
    print(f"OK: {checked} machines imported and parity-verified ({mismatches} mismatches).")


if __name__ == "__main__":
    asyncio.run(main())
