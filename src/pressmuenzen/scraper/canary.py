"""Parse-rate canary: the early-warning system for forum HTML drift.

If the share of topics that parse cleanly drops below a threshold (vs the
trailing average of past runs), we abort the run, keep the previous data, and
alert the admin. This converts silent breakage into a notification.
"""

from __future__ import annotations

from dataclasses import dataclass

from pressmuenzen.config import get_settings


@dataclass(frozen=True, slots=True)
class CanaryVerdict:
    ok: bool
    reason: str


def check(
    parse_rate: float | None,
    trailing_rate: float | None,
    topics_seen: int,
    *,
    min_topics: int = 20,
) -> CanaryVerdict:
    """Decide whether a run's parse rate is healthy enough to commit."""
    if parse_rate is None or topics_seen < min_topics:
        # Too little data to judge -- do not abort on a tiny incremental run.
        return CanaryVerdict(ok=True, reason="insufficient sample, not gating")

    floor = get_settings().scraper_canary_min_parse_rate
    if parse_rate < floor:
        return CanaryVerdict(
            ok=False,
            reason=f"parse rate {parse_rate:.0%} below absolute floor {floor:.0%}",
        )

    if trailing_rate is not None and parse_rate < trailing_rate - 0.15:
        return CanaryVerdict(
            ok=False,
            reason=(
                f"parse rate {parse_rate:.0%} dropped >15pp below "
                f"trailing average {trailing_rate:.0%}"
            ),
        )

    return CanaryVerdict(ok=True, reason="parse rate healthy")
