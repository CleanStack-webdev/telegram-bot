"""Turn a raw Telegram update into a command call."""
from __future__ import annotations

import logging
import time

from ..deps import Deps
from .commands import COMMANDS, Context

log = logging.getLogger(__name__)
MAX_COMMAND_AGE = 600   # ignore commands queued for >10 min (e.g. while a free host was asleep)


async def handle_update(update: dict, deps: Deps) -> None:
    message = update.get("message")
    if not message:
        return

    text = message.get("text") or ""
    entity = next(
        (e for e in message.get("entities", []) if e.get("type") == "bot_command" and e.get("offset") == 0),
        None,
    )
    if entity is None:
        return

    name, _, target = text[1 : entity["length"]].partition("@")
    if target and target.lower() != deps.bot_username.lower():
        return                                          # addressed to another bot
    handler = COMMANDS.get(name.lower())
    if handler is None:
        return

    chat = message["chat"]
    allowed = deps.settings.allowed_chat_ids
    if allowed and chat["type"] != "private" and chat["id"] not in allowed:
        log.info("Ignoring command from non-whitelisted chat %s", chat["id"])
        return
    if time.time() - message.get("date", 0) > MAX_COMMAND_AGE:
        log.info("Ignoring stale command /%s", name)
        return

    try:
        await handler(Context(deps=deps, message=message))
    except Exception:
        log.exception("Command /%s crashed", name)
