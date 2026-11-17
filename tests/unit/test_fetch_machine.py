"""Unit tests for ElongatedCoinSource.fetch_machine() on template and free-text entries."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pressmuenzen.domain.gps_parser import parse_gps_text
from pressmuenzen.scraper import pipeline
from pressmuenzen.scraper.elongated_coin import ElongatedCoinSource
from pressmuenzen.scraper.source import ScrapedMachine, ScrapedRegion, ScrapeStats, TopicRef

FIXTURES = Path(__file__).parent.parent / "fixtures" / "forum_pages"
REGION = ScrapedRegion(
    forum_url="http://example.com/f=31", name="Rheinland-Pfalz", is_limited_section=False
)


def _source(body: bytes) -> ElongatedCoinSource:
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, content=body))
    return ElongatedCoinSource(client=httpx.AsyncClient(transport=transport, timeout=5.0))


def _post(content: str) -> bytes:
    return f"""<html><body><div class="post bg2">
        <p class="author">von <strong>Max</strong> &raquo; 01.01.2024, 10:00 </p>
        <div class="content">{content}</div>
    </div></body></html>""".encode()


@pytest.mark.asyncio
async def test_free_text_entry_with_gps_label_keeps_gps_and_description() -> None:
    body = (FIXTURES / "legacy_marksburg_first_post.html").read_bytes()
    topic = TopicRef(url="http://example.com/t=53", name='Braubach / Rhein "Marksburg"')

    machine = await _source(body).fetch_machine(topic, REGION)

    assert machine is not None
    assert not machine.matches_template
    assert machine.gps_text is not None
    coord = parse_gps_text(machine.gps_text)
    assert coord is not None
    assert coord.lat == pytest.approx(50.2723, abs=1e-3)
    assert coord.lon == pytest.approx(7.6495, abs=1e-3)
    assert "Der Automat steht in der Burg vor dem Souvenir Shop." in machine.description
    assert "Photo by" not in machine.description
    assert "Eigenarten" not in machine.description
    assert machine.entry_date_text == "14.07.2007, 22:41"


@pytest.mark.asyncio
async def test_free_text_entry_without_labels_is_still_returned() -> None:
    body = _post(
        "Er steht im Eingang zum Souvenirshop. <br />"
        '<span style="font-weight: bold"><span>Photo by HF-Penny</span></span>'
    )
    topic = TopicRef(url="http://example.com/t=215", name='Duisburg "Zoo" (Automat 3)')

    machine = await _source(body).fetch_machine(topic, REGION)

    assert machine is not None
    assert not machine.matches_template
    assert machine.description == "Er steht im Eingang zum Souvenirshop."
    assert machine.gps_text is None


@pytest.mark.asyncio
async def test_template_entry_uses_standort_section() -> None:
    body = _post(
        '<span style="font-weight: bold">Standortbeschreibung:</span> Am Bahnhof.<br />'
        '<span style="font-weight: bold">GPS:</span> 50.1, 7.2'
    )
    topic = TopicRef(url="http://example.com/t=2", name="Bonn")

    machine = await _source(body).fetch_machine(topic, REGION)

    assert machine is not None
    assert machine.matches_template
    assert machine.description == "Am Bahnhof."
    assert machine.gps_text == "50.1, 7.2"


@pytest.mark.asyncio
async def test_pipeline_persists_free_text_entry_but_excludes_it_from_parse_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upserted: list[ScrapedMachine] = []

    async def _fake_upsert(machine: ScrapedMachine, *_args: object) -> bool:
        upserted.append(machine)
        return True

    monkeypatch.setattr(pipeline, "_upsert_machine", _fake_upsert)
    body = (FIXTURES / "legacy_marksburg_first_post.html").read_bytes()
    topic = TopicRef(url="http://example.com/t=53", name='Braubach / Rhein "Marksburg"')
    stats = ScrapeStats()

    await pipeline._scrape_topic(_source(body), REGION, topic, stats, [])

    assert [m.source_url for m in upserted] == [topic.url]
    assert stats.topics_seen == 1
    assert stats.topics_parsed == 0
