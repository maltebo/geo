"""Single entrypoint. The first argument selects the process role:

python -m pressmuenzen bot
python -m pressmuenzen web
python -m pressmuenzen scrape [--mode incremental|full]
python -m pressmuenzen migrate
"""

from __future__ import annotations

import argparse
import sys

from pressmuenzen.logging import configure_logging, get_logger


def _run_migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


def _run_bot() -> None:
    from pressmuenzen.bot.app import run_bot

    run_bot()


def _run_web() -> None:
    import uvicorn

    from pressmuenzen.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "pressmuenzen.web.app:app",
        host=settings.web_host,
        port=settings.web_port,
        log_config=None,
    )


def _run_scrape(argv: list[str]) -> None:
    import asyncio

    from pressmuenzen.scraper.pipeline import run_scrape

    parser = argparse.ArgumentParser(prog="pressmuenzen scrape")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    args = parser.parse_args(argv)
    asyncio.run(run_scrape(mode=args.mode))


def main() -> None:
    configure_logging()
    log = get_logger("pressmuenzen")

    if len(sys.argv) < 2:
        print("usage: pressmuenzen {bot|web|scrape|migrate}", file=sys.stderr)
        raise SystemExit(2)

    role, rest = sys.argv[1], sys.argv[2:]
    log.info("starting", role=role)

    match role:
        case "bot":
            _run_bot()
        case "web":
            _run_web()
        case "scrape":
            _run_scrape(rest)
        case "migrate":
            _run_migrate()
        case _:
            print(f"unknown role: {role}", file=sys.stderr)
            raise SystemExit(2)


if __name__ == "__main__":
    main()
