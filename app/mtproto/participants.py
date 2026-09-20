"""Retrieve group participants through MTProto (the part the Bot API cannot do).

Supergroups / gigagroups -> channels.getParticipants, paginated by offset.
Basic groups             -> messages.getFullChat (returns the whole member list in one call).
"""
from __future__ import annotations

import asyncio
import logging
import string
from dataclasses import dataclass, field

from telethon import TelegramClient, errors
from telethon.tl import types
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantsRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types.channels import ChannelParticipants

from ..database.models import Member

log = logging.getLogger(__name__)

PAGE_SIZE = 200          # server-side maximum per channels.getParticipants call
PAGE_DELAY = 0.5         # polite pause between pages so we never hammer Telegram
MAX_ATTEMPTS = 5

# Name-search alphabet used ONLY when the plain listing is incomplete. Telegram's search matches
# the start of first/last names and usernames, so we cover Latin, digits, French accents,
# Arabic and Cyrillic letters.
SEARCH_ALPHABET: list[str] = (
    list(string.ascii_lowercase)
    + list(string.digits)
    + list("àâçéèêëîïôùûüœ")
    + list("ابتثجحخدذرزسشصضطظعغفقكلمنهوية")
    + list("абвгдежзийклмнопрстуфхцчшщыэюя")
)

_TRANSIENT = (
    errors.ServerError,
    errors.RpcCallFailError,
    errors.RpcMcgetFailError,
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
)


class GroupAccessError(Exception):
    """Something the group owner can fix. str(exc) is safe to show in the chat."""


class RateLimitedError(GroupAccessError):
    """Telegram asked us to wait longer than we are willing to."""


