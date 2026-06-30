"""phpBB3 adapter for elongated-coin.de.

Faithful async port of the legacy ``functions.py`` parsing logic. The selectors
key off the phpBB template (forum titles starting with "Standorte in", the first
post's bold "Standortbeschreibung"/"GPS" spans). The parse-rate canary in the
pipeline is the early-warning system for when this template drifts.
"""

from __future__ import annotations

import re

import httpx
from aiolimiter import AsyncLimiter
from bs4 import BeautifulSoup, Tag

from pressmuenzen.config import get_settings
from pressmuenzen.logging import get_logger
from pressmuenzen.scraper.source import ScrapedMachine, ScrapedRegion, TopicRef

log = get_logger("scraper.elongated_coin")

LIMITED_SECTION_NAME = "Zeitlich begrenzte Standorte"
_PAGE_SIZE = 30
# 1 request/second to the forum, as the legacy code did. Be a polite guest.
_limiter = AsyncLimiter(max_rate=1, time_period=1.0)


class ElongatedCoinSource:
    source_id = "elongated_coin"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.scraper_base_url
        self._main_url = settings.scraper_main_forum_url
        self._ua = settings.nominatim_user_agent
        self._client = client

    async def _soup(self, url: str) -> BeautifulSoup:
        async with _limiter:
            client = self._client or httpx.AsyncClient(timeout=20.0)
            try:
                resp = await client.get(url, headers={"User-Agent": self._ua})
                resp.raise_for_status()
                return BeautifulSoup(resp.content, "html.parser")
            finally:
                if self._client is None:
                    await client.aclose()

    def _complete_link(self, link: Tag) -> str:
        href = str(link["href"]).replace("./", self._base_url)
        return re.sub("sid=.*", "start=0", href)

    # --- regions -------------------------------------------------------------

    async def discover_regions(self) -> list[ScrapedRegion]:
        soup = await self._soup(self._main_url)
        regions: list[ScrapedRegion] = []
        for row in soup.find_all("li", class_="row"):
            titles = row.find_all("a", class_="forumtitle")
            if not any(t.text.startswith("Standorte in") for t in titles):
                continue
            for sub in row.find_all("a", class_="subforum read", href=True):
                name = sub.text.strip()
                if name in ("Informationen und Download", "Treffen und Forumcoins"):
                    continue
                regions.append(
                    ScrapedRegion(
                        forum_url=self._complete_link(sub),
                        name=name,
                        is_limited_section=name == LIMITED_SECTION_NAME,
                    )
                )
        log.info("discovered regions", count=len(regions))
        return regions

    # --- topic lists ---------------------------------------------------------

    async def list_topics(self, region: ScrapedRegion) -> list[TopicRef]:
        topics: list[TopicRef] = []
        await self._collect_topics(region.forum_url, topics)
        return topics

    async def _collect_topics(self, page_url: str, acc: list[TopicRef]) -> None:
        soup = await self._soup(page_url)
        container = soup.find(lambda tag: tag.name == "div" and tag.get("class") == ["forumbg"])
        if not isinstance(container, Tag):
            return
        for link in container.find_all("a", class_="topictitle", href=True):
            acc.append(TopicRef(url=self._complete_link(link), name=link.text.strip()))
        if not self._is_last_page(soup):
            await self._collect_topics(self._next_page(page_url), acc)

    @staticmethod
    def _next_page(link: str) -> str:
        match = re.match(r".*start=(\d+)", link)
        start = int(match.group(1)) if match else 0
        return re.sub(r"start=\d+", f"start={start + _PAGE_SIZE}", link)

    @staticmethod
    def _is_last_page(soup: BeautifulSoup) -> bool:
        pages = soup.find_all("div", class_="pagination")
        if len(pages) < 1:
            return True
        words: list[str] = pages[0].text.split(" ")
        try:
            index = words.index("Seite")
        except ValueError:
            return True
        return words[index + 1].strip() == words[index + 3].strip()

    # --- full thread ---------------------------------------------------------

    async def fetch_thread_text(self, topic_url: str) -> tuple[str, int]:
        """Fetch all posts from a topic URL, including paginated replies.

        Returns (concatenated_text, post_count). Posts are separated by a
        delimiter line so the LLM can distinguish boundaries. The same 1 req/s
        limiter applies — callers must budget time accordingly.
        """
        posts: list[str] = []
        await self._collect_posts(topic_url, posts)
        return "\n\n---\n\n".join(posts), len(posts)

    async def _collect_posts(self, page_url: str, acc: list[str]) -> None:
        soup = await self._soup(page_url)
        for post in soup.find_all("div", class_=re.compile(r"post bg[12].*")):
            if not isinstance(post, Tag):
                continue
            author_tag = post.find("p", class_="author")
            author = author_tag.get_text(strip=True) if isinstance(author_tag, Tag) else ""
            content_tag = post.find("div", class_="content")
            if isinstance(content_tag, Tag):
                body = content_tag.get_text(separator="\n", strip=True)
                acc.append(f"[{author}]\n{body}")
        if not self._is_last_page(soup):
            await self._collect_posts(self._next_page(page_url), acc)

    # --- single machine ------------------------------------------------------

    async def fetch_machine(self, topic: TopicRef, region: ScrapedRegion) -> ScrapedMachine | None:
        soup = await self._soup(topic.url)
        first_post = soup.find("div", class_=re.compile(r"post bg[12].*"))
        if not isinstance(first_post, Tag):
            return None

        if not first_post.find("span", string=re.compile("Standortbeschreibung.*")):
            # Not a location entry (e.g. an announcement topic).
            return ScrapedMachine(
                source_url=topic.url,
                name=topic.name,
                region=region,
                is_location_entry=False,
            )

        description = self._location_description(first_post)
        gps_text = self._gps_text(first_post)
        entry_date = None
        author = first_post.find("p", class_="author")
        if isinstance(author, Tag) and "»" in author.text:
            entry_date = author.text.split("»")[1].strip()

        return ScrapedMachine(
            source_url=topic.url,
            name=topic.name,
            region=region,
            description=description,
            gps_text=gps_text or None,
            entry_date_text=entry_date,
        )

    @staticmethod
    def _location_description(post: Tag) -> str:
        address = post.find("span", style="font-weight: bold", string=re.compile(".*Standort.*"))
        if address is None:
            return ""
        text = ""
        node = address.next
        while node is not None and not str(node).startswith('<span style="font-weight: bold'):
            node = node.next
            if node is None:
                break
            if str(node).startswith('<span style="text-decoration: line-through'):
                node = node.next
                continue
            if not str(node).startswith("<") and node:
                text += "\n" + str(node)
        return text.strip()

    @staticmethod
    def _gps_text(post: Tag) -> str:
        gps = post.find("span", style="font-weight: bold", string=re.compile(".*GPS.*"))
        if gps is None:
            return ""
        text = ""
        node = gps.next
        while node is not None and not str(node).startswith('<span style="font-weight: bold'):
            node = node.next
            if node is None:
                break
            if str(node).startswith('<span style="text-decoration: line-through'):
                node = node.next
                continue
            if not str(node).startswith("<"):
                text += " " + str(node)
        return text.strip()
