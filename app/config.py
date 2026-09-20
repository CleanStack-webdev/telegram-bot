"""Central configuration. Every secret is read from environment variables - never hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised at startup when the environment is misconfigured."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int_set(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "").replace(" ", "")
    if not raw:
        return frozenset()
    try:
        return frozenset(int(part) for part in raw.split(",") if part)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a comma-separated list of integers") from exc


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    telethon_session: str
    supabase_url: str
    supabase_service_key: str
    webhook_secret: str
    public_url: str
    port: int
    allowed_chat_ids: frozenset[int]
    all_permission: str          # "admins" | "everyone"
    mentions_per_message: int
    all_cooldown_seconds: int
    include_bots: bool
    max_flood_wait: int          # longest FloodWait (seconds) we are willing to sit through

    def __repr__(self) -> str:   # never leak secrets through logs / tracebacks
        return "Settings(<redacted>)"


def load_settings() -> Settings:
    public_url = os.environ.get("PUBLIC_URL", "").strip() or os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not public_url:
        raise ConfigError("Set PUBLIC_URL (or deploy on Render, which provides RENDER_EXTERNAL_URL)")

    permission = os.environ.get("ALL_PERMISSION", "admins").strip().lower()
    if permission not in {"admins", "everyone"}:
        raise ConfigError("ALL_PERMISSION must be 'admins' or 'everyone'")

    return Settings(
        api_id=int(_required("API_ID")),
        api_hash=_required("API_HASH"),
        bot_token=_required("BOT_TOKEN"),
        telethon_session=_required("TELETHON_SESSION"),
        supabase_url=_required("SUPABASE_URL"),
        supabase_service_key=_required("SUPABASE_SERVICE_KEY"),
        webhook_secret=_required("WEBHOOK_SECRET"),
        public_url=public_url.rstrip("/"),
        port=_int("PORT", 10000),
        allowed_chat_ids=_int_set("ALLOWED_CHAT_IDS"),
        all_permission=permission,
        mentions_per_message=max(1, min(_int("MENTIONS_PER_MESSAGE", 20), 50)),
        all_cooldown_seconds=max(0, _int("ALL_COOLDOWN_SECONDS", 30)),
        include_bots=_bool("INCLUDE_BOTS", False),
        max_flood_wait=max(1, _int("MAX_FLOOD_WAIT_SECONDS", 120)),
    )
