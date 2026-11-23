"""Unit tests for the AI extraction job's selection loop and admin report."""

from __future__ import annotations

from pressmuenzen.ai.job import MachineOutcome, drive_extraction, format_report
from pressmuenzen.db.models import Machine


def _machines(*ids: int) -> list[Machine]:
    return [Machine(id=i, source_url=f"u{i}", name=f"M{i}") for i in ids]


class _FakePicker:
    """Serves machines from a fixed queue, honouring limit and exclusions."""

    def __init__(self, ids: list[int]) -> None:
        self.queue = _machines(*ids)
        self.calls: list[tuple[int, frozenset[int]]] = []

    async def __call__(self, limit: int, exclude: frozenset[int]) -> list[Machine]:
        self.calls.append((limit, exclude))
        return [m for m in self.queue if m.id not in exclude][:limit]


async def test_budget_counts_llm_calls_not_fetches() -> None:
    picker = _FakePicker(list(range(1, 11)))
    unchanged = {1, 2, 3}

    async def process(m: Machine) -> MachineOutcome:
        return MachineOutcome(llm_called=m.id not in unchanged)

    stats = await drive_extraction(budget=4, max_fetches=100, pick=picker, process=process)

    assert stats.llm_calls == 4
    assert stats.threads_fetched == 7
    assert stats.unchanged == 3


async def test_stops_when_no_candidates_left() -> None:
    picker = _FakePicker([1, 2])

    async def process(m: Machine) -> MachineOutcome:
        return MachineOutcome(llm_called=False)

    stats = await drive_extraction(budget=10, max_fetches=100, pick=picker, process=process)

    assert stats.threads_fetched == 2
    assert stats.llm_calls == 0


async def test_fetch_cap_bounds_forum_load() -> None:
    picker = _FakePicker(list(range(1, 100)))

    async def process(m: Machine) -> MachineOutcome:
        return MachineOutcome(llm_called=False)

    stats = await drive_extraction(budget=10, max_fetches=5, pick=picker, process=process)

    assert stats.threads_fetched == 5


async def test_failed_machine_is_not_picked_again() -> None:
    picker = _FakePicker([1, 2, 3])
    attempts: list[int] = []

    async def process(m: Machine) -> MachineOutcome:
        attempts.append(m.id)
        if m.id == 1:
            raise RuntimeError("boom")
        return MachineOutcome(llm_called=False)

    stats = await drive_extraction(budget=5, max_fetches=100, pick=picker, process=process)

    assert attempts == [1, 2, 3]
    assert stats.unchanged == 2
    assert len(stats.errors) == 1
    assert "machine 1 (u1): boom" in stats.errors[0]


async def test_outcome_counters_are_summed() -> None:
    picker = _FakePicker([1, 2])

    async def process(m: Machine) -> MachineOutcome:
        return MachineOutcome(llm_called=True, candidates_added=1, corrections_enqueued=m.id - 1)

    stats = await drive_extraction(budget=5, max_fetches=100, pick=picker, process=process)

    assert stats.candidates_added == 2
    assert stats.corrections_enqueued == 1


async def test_picker_limit_shrinks_with_remaining_budget() -> None:
    picker = _FakePicker(list(range(1, 10)))

    async def process(m: Machine) -> MachineOutcome:
        return MachineOutcome(llm_called=m.id % 2 == 0)

    await drive_extraction(budget=3, max_fetches=100, pick=picker, process=process)

    assert picker.calls[0][0] == 3
    assert all(limit <= 3 for limit, _ in picker.calls)


def test_report_shows_llm_calls_against_budget() -> None:
    text = format_report(
        status="ok",
        budget=300,
        threads_fetched=420,
        unchanged=120,
        llm_calls=300,
        candidates_added=40,
        corrections_enqueued=0,
        errors=[],
    )

    assert "Threads geladen: 420 (120 unverändert, kein LLM-Aufruf)" in text
    assert "LLM-Aufrufe: 300/300" in text


def test_report_lists_errors() -> None:
    text = format_report(
        status="partial",
        budget=300,
        threads_fetched=1,
        unchanged=0,
        llm_calls=0,
        candidates_added=0,
        corrections_enqueued=0,
        errors=["machine 1 (u1): boom"],
    )

    assert "PARTIAL (1 Fehler)" in text
    assert "machine 1 (u1): boom" in text
