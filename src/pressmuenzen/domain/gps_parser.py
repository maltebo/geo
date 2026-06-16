"""Free-text GPS coordinate parser for forum posts.

This module is a faithful, typed port of the legacy ``functions.find_gps_gps``.
It is the single most error-prone piece of the system: forum users write GPS in
dozens of incompatible notations (decimal, DMS, mixed separators, German commas,
cardinal letters before/after, etc.). The preprocessing below normalizes those
notations into something ``geopy.Point.from_string`` can parse.

The behaviour is pinned by a regression corpus of 618 real forum strings
(``tests/fixtures/gps_strings.json``) extracted from the production database.
Treat that corpus as a contract: any change here must keep every corpus entry
parsing to the same coordinate. See ``tests/unit/test_gps_parser.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from geopy import Point

# Bounds for a sane WGS84 coordinate. The forum is German/European but contains
# worldwide entries, so we only reject physically impossible values.
_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LON, _MAX_LON = -180.0, 180.0


@dataclass(frozen=True, slots=True)
class LatLon:
    """A parsed coordinate pair in decimal degrees (WGS84)."""

    lat: float
    lon: float


def parse_gps_text(gps_string: str) -> LatLon | None:
    """Parse a free-text GPS string into a :class:`LatLon`, or ``None``.

    Faithful port of the legacy parser. The long sequence of string surgery
    below intentionally mirrors the original step for step so the regression
    corpus stays valid; do not "simplify" it without re-running the corpus test.
    """
    if gps_string is None or len(gps_string) < 8:
        return None

    s = gps_string
    # Normalize unicode/typo variants of the standard DMS punctuation.
    s = s.replace("O", "E")  # German "Ost" -> East
    s = s.replace("`", "'")
    s = s.replace("′", "'")  # prime
    s = s.replace("’", "'")  # right single quote
    s = s.replace("´", "'")  # acute accent
    s = s.replace('"', "''")
    s = s.replace("″", "''")  # double prime
    s = s.replace("- ", "/ ")
    s = s.replace(";", "/")
    s = s.replace("-E", " / E")
    s = s.replace("+", "")
    s = re.sub(r"\(.*\)", "", s)
    s = re.sub(r"\[.*\]", "", s)

    # Ensure a separator between the two halves when a cardinal letter is glued on.
    if re.match(r"^[NS]", s):
        match = re.search(r"[WE]", s)
        if match:
            index = match.start()
            s = s[:index] + " " + s[index:]
    elif re.match(r".*[WE]$", s):
        match = re.search(r"[NS]", s)
        if match:
            index = match.end()
            s = s[:index] + " " + s[index:]

    if "°" in s:  # degree sign present -> DMS handling
        # Insert a minute marker (') after "DD° MM.mmm" forms missing it.
        add_dash = list(re.finditer(r"\d+°\s*\d+[.,]\d+[^'\d]", s))
        for elem in reversed(add_dash):
            index = elem.end() - 1
            s = s[:index] + "'" + s[index:]

        if re.search(r"\d+°\s*\d+[,.]\d+$", s):
            s = s + "'"

        # Insert a seconds marker ('') after "DD° MM' SS.sss" forms missing it.
        add_dash_2 = list(re.finditer(r"\d+°\s*\d+'\s*\d+[.,]?\d+[^'\d.,]", s))
        for elem in reversed(add_dash_2):
            index = elem.end() - 1
            s = s[:index] + "''" + s[index:]

        if re.search(r"\d+°\s*\d+'\s*\d+[.,]\d+$", s):
            s = s + "''"

    # German decimal commas inside a DMS field -> dots.
    wrong_commas = re.search(r"\d+(,)\d+['°]", s)
    while wrong_commas:
        index = wrong_commas.start(1)
        s = s[:index] + "." + s[index + 1 :]
        wrong_commas = re.search(r"\d+(,)\d+['°]", s)

    # Pure decimal pair using commas as the decimal sep -> dots.
    if re.fullmatch(r"[NS]?\s*\d+,\d+\s*[NS]?\s*[/ ]\s*[WE]?\s*\d+,\d+\s*[WE]?", s):
        s = s.replace(",", ".")

    # "DD MM.mmm" with a space instead of degree/minute markers.
    weird_form = re.fullmatch(
        r"[NS]?\s*(\d+)\s+([\d.]+)\s*[NS]?[\s/,]+[WE]?\s*(\d+)\s+([\d.]+)\s*[WE]?", s
    )
    if weird_form:
        i1 = weird_form.end(1)
        i2 = weird_form.end(2)
        i3 = weird_form.end(3)
        i4 = weird_form.end(4)
        s = s[:i1] + "°" + s[i1:i2] + "'" + s[i2:i3] + "°" + s[i3:i4] + "'" + s[i4:]

    # Four comma-separated integer groups: "lat_int,lat_frac,lon_int,lon_frac".
    if len(s.split(",")) == 4 and re.fullmatch(r"[0-9, ]+", s):
        p1, p2, p3, p4 = s.split(",")
        s = f"{p1.strip()}.{p2.strip()},{p3.strip()}.{p4.strip()}"

    try:
        point = Point.from_string(s)
    except ValueError:
        return None

    lat, lon = point.latitude, point.longitude
    if not (_MIN_LAT <= lat <= _MAX_LAT and _MIN_LON <= lon <= _MAX_LON):
        return None
    return LatLon(lat=lat, lon=lon)
