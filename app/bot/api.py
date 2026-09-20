"""Minimal Telegram Bot API client (plain HTTPS). Handles 429 rate limits."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class BotApiError(RuntimeError):
    pass


class BotApi:
    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        self._base = f"https://api.telegram.org/bot{token}/"
        self._session = session

    async def call(self, method: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(1, 5):
            try:
                async with self._session.post(
                    self._base + method, json=params, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                # Deliberately log only the exception type: aiohttp messages can contain the URL,
                # and the URL contains the bot token.
                log.warning("Bot API %s network error (%s), attempt %d/4", method, type(exc).__name__, attempt)
                await asyncio.sleep(2 * attempt)
                continue

            if data.get("ok"):
                return data["result"]
            if data.get("error_code") == 429:
                wait = int(data.get("parameters", {}).get("retry_after", 5)) + 1
                log.warning("Bot API 429 on %s - waiting %ss (attempt %d/4)", method, wait, attempt)
                await asyncio.sleep(wait)
                continue
            raise BotApiError(f"{method} failed: {data.get('error_code')} {data.get('description')}")
        raise BotApiError(f"{method} failed after retries")

    # ---- thin wrappers ----
    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self.call(
            "setWebhook", url=url, secret_token=secret_token,
            allowed_updates=["message"], max_connections=5,
        )

    async def get_chat_member(self, chat_id: int, user_id: int) -> dict:
        return await self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    async def send_chat_action(self, chat_id: int, action: str, thread_id: int | None = None) -> None:
        try:
            await self.call("sendChatAction", chat_id=chat_id, action=action, message_thread_id=thread_id)
        except BotApiError:
            pass  # cosmetic only

    async def send_message(self, chat_id: int, text: str, thread_id: int | None = None) -> dict:
        return await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            message_thread_id=thread_id,
            link_preview_options={"is_disabled": True},
        )
