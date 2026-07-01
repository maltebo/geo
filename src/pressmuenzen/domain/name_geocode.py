"""Name-based geocode query construction.

A faithful port of the legacy ``functions.find_name_gps`` string logic, kept
pure (no network, no DB) so it can be unit-tested in isolation. The scraper
feeds these queries to the geocoder in order: the first that resolves wins, with
the *full* name producing a ``FULL_NAME_GEOCODE`` candidate and any of the
stripped fallbacks producing a ``PARTIAL_NAME_GEOCODE`` candidate.

Why fallbacks exist: forum topic titles look like ``Bonn "Bonnshop"`` or
``Edinburgh "Bonnie Scotland" (Automat 2)``. Nominatim cannot resolve the quoted
shop name, so we strip the decorations and retry with just the place part.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Drop "Automat N" disambiguators (any bracket style or bare) before geocoding
# -- they are never part of a place name. Mirrors _AUTOMAT_RE in geocoding.py.
_AUTOMAT_SUFFIX = re.compile(
    r"\[Automat\s*\d+\]"
    r"|\(Automat\s*\d+\)"
    r'|"Automat\s*\d+"'
    r"|Automat\s*\d+",
    re.IGNORECASE,
)
# The quoted shop/landmark name: straight or German opening/closing quotes.
_QUOTED = re.compile(r'["„].*["“]')
# Any parenthesised aside left after the automat suffix is removed.
_PARENS = re.compile(r"\(.*\)")


@dataclass(frozen=True, slots=True)
class NameGeocodeQueries:
    """Ordered geocode queries derived from a machine name.

    ``full`` is the cleaned full name (automat suffix stripped) and yields a
    ``FULL_NAME_GEOCODE`` candidate. ``partials`` are the decoration-stripped
    fallbacks, in priority order, each yielding a ``PARTIAL_NAME_GEOCODE``
    candidate. ``partials`` never contains the empty string, a duplicate, or a
    value equal to ``full``.
    """

    full: str
    partials: list[str]


def name_geocode_queries(name: str) -> NameGeocodeQueries:
    """Build the full-name and partial-name geocode queries for ``name``.

    Mirrors the legacy cascade: full name, then name without the quoted part,
    then without the parenthesised part, then without both.
    """
    cleaned = _AUTOMAT_SUFFIX.sub("", name).strip()
    quoted = _QUOTED.search(cleaned)
    parens = _PARENS.search(cleaned)

    partials: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate != cleaned and candidate not in partials:
            partials.append(candidate)

    if quoted:
        add(cleaned.replace(quoted.group(0), ""))
    if parens:
        without_parens = cleaned.replace(parens.group(0), "")
        add(without_parens)
        if quoted:
            add(without_parens.replace(quoted.group(0), ""))

    return NameGeocodeQueries(full=cleaned, partials=partials)
