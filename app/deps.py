from __future__ import annotations

from dataclasses import dataclass

from .bot.api import BotApi
from .config import Settings
from .database.supabase import MemberStore
from .mtproto.client import MTProtoSession


@dataclass
class Deps:
    settings: Settings
    bot: BotApi
    mtproto: MTProtoSession
    store: MemberStore
    bot_username: str
