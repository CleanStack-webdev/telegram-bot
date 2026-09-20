import os

from telethon import TelegramClient
from telethon.sessions import StringSession


API_ID = 31081482


def main():
    api_hash = os.environ["TG_API_HASH"].strip()
    phone = input("Phone: ").strip()

    print("API hash length:", len(api_hash))

    client = TelegramClient(StringSession(), API_ID, api_hash)

    client.start(phone=phone)

    me = client.loop.run_until_complete(client.get_me())

    print(f"\nLogged in as: {me.first_name} (id {me.id})")

    print("\n=== TELETHON_SESSION (keep secret) ===")
    print(client.session.save())
    print("======================================")

    client.disconnect()


if __name__ == "__main__":
    main()