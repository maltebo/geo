"""Source protocol -- the seam that keeps phpBB specifics behind an interface.

We are not building multiple sources now, but this interface means a second
source (or a forum data dump/API) is an additive change, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScrapedRegion:
    forum_url: str
    name: str
    is_limited_section: bool


@dataclass(slots=True)
class ScrapedMachine:
    source_url: str
    name: str
    region: ScrapedRegion
    description: str = ""
    gps_text: str | None = None
    entry_date_text: str | None = None
    is_location_entry: bool = True

    def content_hash_input(self) -> str:
        """Stable string used for change detection (content_hash)."""
        return "".join(
            [
                self.name.strip(),
                (self.description or "").strip(),
                (self.gps_text or "").strip(),
                (self.entry_date_text or "").strip(),
            ]
        )


@dataclass(slots=True)
class TopicRef:
    url: str
    name: str
    last_activity: datetime | None = None


class Source(Protocol):
    """A scrapable forum/data source."""

    source_id: str

    async def discover_regions(self) -> list[ScrapedRegion]: ...

    async def list_topics(self, region: ScrapedRegion) -> list[TopicRef]: ...

    async def fetch_machine(
        self, topic: TopicRef, region: ScrapedRegion
    ) -> ScrapedMachine | None: ...


@dataclass(slots=True)
class ScrapeStats:
    pages_fetched: int = 0
    topics_seen: int = 0
    topics_parsed: int = 0
    machines_added: int = 0
    machines_updated: int = 0
    machines_unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def parse_rate(self) -> float | None:
        if self.topics_seen == 0:
            return None
        return self.topics_parsed / self.topics_seen
