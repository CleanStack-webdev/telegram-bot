"""Supabase persistence. supabase-py is synchronous, so calls run in a worker thread."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from supabase import Client, create_client

from .models import Member

log = logging.getLogger(__name__)
BATCH = 500


class MemberStore:
    def __init__(self, url: str, service_key: str) -> None:
        self._client: Client = create_client(url, service_key)

    async def save_snapshot(
        self,
        *,
        group_id: int,
        title: str,
        chat_type: str,
        members: list[Member],
        reported_total: int | None,
        complete: bool,
    ) -> None:
        await asyncio.to_thread(
            self._save_sync, group_id, title, chat_type, members, reported_total, complete
        )

    def _save_sync(
        self,
        group_id: int,
        title: str,
        chat_type: str,
        members: list[Member],
        reported_total: int | None,
        complete: bool,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        self._client.table("groups").upsert(
            {
                "group_id": group_id,
                "title": title,
                "chat_type": chat_type,
                "member_count": reported_total,
                "last_synced_at": now,
            },
            on_conflict="group_id",
        ).execute()

        # `discovered_at` is deliberately NOT in the payload: it is set by the column default on
        # first insert and left untouched when an existing row is updated.
        rows = [
            {
                "telegram_user_id": m.user_id,
                "group_id": group_id,
                "group_title": title,
                "first_name": m.first_name,
                "last_name": m.last_name,
                "username": m.username,
                "is_active": True,
                "last_seen_at": now,
            }
            for m in members
        ]
        for i in range(0, len(rows), BATCH):
            self._client.table("members").upsert(
                rows[i : i + BATCH], on_conflict="telegram_user_id,group_id"
            ).execute()

        # Members missing from a COMPLETE listing have left the group. Never do this after a
        # partial listing, or we would wrongly deactivate people we simply could not see.
        if complete:
            (
                self._client.table("members")
                .update({"is_active": False})
                .eq("group_id", group_id)
                .lt("last_seen_at", now)
                .execute()
            )
        log.info("Saved %d members for group %s (complete=%s)", len(rows), group_id, complete)
