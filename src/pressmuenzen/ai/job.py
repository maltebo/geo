"""Nightly AI extraction job.

Picks up to ``budget`` machines ordered by coordinate uncertainty (no coords
first, then lower-quality geocodes, then least-recently-analysed), fetches their
full forum thread, sends it to the LLM, and persists extracted address candidates,
opening hours, summaries, and — for detected moves — pending correction rows.

The budget counts *LLM calls made*, not rows picked. Threads whose content hash
is unchanged since the last analysis are skipped after a single cheap fetch, so
the budget does not erode on stale threads.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import asc, case, nulls_first, select

from pressmuenzen.ai.extract import _CONFIDENCE_RANK, ExtractionResult, extract_from_thread
from pressmuenzen.config import get_settings
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.models import AiExtractRun, Machine
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import CorrectionType, GpsSource
from pressmuenzen.logging import configure_logging, get_logger
from pressmuenzen.scraper.elongated_coin import ElongatedCoinSource
from pressmuenzen.scraper.geocoding import Geocoder

log = get_logger("ai.job")


async def run_ai_extract(budget: int | None = None) -> None:
    configure_logging()
    settings = get_settings()
    effective_budget = budget if budget is not None else settings.ai_extract_nightly_budget
    min_conf = settings.ai_extract_min_confidence

    log.info("ai-extract started", budget=effective_budget, min_confidence=min_conf)

    async with session_scope() as session:
        run = AiExtractRun(status="running", budget=effective_budget)
        session.add(run)
        await session.flush()
        run_id = run.id

    errors: list[str] = []
    threads_fetched = 0
    llm_calls = 0
    candidates_added = 0
    corrections_enqueued = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        source = ElongatedCoinSource(client=client)

        async with session_scope() as session:
            machines = await _pick_machines(session, effective_budget)

        for machine in machines:
            if llm_calls >= effective_budget:
                break
            try:
                thread_text, msg_count = await source.fetch_thread_text(machine.source_url)
                threads_fetched += 1
                thread_hash = _sha256(thread_text)

                if machine.thread_content_hash == thread_hash:
                    log.debug("thread unchanged, skipping llm", machine_id=machine.id)
                    # Still update the hash fields in case this is the first check.
                    async with session_scope() as session:
                        m = await session.get(Machine, machine.id)
                        if m is not None:
                            m.last_message_count = msg_count
                            m.thread_content_hash = thread_hash
                    continue

                result = extract_from_thread(thread_text)
                llm_calls += 1
                log.info(
                    "llm extraction done",
                    machine_id=machine.id,
                    address_found=result.address_found,
                    moved=result.moved_detected,
                    opening_hours=result.opening_hours is not None,
                )

                async with session_scope() as session:
                    repo = MachineRepository(session)
                    corr_repo = CorrectionRepository(session)
                    m = await session.get(Machine, machine.id)
                    if m is None:
                        continue

                    _persist_thread_meta(m, thread_hash, msg_count)
                    if result.summary:
                        m.ai_summary = result.summary
                    if result.opening_hours is not None:
                        m.opening_hours = result.opening_hours.to_json()

                    added, enqueued = await _process_location(repo, corr_repo, m, result, min_conf)
                    candidates_added += added
                    corrections_enqueued += enqueued

            except Exception as exc:  # noqa: BLE001 - per-machine isolation
                msg = f"machine {machine.id} ({machine.source_url}): {exc}"
                errors.append(msg)
                log.warning("ai-extract error", machine_id=machine.id, error=str(exc))

    status = "ok" if not errors else "partial"
    async with session_scope() as session:
        db_run = await session.get(AiExtractRun, run_id)
        if db_run is not None:
            db_run.finished_at = datetime.now(UTC)
            db_run.status = status
            db_run.threads_fetched = threads_fetched
            db_run.llm_calls_made = llm_calls
            db_run.candidates_added = candidates_added
            db_run.corrections_enqueued = corrections_enqueued
            db_run.errors_json = json.dumps(errors[:200]) if errors else None

    log.info(
        "ai-extract finished",
        status=status,
        threads_fetched=threads_fetched,
        llm_calls=llm_calls,
        candidates_added=candidates_added,
        corrections_enqueued=corrections_enqueued,
        errors=len(errors),
    )


async def _pick_machines(session, budget: int) -> list[Machine]:  # type: ignore[no-untyped-def]
    """Return up to ``budget`` active machines ordered by coordinate uncertainty."""
    # Precedence of gps_source values as ordinal for ordering:
    # none (99) > partial_name (4) > full_name (3) > ai_address (2) > forum_gps (1) > corrected (0)
    # We want the *least reliable* coordinates first, so ORDER BY precedence DESC (higher = less sure).
    precedence_case = case(
        (Machine.gps_source == GpsSource.NONE.value, 99),
        (Machine.gps_source == GpsSource.PARTIAL_NAME_GEOCODE.value, 4),
        (Machine.gps_source == GpsSource.FULL_NAME_GEOCODE.value, 3),
        (Machine.gps_source == GpsSource.AI_ADDRESS_GEOCODE.value, 2),
        (Machine.gps_source == GpsSource.FORUM_GPS.value, 1),
        (Machine.gps_source == GpsSource.CORRECTED.value, 0),
        else_=99,
    )
    stmt = (
        select(Machine)
        .where(Machine.status == "active")
        .order_by(
            precedence_case.desc(),
            nulls_first(asc(Machine.last_ai_analyzed_at)),
        )
        .limit(budget)
    )
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def _process_location(
    repo: MachineRepository,
    corr_repo: CorrectionRepository,
    machine: Machine,
    result: ExtractionResult,
    min_confidence: str,
) -> tuple[int, int]:
    """Apply address/move signals. Returns (candidates_added, corrections_enqueued)."""
    candidates_added = 0
    corrections_enqueued = 0

    high_quality_source = machine.gps_source in (
        GpsSource.CORRECTED.value,
        GpsSource.FORUM_GPS.value,
    )

    if result.moved_detected and result.moved_new_address and high_quality_source:
        # Possible relocation detected away from a trusted GPS point → queue for admin.
        await corr_repo.create(
            machine_id=machine.id,
            user_id=None,
            type_=CorrectionType.MOVED,
            comment=f"[AI] Thread mentions move to: {result.moved_new_address}",
        )
        corrections_enqueued += 1
        log.info("move correction enqueued", machine_id=machine.id)

    elif result.address_found and result.address_value:
        conf_rank = _CONFIDENCE_RANK.get(result.address_confidence, 0)
        min_rank = _CONFIDENCE_RANK.get(min_confidence, 1)

        if conf_rank >= min_rank:
            geocoder = Geocoder(repo.session)
            coord = await geocoder.geocode(result.address_value)
            if coord is not None:
                await repo.clear_candidates_of_source(machine.id, GpsSource.AI_ADDRESS_GEOCODE)
                await repo.add_candidate(
                    machine.id,
                    GpsSource.AI_ADDRESS_GEOCODE,
                    coord,
                    raw_text=result.address_value,
                )
                await repo.recompute_geom(machine.id)
                candidates_added += 1
                log.info(
                    "ai address candidate added",
                    machine_id=machine.id,
                    address=result.address_value,
                    confidence=result.address_confidence,
                )
            else:
                log.info(
                    "ai address did not geocode",
                    machine_id=machine.id,
                    address=result.address_value,
                )
        else:
            log.debug(
                "ai address below confidence threshold",
                machine_id=machine.id,
                confidence=result.address_confidence,
                threshold=min_confidence,
            )

    machine.last_ai_analyzed_at = datetime.now(UTC)
    return candidates_added, corrections_enqueued


def _persist_thread_meta(machine: Machine, thread_hash: str, msg_count: int) -> None:
    machine.thread_content_hash = thread_hash
    machine.last_message_count = msg_count


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
