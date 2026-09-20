import os
import asyncio
from telethon import TelegramClient

API_ID = 31081482

async def main():
    api_hash = os.environ["TG_API_HASH"].strip()
    phone = input("PHONE: ").strip()

    print("API hash length:", len(api_hash))
    print("API hash format:", len(api_hash) == 32 and all(
        c in "0123456789abcdefABCDEF" for c in api_hash
    ))

    client = TelegramClient(None, API_ID, api_hash)

    try:
        await client.connect()
        print("CONNECTED:", client.is_connected())

        await client.send_code_request(phone)

        print("SEND CODE: OK")

    except Exception as e:
        print(type(e).__name__ + ":", e)

    finally:
        await client.disconnect()


asyncio.run(main())