import os
import asyncio
from telethon import TelegramClient


async def main():
    api_hash = os.environ["TG_API_HASH"]

    client = TelegramClient(
        "test_session",
        31081482,
        api_hash
    )

    await client.connect()

    print("Telegram connection:", client.is_connected())

    await client.disconnect()


asyncio.run(main())