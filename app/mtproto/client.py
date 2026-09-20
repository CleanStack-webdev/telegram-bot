"""MTProto user-session wrapper (Telethon).

Design choice: we connect *on demand* for each /all and disconnect right after, instead of holding
a permanent connection. Reasons:
  * a session must never be used by two processes at once (Telegram can invalidate it with
    AuthKeyDuplicatedError) - short-lived connections shrink the overlap window during redeploys;
  * free hosts sleep/restart, so long-lived sockets would be dropped anyway;
  * this client does not need live updates, only request/response calls.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.sessions import StringSession

log = logging.getLogger(__name__)


class SessionNotAuthorizedError(RuntimeError):
    """The stored session string is no longer valid (revoked, expired or wrong)."""


class MTProtoSession:
    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string
        self._lock = asyncio.Lock()  # one MTProto connection at a time inside this process

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[TelegramClient]:
        async with self._lock:
            client = TelegramClient(
                StringSession(self._session_string),
                self._api_id,
                self._api_hash,
                receive_updates=False,     # we only make requests, we never listen
                flood_sleep_threshold=0,   # never sleep silently; participants.py handles FloodWait
                connection_retries=3,
                retry_delay=2,
                request_retries=3,
            )
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    raise SessionNotAuthorizedError("Stored Telegram session is not authorized")
                yield client
            finally:
                await client.disconnect()
