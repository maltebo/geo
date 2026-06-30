"""Unit tests for ElongatedCoinSource.fetch_thread_text().

HTTP calls are intercepted with httpx.MockTransport so no network is required.
The HTML fragments mirror the phpBB3 structure the parser actually targets.
"""

from __future__ import annotations

import httpx
import pytest

from pressmuenzen.scraper.elongated_coin import ElongatedCoinSource


def _phpbb_page(posts: list[tuple[str, str]], is_last: bool = True) -> bytes:
    """Build a minimal phpBB3 topic page with ``posts`` as (author, body) pairs."""
    post_html = ""
    for i, (author, body) in enumerate(posts):
        bg = "bg1" if i % 2 == 0 else "bg2"
        post_html += f"""
        <div class="post {bg}">
            <p class="author">{author}</p>
            <div class="content">{body}</div>
        </div>
        """

    # Pagination block: same page number twice means last page.
    if is_last:
        pagination = '<div class="pagination">Seite 1 von 1</div>'
    else:
        # "Seite 1 von 2" — not the last page.
        pagination = '<div class="pagination">Seite 1 von 2</div>'

    return f"""
    <html><body>
    {post_html}
    {pagination}
    </body></html>
    """.encode()


def _make_source(responses: list[bytes]) -> ElongatedCoinSource:
    """Build a source backed by a sequence of canned HTTP responses."""
    calls: list[int] = [0]

    def _handler(request: httpx.Request) -> httpx.Response:
        idx = calls[0]
        calls[0] += 1
        body = responses[idx] if idx < len(responses) else responses[-1]
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return ElongatedCoinSource(client=client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_page_single_post() -> None:
    page = _phpbb_page([("Max Muster » 01.01.2024", "Automat steht am Bahnhof.")])
    source = _make_source([page])

    text, count = await source.fetch_thread_text("http://example.com/viewtopic.php?t=1&start=0")

    assert count == 1
    assert "Automat steht am Bahnhof." in text


@pytest.mark.asyncio
async def test_single_page_multiple_posts() -> None:
    page = _phpbb_page(
        [
            ("Alice » 01.01.2024", "Erster Beitrag."),
            ("Bob » 02.01.2024", "Zweiter Beitrag."),
            ("Carol » 03.01.2024", "Dritter Beitrag."),
        ]
    )
    source = _make_source([page])

    text, count = await source.fetch_thread_text("http://example.com/viewtopic.php?t=1&start=0")

    assert count == 3
    assert "Erster Beitrag." in text
    assert "Zweiter Beitrag." in text
    assert "Dritter Beitrag." in text
    # Posts are delimited
    assert "---" in text


@pytest.mark.asyncio
async def test_multi_page_concatenates_all_posts() -> None:
    page1 = _phpbb_page(
        [("Alice » 01.01.2024", "Seite 1 Post.")],
        is_last=False,
    )
    page2 = _phpbb_page(
        [("Bob » 02.01.2024", "Seite 2 Post.")],
        is_last=True,
    )
    source = _make_source([page1, page2])

    text, count = await source.fetch_thread_text("http://example.com/viewtopic.php?t=1&start=0")

    assert count == 2
    assert "Seite 1 Post." in text
    assert "Seite 2 Post." in text


@pytest.mark.asyncio
async def test_empty_page_returns_empty_string_and_zero() -> None:
    page = _phpbb_page([])
    source = _make_source([page])

    text, count = await source.fetch_thread_text("http://example.com/viewtopic.php?t=1&start=0")

    assert count == 0
    assert text == ""


@pytest.mark.asyncio
async def test_author_included_in_output() -> None:
    page = _phpbb_page([("Hans Mustermann » 15.06.2024", "Inhalt des Beitrags.")])
    source = _make_source([page])

    text, _ = await source.fetch_thread_text("http://example.com/viewtopic.php?t=1&start=0")

    assert "Hans Mustermann" in text
