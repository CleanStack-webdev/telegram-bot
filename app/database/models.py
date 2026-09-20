from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    """A group participant. `user_id` is the identity; everything else is cosmetic."""

    user_id: int
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None

    @property
    def display_name(self) -> str:
        name = (
            self.first_name.strip()
            or (self.last_name or "").strip()
            or (self.username or "").strip()
        )
        return name or "Member"
