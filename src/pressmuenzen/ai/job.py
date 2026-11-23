"""Nightly AI extraction job.

Picks active machines ordered by coordinate uncertainty (no coords first, then
lower-quality geocodes, then least-recently-checked), fetches their full forum
thread, sends it to the LLM, and persists extracted address candidates, opening
hours, summaries, and — for detected moves — pending correction rows.

The budget counts *LLM calls made*. A thread whose content hash is unchanged
costs one fetch but no LLM call, and the job keeps picking until the budget is
spent. Every check starts a recheck cooldown, so unchanged threads do not fill
the next runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from aiolimiter import AsyncLimiter
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pressmuenzen.ai.extract import ExtractionResult, extract_from_thread
from pressmuenzen.config import get_settings
from pressmuenzen.db.engine import session_scope
from pressmuenzen.db.models import AiExtractRun, Machine
from pressmuenzen.db.repositories.corrections import CorrectionRepository
from pressmuenzen.db.repositories.machines import MachineRepository
from pressmuenzen.domain.models import CorrectionType, GpsSource, MachineStatus
from pressmuenzen.logging import configure_logging, get_logger
from pressmuenzen.scraper.elongated_coin import ElongatedCoinSource
from pressmuenzen.scraper.geocoding import Geocoder

log = get_logger("ai.job")

# Bounds forum load (1 req/s) when many picked threads turn out unchanged.
_MAX_FETCHES_PER_BUDGET_UNIT = 2


class EmptyThreadError(Exception):
    """The fetched thread has no post text; sending it to the LLM would be rejected."""


@dataclass
class MachineOutcome:
    llm_called: bool
    candidates_added: int = 0
    corrections_enqueued: int = 0


@dataclass
class ExtractStats:
    threads_fetched: int = 0
    unchanged: int = 0
    llm_calls: int = 0
    candidates_added: int = 0
    corrections_enqueued: int = 0
    errors: list[str] = field(default_factory=list)


PickFn = Callable[[int, frozenset[int]], Awaitable[list[Machine]]]
ProcessFn = Callable[[Machine], Awaitable[MachineOutcome]]


async def run_ai_extract(budget: int | None = None) -> None:
    configure_logging()
    settings = get_settings()
    effective_budget = budget if budget is not None else settings.ai_extract_nightly_budget
    recheck_after = timedelta(days=settings.ai_extract_recheck_days)
    llm_limiter = AsyncLimiter(max_rate=settings.ai_extract_rpm, time_period=60.0)
    started_at = datetime.now(UTC)

    log.info("ai-extract started", budget=effective_budget, rpm=settings.ai_extract_rpm)

    async with session_scope() as session:
        run = AiExtractRun(status="running", budget=effective_budget)
        session.add(run)
        await session.flush()
        run_id = run.id

    async def pick(limit: int, exclude: frozenset[int]) -> list[Machine]:
        async with session_scope() as session:
            return await pick_machines(
                session, limit, exclude=exclude, now=started_at, recheck_after=recheck_after
            )

    async def extract(text: str) -> ExtractionResult:
        async with llm_limiter:
            return extract_from_thread(text)

    async with httpx.AsyncClient(timeout=30.0) as client:
        source = ElongatedCoinSource(client=client)

        async def process(machine: Machine) -> MachineOutcome:
            return await process_machine(
                machine,
                fetch_thread=source.fetch_thread_text,
                extract=extract,
                now=datetime.now(UTC),
            )

        stats = await drive_extraction(
            budget=effective_budget,
            max_fetches=effective_budget * _MAX_FETCHES_PER_BUDGET_UNIT,
            pick=pick,
            process=process,
        )

    status = "ok" if not stats.errors else "partial"
    async with session_scope() as session:
        db_run = await session.get(AiExtractRun, run_id)
        if db_run is not None:
            db_run.finished_at = datetime.now(UTC)
            db_run.status = status
            db_run.threads_fetched = stats.threads_fetched
            db_run.llm_calls_made = stats.llm_calls
            db_run.candidates_added = stats.candidates_added
            db_run.corrections_enqueued = stats.corrections_enqueued
            db_run.errors_json = json.dumps(stats.errors[:200]) if stats.errors else None

    log.info(
        "ai-extract finished",
        status=status,
        threads_fetched=stats.threads_fetched,
        unchanged=stats.unchanged,
        llm_calls=stats.llm_calls,
        candidates_added=stats.candidates_added,
        corrections_enqueued=stats.corrections_enqueued,
        errors=len(stats.errors),
    )

    from pressmuenzen.services.notifications import notify_admins

    await notify_admins(
        format_report(
            status=status,
            budget=effective_budget,
            threads_fetched=stats.threads_fetched,
            unchanged=stats.unchanged,
            llm_calls=stats.llm_calls,
            candidates_added=stats.candidates_added,
            corrections_enqueued=stats.corrections_enqueued,
            errors=stats.errors,
        )
    )


async def drive_extraction(
    *, budget: int, max_fetches: int, pick: PickFn, process: ProcessFn
) -> ExtractStats:
    """Process picked machines until ``budget`` LLM calls are made or no candidates remain."""
    stats = ExtractStats()
    # Failed machines keep their old timestamp, so without this they would be re-picked.
    attempted: set[int] = set()

    while stats.llm_calls < budget and stats.threads_fetched < max_fetches:
        batch = await pick(budget - stats.llm_calls, frozenset(attempted))
        if not batch:
            break
        for machine in batch:
            if stats.llm_calls >= budget or stats.threads_fetched >= max_fetches:
                break
            attempted.add(machine.id)
            stats.threads_fetched += 1
            try:
                outcome = await process(machine)
            except Exception as exc:  # noqa: BLE001 - per-machine isolation
                stats.errors.append(f"machine {machine.id} ({machine.source_url}): {exc}")
                log.warning("ai-extract error", machine_id=machine.id, error=str(exc))
                continue
            if outcome.llm_called:
                stats.llm_calls += 1
            else:
                stats.unchanged += 1
            stats.candidates_added += outcome.candidates_added
            stats.corrections_enqueued += outcome.corrections_enqueued

    return stats


async def process_machine(
    machine: Machine,
    *,
    fetch_thread: Callable[[str], Awaitable[tuple[str, int]]],
    extract: Callable[[str], Awaitable[ExtractionResult]],
    now: datetime,
) -> MachineOutcome:
    """Fetch one thread and run the LLM on it unless its content is unchanged.

    Raises EmptyThreadError after recording the check, so the cooldown applies.
    """
    thread_text, msg_count = await fetch_thread(machine.source_url)
    thread_hash = _sha256(thread_text)
    empty = not thread_text.strip()

    if empty or machine.thread_content_hash == thread_hash:
        async with session_scope() as session:
            m = await session.get(Machine, machine.id)
            if m is not None:
                _persist_thread_meta(m, thread_hash, msg_count)
                m.last_ai_analyzed_at = now
        if empty:
            raise EmptyThreadError("thread has no post text")
        log.debug("thread unchanged, skipping llm", machine_id=machine.id)
        return MachineOutcome(llm_called=False)

    result = await extract(thread_text)
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
            return MachineOutcome(llm_called=True)

        _persist_thread_meta(m, thread_hash, msg_count)
        m.last_ai_analyzed_at = now
        if result.summary:
            m.ai_summary = result.summary
        if result.opening_hours is not None:
            m.opening_hours = result.opening_hours.to_json()

        added, enqueued = await _process_location(repo, corr_repo, m, result)
    return MachineOutcome(llm_called=True, candidates_added=added, corrections_enqueued=enqueued)


async def pick_machines(
    session: AsyncSession,
    limit: int,
    *,
    exclude: frozenset[int],
    now: datetime,
    recheck_after: timedelta,
) -> list[Machine]:
    """Return up to ``limit`` active machines due for a check, most uncertain first."""
    # Mirror the _PRECEDENCE dict: higher value = less reliable = process first.
    precedence_case = case(
        (Machine.gps_source == GpsSource.NONE.value, 99),
        (Machine.gps_source == GpsSource.PARTIAL_NAME_GEOCODE.value, 5),
        (Machine.gps_source == GpsSource.AI_ADDRESS_GEOCODE_LOW.value, 4),
        (Machine.gps_source == GpsSource.FULL_NAME_GEOCODE.value, 3),
        (Machine.gps_source == GpsSource.AI_ADDRESS_GEOCODE.value, 2),
        (Machine.gps_source == GpsSource.FORUM_GPS.value, 1),
        (Machine.gps_source == GpsSource.CORRECTED.value, 0),
        else_=99,
    )
    stmt = (
        select(Machine)
        .where(
            Machine.status == MachineStatus.ACTIVE,
            or_(
                Machine.last_ai_analyzed_at.is_(None),
                Machine.last_ai_analyzed_at <= now - recheck_after,
            ),
        )
        .order_by(
            precedence_case.desc(),
            Machine.last_ai_analyzed_at.asc().nulls_first(),
            Machine.id,
        )
        .limit(limit)
    )
    if exclude:
        stmt = stmt.where(Machine.id.not_in(exclude))
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def _process_location(
    repo: MachineRepository,
    corr_repo: CorrectionRepository,
    machine: Machine,
    result: ExtractionResult,
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
        # medium/high confidence → AI_ADDRESS_GEOCODE (beats name geocoding)
        # low confidence → AI_ADDRESS_GEOCODE_LOW (city-level find, below full name geocode)
        source = (
            GpsSource.AI_ADDRESS_GEOCODE
            if result.address_confidence in ("medium", "high")
            else GpsSource.AI_ADDRESS_GEOCODE_LOW
        )
        geocoder = Geocoder(repo.session)
        coord = await geocoder.geocode(result.address_value)
        if coord is not None:
            await repo.clear_candidates_of_source(machine.id, GpsSource.AI_ADDRESS_GEOCODE)
            await repo.clear_candidates_of_source(machine.id, GpsSource.AI_ADDRESS_GEOCODE_LOW)
            await repo.add_candidate(machine.id, source, coord, raw_text=result.address_value)
            await repo.recompute_geom(machine.id)
            candidates_added += 1
            log.info(
                "ai address candidate added",
                machine_id=machine.id,
                address=result.address_value,
                confidence=result.address_confidence,
                source=source.value,
            )
        else:
            log.info(
                "ai address did not geocode",
                machine_id=machine.id,
                address=result.address_value,
            )

    return candidates_added, corrections_enqueued


def format_report(
    *,
    status: str,
    budget: int,
    threads_fetched: int,
    unchanged: int,
    llm_calls: int,
    candidates_added: int,
    corrections_enqueued: int,
    errors: list[str],
) -> str:
    status_line = "OK" if status == "ok" else f"PARTIAL ({len(errors)} Fehler)"

    lines = [
        f"AI-Extract abgeschlossen — {status_line}",
        f"Threads geladen: {threads_fetched}"
        + (f" ({unchanged} unverändert, kein LLM-Aufruf)" if unchanged else ""),
        f"LLM-Aufrufe: {llm_calls}/{budget} | Neue Koordinaten: {candidates_added}"
        f" | Umzugs-Hinweise: {corrections_enqueued}",
    ]
    if corrections_enqueued:
        lines.append("→ Umzugs-Hinweise bitte über /queue prüfen und bestätigen.")
    if errors:
        lines.append("")
        lines.append("Fehler (erste 5):")
        for e in errors[:5]:
            lines.append(f"  • {e}")
        if len(errors) > 5:
            lines.append(f"  … und {len(errors) - 5} weitere (ai_extract_runs.errors_json)")
    return "\n".join(lines)


def _persist_thread_meta(machine: Machine, thread_hash: str, msg_count: int) -> None:
    machine.thread_content_hash = thread_hash
    machine.last_message_count = msg_count


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
