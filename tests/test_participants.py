import asyncio

import pytest
from telethon import errors
from telethon.tl import types
from telethon.tl.types.channels import ChannelParticipants

from app.mtproto import participants as P


def _user(i):
    return types.User(id=i, first_name=f"U{i}")


def _page(ids, count):
    return ChannelParticipants(
        count=count,
        participants=[types.ChannelParticipant(user_id=i, date=None) for i in ids],
        chats=[],
        users=[_user(i) for i in ids],
    )


class FakeClient:
    """Serves 450 participants in pages of 200, with one FloodWait on the second page."""

    def __init__(self):
        self.calls = 0
        self.flooded = False

    async def __call__(self, request):
        self.calls += 1
        if request.offset == 200 and not self.flooded:
            self.flooded = True
            raise errors.FloodWaitError(request=request, capture=3)
        start = request.offset
        return _page(range(start, min(start + request.limit, 450)), 450)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fast(_):
        return None
    monkeypatch.setattr(P.asyncio, "sleep", fast)


def test_pagination_collects_everyone_and_survives_floodwait():
    client, sink = FakeClient(), {}
    asyncio.run(P._paginate(client, object(), types.ChannelParticipantsRecent(), sink, max_flood_wait=60))
    assert len(sink) == 450
    assert client.flooded and client.calls == 4   # 3 pages + 1 retry


def test_floodwait_longer_than_limit_is_reported_not_hammered():
    class Always:
        async def __call__(self, request):
            raise errors.FloodWaitError(request=request, capture=500)

    with pytest.raises(P.RateLimitedError):
        asyncio.run(P._rpc(Always(), P.GetParticipantsRequest(
            channel=None, filter=types.ChannelParticipantsRecent(), offset=0, limit=200, hash=0), 120))
