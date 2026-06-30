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

_SYSTEM_PROMPT = """\
You are extracting structured information from a German forum thread about a \
Pressmuenze (elongated coin) machine. Extract exactly what the thread says — do \
not infer or hallucinate. If information is absent, set found=false or \
detected=false and leave value/new_address empty.

Fields to extract:
- address: The physical location address of the machine, if explicitly mentioned \
in any post (not just implied by the machine name). Provide full address including \
street, house number, city where available.
- moved: Whether a post explicitly states the machine has relocated to a new address.
- opening_hours: Operating hours of the machine or its host venue, if mentioned.
- summary: One to three sentences summarising the thread (German or English).
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
    import google.generativeai as genai  # lazy: only needed at runtime, not for tests

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; AI extraction is disabled")

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name=settings.gemini_model,
        system_instruction=_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    response = model.generate_content(text)
    raw = json.loads(response.text)
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
