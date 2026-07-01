"""Unit tests for name-based geocode query construction."""

from __future__ import annotations

import pytest

from pressmuenzen.domain.name_geocode import name_geocode_queries


def test_plain_name_has_no_partials() -> None:
    q = name_geocode_queries("Bonn")
    assert q.full == "Bonn"
    assert q.partials == []


def test_quoted_shop_name_falls_back_to_place() -> None:
    # The two real entries that were missing from the map.
    assert name_geocode_queries('Bonn "Bonnshop"').partials == ["Bonn"]
    assert name_geocode_queries('Edinburgh "Bonnie Scotland"').partials == ["Edinburgh"]


@pytest.mark.parametrize(
    "suffix",
    [
        "(Automat 1)",
        "[Automat 2]",
        '"Automat 3"',
        "Automat 4",
        "(automat 5)",
        "[AUTOMAT 6]",
    ],
)
def test_full_name_strips_automat_in_any_bracket_style(suffix: str) -> None:
    q = name_geocode_queries(f'Hamburg "Hamburger DOM" {suffix}')
    assert q.full == 'Hamburg "Hamburger DOM"'
    assert q.partials == ["Hamburg"]


def test_german_quotes_are_recognised() -> None:
    assert name_geocode_queries("Köln „Dom-Shop“").partials == ["Köln"]


def test_parenthesised_aside_is_a_partial() -> None:
    q = name_geocode_queries("Frankfurt (Main)")
    assert q.full == "Frankfurt (Main)"
    assert q.partials == ["Frankfurt"]


def test_both_quote_and_parens_yield_progressive_fallbacks() -> None:
    q = name_geocode_queries('Berlin "Shop" (Standort 2)')
    assert q.full == 'Berlin "Shop" (Standort 2)'
    # Drop quotes, then drop parens, then drop both -- in that order, deduped.
    # Only outer whitespace is trimmed (legacy behaviour), so inner gaps remain.
    assert q.partials == ["Berlin  (Standort 2)", 'Berlin "Shop"', "Berlin"]


def test_partials_never_duplicate_or_equal_full() -> None:
    q = name_geocode_queries("Mainz")
    assert q.full == "Mainz"
    assert q.full not in q.partials


@pytest.mark.parametrize("name", ["", "   ", '""', "()"])
def test_degenerate_names_do_not_crash(name: str) -> None:
    q = name_geocode_queries(name)
    assert isinstance(q.partials, list)
