"""Build Telegram HTML mentions from numeric user IDs (never from @usernames)."""
from __future__ import annotations

import html
import re
import unicodedata

from ..database.models import Member

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NAME_LEN = 32
MAX_CHARS_PER_MESSAGE = 3600   # Telegram's hard limit is 4096; keep a safety margin


def safe_name(member: Member) -> str:
    """A display name that cannot break the HTML or the message layout."""
    name = _CONTROL.sub(" ", member.display_name)
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Cf")  # drop invisible/RTL marks
    name = " ".join(name.split()) or "Member"
    return name[:MAX_NAME_LEN]


def mention_html(member: Member) -> str:
    # Example: <a href="tg://user?id=123456789">Nassim</a>
    return f'<a href="tg://user?id={int(member.user_id)}">{html.escape(safe_name(member), quote=False)}</a>'


def build_messages(
    members: list[Member],
    title: str,
    *,
    per_message: int = 20,
    max_chars: int = MAX_CHARS_PER_MESSAGE,
) -> list[str]:
    """Split the mention list into as many messages as needed. The header goes on the first one."""
    clean_title = html.escape(" ".join(title.split())[:100], quote=False)
    header = f"📢 <b>{clean_title}</b> — {len(members)} member{'s' if len(members) != 1 else ''}"

    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for member in members:
        piece = mention_html(member)
        if current and (len(current) >= per_message or length + len(piece) + 1 > max_chars):
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(piece)
        length += len(piece) + 1
    if current:
        chunks.append(" ".join(current))

    if not chunks:
        return [header]
    chunks[0] = f"{header}\n\n{chunks[0]}"
    return chunks
