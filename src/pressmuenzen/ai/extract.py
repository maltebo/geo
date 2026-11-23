"""LLM-based thread extraction: address, opening hours, move detection, summary.

The narrow public interface is ``extract_from_thread(text) -> ExtractionResult``.
All provider details (Gemini free tier) are hidden here; switching to a different
provider is a one-file change.

Opening hours use a bespoke JSON spec (not OSM syntax) because it is much simpler
for the model to emit reliably:

    {
      "periods": [
        {"days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "open": "09:00", "close": "18:00"}
      ],
      "notes": "Geschlossen an Feiertagen"
    }

Days are full English names (Monday … Sunday) to avoid locale ambiguity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pressmuenzen.config import get_settings

log = logging.getLogger("pressmuenzen.ai.extract")

# Confidence levels in ascending order; used by job.py to filter below-threshold results.
_CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}

# JSON schema passed to Gemini for structured output.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "address": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "value": {"type": "string"},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["found"],
        },
        "moved": {
            "type": "object",
            "properties": {
                "detected": {"type": "boolean"},
                "new_address": {"type": "string"},
            },
            "required": ["detected"],
        },
        "opening_hours": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "periods": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "open": {"type": "string"},
                            "close": {"type": "string"},
                        },
                        "required": ["days", "open", "close"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["found"],
        },
        "summary": {"type": "string"},
    },
    "required": ["address", "moved", "opening_hours", "summary"],
}

# The address value goes unchanged into a free-form Nominatim query, so the
# prompt forces a geocoder-friendly format. The confidence levels map to
# GpsSource precedence in job.py (low = city-level only).
_SYSTEM_PROMPT = """\
You extract structured information from a German forum thread about a \
Pressmuenze (elongated coin) machine. Posts are separated by lines of "---"; \
each post starts with the author in brackets. Posts are in chronological order.

Use only what the thread says. Do not use your own knowledge to add a street, \
house number or postal code that no post gives. If information is absent, set \
found=false or detected=false and leave value/new_address empty.

## address

The location where the machine stands NOW. The value is sent directly to a \
geocoder (OpenStreetMap Nominatim), so it must be a plain search query that a \
geocoder can resolve.

Format, with each part only when the thread gives it:
  "<street> <house number>, <postal code> <city>, <country>"
If no post gives a street, use the name of the venue that hosts the machine:
  "<venue name>, <postal code> <city>, <country>"

Rules:
- Country: write the country name in German ("Deutschland", "Österreich", \
"Schweiz", "Niederlande", ...). Add it when the thread makes the country clear; \
otherwise leave it out.
- Remove everything a geocoder cannot resolve: position inside the building \
("im Eingangsbereich", "neben der Kasse", "1. OG"), directions, opening hours, \
comments, quotes.
- Write a venue name as its official name ("Zoo Leipzig", "Burg Eltz"), not as a \
description ("der Zoo dort").
- Give exactly one location. If the posts give more than one, use the most \
recent one. Ignore addresses of the operator, the seller or a company office.
- Never return only a country or a region.

confidence:
- "high": a post gives street and house number, and the city or postal code.
- "medium": a post gives a street without a house number, or a named venue \
together with its city.
- "low": a post gives only a city, district or village, or the address is \
ambiguous.

## moved

detected=true only if a post explicitly says that the machine was moved to a \
different location. A machine that was removed, replaced, or is out of order is \
not a move. Write new_address in the same format as address. If the posts \
report a move, address also contains the new location.

## opening_hours

Operating hours of the machine or its host venue, if a post gives them. Days are \
full English names ("Monday" ... "Sunday"). Times are "HH:MM", 24-hour clock. \
Put seasonal rules and exceptions into notes.

## summary

One to three sentences in German that summarise the thread.
"""


@dataclass
class OpeningHoursPeriod:
    days: list[str]
    open: str
    close: str


@dataclass
class OpeningHours:
    periods: list[OpeningHoursPeriod] = field(default_factory=list)
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "periods": [
                    {"days": p.days, "open": p.open, "close": p.close} for p in self.periods
                ],
                "notes": self.notes,
            },
            ensure_ascii=False,
        )


@dataclass
class ExtractionResult:
    address_found: bool = False
    address_value: str = ""
    address_confidence: str = "low"

    moved_detected: bool = False
    moved_new_address: str = ""

    opening_hours: OpeningHours | None = None

    summary: str = ""


def extract_from_thread(text: str) -> ExtractionResult:
    """Call the LLM and return a structured extraction result.

    Raises on API errors — callers should catch and log, then continue with
    the next machine (per-machine isolation, same as the scraper pipeline).
    """
    from google import genai  # lazy: only needed at runtime, not for tests

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; AI extraction is disabled")

    client = genai.Client(api_key=settings.gemini_api_key)
    interaction = client.interactions.create(
        model=settings.gemini_model,
        system_instruction=_SYSTEM_PROMPT,
        input=text,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": _RESPONSE_SCHEMA,
        },
    )
    raw = json.loads(str(interaction.output_text))  # type: ignore[union-attr]
    return _parse_response(raw)


def _parse_response(raw: dict) -> ExtractionResult:  # type: ignore[type-arg]
    result = ExtractionResult()

    addr = raw.get("address", {})
    result.address_found = bool(addr.get("found", False))
    result.address_value = str(addr.get("value") or "").strip()
    result.address_confidence = str(addr.get("confidence") or "low")

    moved = raw.get("moved", {})
    result.moved_detected = bool(moved.get("detected", False))
    result.moved_new_address = str(moved.get("new_address") or "").strip()

    oh = raw.get("opening_hours", {})
    if oh.get("found", False):
        periods = [
            OpeningHoursPeriod(
                days=p.get("days", []),
                open=p.get("open", ""),
                close=p.get("close", ""),
            )
            for p in oh.get("periods", [])
        ]
        result.opening_hours = OpeningHours(
            periods=periods,
            notes=str(oh.get("notes") or ""),
        )

    result.summary = str(raw.get("summary") or "").strip()
    return result
