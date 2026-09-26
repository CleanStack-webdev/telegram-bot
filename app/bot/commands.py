"""Command registry + command implementations.

Adding /sync, /menu, /events later = write an `async def ...(ctx)` and decorate it with
@command("name"). Nothing else needs to change.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..deps import Deps
from ..mtproto.client import SessionNotAuthorizedError
from ..mtproto.participants import GroupAccessError, fetch_participants
from .mentions import build_messages

log = logging.getLogger(__name__)

GROUP_ANONYMOUS_BOT_ID = 1087968824   # Telegram's stand-in sender for anonymous admins
SEND_DELAY = 1.3                    # seconds between messages; groups tolerate ~20 msgs/minute


@dataclass
class Context:
    deps: Deps
    message: dict

    @property
    def chat_id(self) -> int:
        return self.message["chat"]["id"]

    @property
    def chat_type(self) -> str:
        return self.message["chat"]["type"]         # private | group | supergroup | channel

    @property
    def thread_id(self) -> int | None:
        return self.message.get("message_thread_id") if self.message.get("is_topic_message") else None

    async def reply(self, text: str) -> None:
        await self.deps.bot.send_message(self.chat_id, text, self.thread_id)


Handler = Callable[[Context], Awaitable[None]]
COMMANDS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        COMMANDS[name] = fn
        return fn
    return register


# ---------------------------------------------------------------------------------------
@command("help")
@command("start")
async def cmd_help(ctx: Context) -> None:
    await ctx.reply(
        "<b>Group tagger</b>\n"
        "/all — mention every member of this group (admins only by default)\n"
        "/chatid — show this chat's ID"
    )


@command("chatid")
async def cmd_chatid(ctx: Context) -> None:
    await ctx.reply(f"Chat ID: <code>{ctx.chat_id}</code>")


# ---------------------------------------------------------------------------------------
_locks: dict[int, asyncio.Lock] = {}
_last_run: dict[int, float] = {}


async def _is_allowed(ctx: Context) -> bool:
    if ctx.deps.settings.all_permission == "everyone":
        return True
    msg = ctx.message
    sender_chat = msg.get("sender_chat") or {}
    sender_id = (msg.get("from") or {}).get("id")
    if sender_chat.get("id") == ctx.chat_id or sender_id == GROUP_ANONYmoUS_BOT_ID:
        return True                                   # anonymous admin posting as the group
    if sender_id is None:
        return False
    member = await ctx.deps.bot.get_chat_member(ctx.chat_id, sender_id)
    return member.get("status") in {"creator", "administrator"}


@command("all")
@command("tagall")
async def cmd_all(ctx: Context) -> None:
    if ctx.chat_type == "private":
        await ctx.reply("ℹ️ /all only works inside a group or supergroup. Add me to your group and run it there.")
        return
    if ctx.chat_type == "channel":
        return
    if not await _is_allowed(ctx):
        await ctx.reply("⛔ Only group admins can use /all.")
        return

    cooldown = ctx.deps.settings.all_cooldown_seconds
    lock = _locks.setdefault(ctx.chat_id, asyncio.Lock())
    if lock.locked():
        await ctx.reply("⏳ A member listing is already running for this group.")
        return
    async with lock:
        remaining = cooldown - (time.monotonic() - _last_run.get(ctx.chat_id, float("-inf")))
        if remaining > 0:
            await ctx.reply(f"⏱ Please wait {int(remaining) + 1}s before running /all again.")
            return
        _last_run[ctx.chat_id] = time.monotonic()
        await _run_all(ctx)


async def _run_all(ctx: Context) -> None:
    deps = ctx.deps
    settings = deps.settings
    await deps.bot.send_chat_action(ctx.chat_id, "typing", ctx.thread_id)

    # 1) MTProto: fetch participants (includes people who never sent a message)
    try:
        async with deps.mtproto.connected() as client:
            result = await fetch_participants(
                client,
                ctx.chat_id,
                include_bots=settings.include_bots,
                max_flood_wait=settings.max_flood_wait,
            )
    except GroupAccessError as exc:
        await ctx.reply(f"❌ {html.escape(str(exc))}")
        return
    except SessionNotAuthorizedError:
        log.critical("The Telethon session is no longer authorized - regenerate TELETHON_SESSION")
        await ctx.reply("❌ The helper account is logged out. The bot owner must generate a new session.")
        return
    except Exception:
        log.exception("Unexpected error while fetching participants")
        await ctx.reply("❌ Unexpected error while contacting Telegram. Please try again in a minute.")
        return

    if not result.members:
        await ctx.reply("No mentionable members were found.")
        return

    title = ctx.message["chat"].get("title") or result.title or "Group"

    # 2) Supabase: persistence must never block the actual mentions
    try:
        await deps.store.save_snapshot(
            group_id=ctx.chat_id,
            title=title,
            chat_type=result.chat_type,
            members=result.members,
            reported_total=result.reported_total,
            complete=result.complete,
        )
    except Exception:
        log.exception("Saving members to Supabase failed (mentions are still sent)")

    # 3) Bot API: send the mentions, split into several messages
    messages = build_messages(result.members, title, per_message=settings.mentions_per_message)
    for i, text in enumerate(messages):
        await ctx.reply(text)
        if i < len(messages) - 1:
            await asyncio.sleep(SEND_DELAY)

    for warning in result.warnings:
        await ctx.reply(f"⚠️ {html.escape(warning)}")
