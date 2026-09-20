"""Web entrypoint: receives Telegram webhooks and serves a /health endpoint."""
from __future__ import annotations

import asyncio
import hmac
import logging
from collections import OrderedDict

import aiohttp
from aiohttp import web

from .bot.api import BotApi
from .bot.handlers import handle_update
from .config import load_settings
from .database.supabase import MemberStore
from .deps import Deps
from .mtproto.client import MTProtoSession

log = logging.getLogger("app")
WEBHOOK_PATH = "/telegram/webhook"


class RecentIds:
    """Bounded set used to drop duplicate webhook deliveries."""

    def __init__(self, limit: int = 2000) -> None:
        self._items: OrderedDict[int, None] = OrderedDict()
        self._limit = limit

    def add_if_new(self, value: int) -> bool:
        if value in self._items:
            return False
        self._items[value] = None
        if len(self._items) > self._limit:
            self._items.popitem(last=False)
        return True


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def webhook(request: web.Request) -> web.Response:
    deps: Deps = request.app["deps"]
    supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied, deps.settings.webhook_secret):
        return web.Response(status=403)
    try:
        update = await request.json()
    except Exception:
        return web.Response(status=400)

    update_id = update.get("update_id")
    if update_id is not None and not request.app["seen"].add_if_new(update_id):
        return web.Response(text="duplicate")

    # Answer Telegram immediately; do the slow work in the background.
    task = asyncio.create_task(handle_update(update, deps))
    request.app["tasks"].add(task)
    task.add_done_callback(request.app["tasks"].discard)
    return web.Response(text="ok")


async def on_startup(app: web.Application) -> None:
    settings = load_settings()
    http = aiohttp.ClientSession()
    bot = BotApi(settings.bot_token, http)
    me = await bot.get_me()
    deps = Deps(
        settings=settings,
        bot=bot,
        mtproto=MTProtoSession(settings.api_id, settings.api_hash, settings.telethon_session),
        store=MemberStore(settings.supabase_url, settings.supabase_service_key),
        bot_username=me["username"],
    )
    await bot.set_webhook(settings.public_url + WEBHOOK_PATH, settings.webhook_secret)
    app["deps"], app["http"] = deps, http
    log.info("Webhook set for @%s at %s%s", me["username"], settings.public_url, WEBHOOK_PATH)


async def on_cleanup(app: web.Application) -> None:
    for task in list(app["tasks"]):
        task.cancel()
    await app["http"].close()


def create_app() -> web.Application:
    app = web.Application()
    app["tasks"] = set()
    app["seen"] = RecentIds()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post(WEBHOOK_PATH, webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    settings = load_settings()       # fail fast with a clear message if something is missing
    web.run_app(create_app(), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
