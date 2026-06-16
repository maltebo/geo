"""Central configuration. Everything comes from the environment (12-factor).

Replaces the old ``private/private_constants.py`` (hardcoded ``ABS_PATH`` + token).
There are no path-coupled constants anymore; the app runs identically in a
container, in CI, or on a laptop given the right environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_token: str = Field(default="", alias="TELEGRAM_TOKEN")
    # Kept as a raw string: pydantic-settings would otherwise try to JSON-decode
    # a tuple/list-typed env value. Parsed into ints via the admin_chat_ids property.
    admin_chat_ids_raw: str = Field(default="", alias="ADMIN_CHAT_IDS")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://pressmuenzen:pressmuenzen@localhost:5432/pressmuenzen",
        alias="DATABASE_URL",
    )

    # Web
    public_base_url: str = Field(default="http://localhost:8000", alias="PUBLIC_BASE_URL")
    map_token_secret: str = Field(default="dev-insecure-secret", alias="MAP_TOKEN_SECRET")
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")

    # Geocoding
    nominatim_user_agent: str = Field(
        default="pressmuenzen-bot (set NOMINATIM_USER_AGENT)",
        alias="NOMINATIM_USER_AGENT",
    )

    # Scraper
    scraper_base_url: str = Field(
        default="http://www.elongated-coin.de/phpBB3/", alias="SCRAPER_BASE_URL"
    )
    scraper_main_forum_url: str = Field(
        default="http://www.elongated-coin.de/phpBB3/viewforum.php?f=126",
        alias="SCRAPER_MAIN_FORUM_URL",
    )
    scraper_canary_min_parse_rate: float = Field(
        default=0.85, alias="SCRAPER_CANARY_MIN_PARSE_RATE"
    )

    # Moderation
    # A machine the scraper has not re-seen for this many days is surfaced by the
    # admin /stale command for human review. Nothing is auto-deleted: forum threads
    # outlive the physical machine, so absence is only a hint, never a verdict.
    stale_after_days: int = Field(default=60, alias="STALE_AFTER_DAYS")

    # Logging
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def admin_chat_ids(self) -> tuple[int, ...]:
        """Parse the comma-separated ADMIN_CHAT_IDS env value into a tuple of ints."""
        return tuple(
            int(part.strip()) for part in self.admin_chat_ids_raw.split(",") if part.strip()
        )

    @property
    def public_base_url_clean(self) -> str:
        return self.public_base_url.rstrip("/")

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.admin_chat_ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Cached so the env is read once."""
    return Settings()