@dataclass
class ParticipantsResult:
    title: str
    chat_type: str                       # "supergroup" | "basic_group"
    members: list[Member]
    reported_total: int | None           # what Telegram says the group contains
    retrieved_total: int                 # raw participants we actually received (incl. bots/deleted)
    complete: bool
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# low-level helper: FloodWait + transient-error handling
# --------------------------------------------------------------------------------------
async def _rpc(client: TelegramClient, request, max_flood_wait: int):
    backoff = 2.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await client(request)
        except errors.FloodWaitError as exc:
            wait = exc.seconds + 1
            if wait > max_flood_wait:
                log.error("FloodWait of %ss exceeds our limit of %ss - giving up", exc.seconds, max_flood_wait)
                raise RateLimitedError(
                    f"Telegram is rate-limiting the helper account (asked us to wait {exc.seconds}s). "
                    "Please try again later."
                ) from exc
            log.warning(
                "FloodWait: sleeping %ss before retrying %s (attempt %d/%d)",
                wait, type(request).__name__, attempt, MAX_ATTEMPTS,
            )
            await asyncio.sleep(wait)
        except _TRANSIENT as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            log.warning(
                "Transient error %s on %s - retry %d/%d in %.0fs",
                type(exc).__name__, type(request).__name__, attempt, MAX_ATTEMPTS, backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    raise RateLimitedError("Telegram kept rate-limiting the helper account. Please try again later.")


# --------------------------------------------------------------------------------------
# entity resolution
# --------------------------------------------------------------------------------------
async def _resolve_entity(client: TelegramClient, chat_id: int):
    """A fresh StringSession has an empty entity cache, so the group must be found via dialogs."""
    try:
        return await client.get_entity(chat_id)
    except ValueError:
        pass
    try:
        async for dialog in client.iter_dialogs():
            if dialog.id == chat_id:
                return dialog.entity
    except errors.FloodWaitError as exc:
        raise RateLimitedError(
            f"Telegram is rate-limiting the helper account (wait {exc.seconds}s). Try again later."
        ) from exc
    raise GroupAccessError(
        "The helper (MTProto) account is not a member of this group. "
        "Add that account to the group, then run /all again."
    )


def _participant_user_id(p) -> int | None:
    uid = getattr(p, "user_id", None)
    if uid is not None:
        return uid
    peer = getattr(p, "peer", None)
    if isinstance(peer, types.PeerUser):
        return peer.user_id
    return None


async def _paginate(client, channel, flt, sink: dict[int, types.User], max_flood_wait: int) -> None:
    """Walk one participant filter page by page until the server has nothing more to give."""
    offset = 0
    while True:
        res = await _rpc(
            client,
            GetParticipantsRequest(channel=channel, filter=flt, offset=offset, limit=PAGE_SIZE, hash=0),
            max_flood_wait,
        )
        if not isinstance(res, ChannelParticipants) or not res.participants:
            break
        users_by_id = {u.id: u for u in res.users}
        for p in res.participants:
            user = users_by_id.get(_participant_user_id(p))
            if isinstance(user, types.User):
                sink[user.id] = user
        offset += len(res.participants)
        if offset >= res.count:
            break
        await asyncio.sleep(PAGE_DELAY)


# --------------------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------------------
async def fetch_participants(
    client: TelegramClient,
    chat_id: int,
    *,
    include_bots: bool = False,
    max_flood_wait: int = 120,
) -> ParticipantsResult:
    entity = await _resolve_entity(client, chat_id)

    if isinstance(entity, types.User):
        raise GroupAccessError("This is a private chat, not a group.")
    if isinstance(entity, (types.ChatForbidden, types.ChannelForbidden, types.ChatEmpty)):
        raise GroupAccessError("The helper account no longer has access to this group.")
    if isinstance(entity, types.Channel) and not entity.megagroup and not getattr(entity, "gigagroup", False):
        raise GroupAccessError(
            "This is a broadcast channel. Telegram only lets channel admins list subscribers, "
            "and channels have no members to tag. /all supports groups and supergroups."
        )
    if isinstance(entity, types.Chat) and getattr(entity, "migrated_to", None):
        raise GroupAccessError(
            "This basic group was upgraded to a supergroup and its ID changed. "
            "Run /all from the upgraded supergroup."
        )

    title = getattr(entity, "title", "") or ""
    warnings: list[str] = []
    raw: dict[int, types.User] = {}

    if isinstance(entity, types.Chat):
        chat_type = "basic_group"
        full = await _rpc(client, GetFullChatRequest(chat_id=entity.id), max_flood_wait)
        participants = full.full_chat.participants
        if isinstance(participants, types.ChatParticipantsForbidden):
            raise GroupAccessError("Telegram does not let the helper account see this group's members.")
        ids = {p.user_id for p in participants.participants}
        raw = {u.id: u for u in full.users if u.id in ids and isinstance(u, types.User)}
        reported_total: int | None = len(ids)
    else:
        chat_type = "supergroup"
        channel = await client.get_input_entity(entity)
        full = await _rpc(client, GetFullChannelRequest(channel), max_flood_wait)
        reported_total = getattr(full.full_chat, "participants_count", None)
        hidden = bool(getattr(full.full_chat, "participants_hidden", False))
        if hidden:
            warnings.append(
                "This group hides its member list. Telegram only exposes the full list to admins, "
                "so make the helper account an admin."
            )

        try:
            await _paginate(client, channel, types.ChannelParticipantsRecent(), raw, max_flood_wait)
        except errors.ChatAdminRequiredError:
            warnings.append(
                "Telegram refused to list members for the helper account. "
                "Make the helper account an admin of the group."
            )

        if reported_total and len(raw) < reported_total:
            log.info(
                "Plain listing returned %d of %d participants - sweeping by name search",
                len(raw), reported_total,
            )
            try:
                await _paginate(client, channel, types.ChannelParticipantsAdmins(), raw, max_flood_wait)
            except errors.ChatAdminRequiredError:
                pass
            for letter in SEARCH_ALPHABET:
                if len(raw) >= reported_total:
                    break
                try:
                    await _paginate(
                        client, channel, types.ChannelParticipantsSearch(letter), raw, max_flood_wait
                    )
                except errors.ChatAdminRequiredError:
                    break
                await asyncio.sleep(PAGE_DELAY)

    complete = reported_total is None or len(raw) >= reported_total
    if not complete:
        warnings.append(
            f"Telegram reports {reported_total} members but only {len(raw)} could be retrieved "
            "(large groups are capped at roughly 10,000 visible members, and hidden member lists "
            "are only visible to admins)."
        )

    members: list[Member] = []
    for user in raw.values():
        if user.deleted or user.is_self or (user.bot and not include_bots):
            continue
        members.append(
            Member(
                user_id=user.id,
                first_name=(user.first_name or "").strip(),
                last_name=(user.last_name or None),
                username=user.username,
            )
        )
    members.sort(key=lambda m: m.display_name.casefold())

    log.info(
        "Group %s (%s): reported=%s retrieved=%d mentionable=%d complete=%s",
        chat_id, chat_type, reported_total, len(raw), len(members), complete,
    )
    return ParticipantsResult(
        title=title,
        chat_type=chat_type,
        members=members,
        reported_total=reported_total,
        retrieved_total=len(raw),
        complete=complete,
        warnings=warnings,
    )
