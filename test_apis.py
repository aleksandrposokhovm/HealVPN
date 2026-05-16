import asyncio
import logging
from bot.database import init_db, async_session, select, User
from bot.marzban_api import marzban_api

logging.basicConfig(level=logging.INFO)

async def test_all():
    print("--- Testing Database Connection ---")
    try:
        await init_db()
        async with async_session() as session:
            result = await session.execute(select(User).limit(1))
            users = result.scalars().all()
            print(f"✅ Database connected successfully. Found {len(users)} users in the limit-1 check.")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

    print("\n--- Testing Marzban API Connection ---")
    try:
        token = await marzban_api.get_token()
        if token:
            print(f"✅ Marzban connected successfully. Token obtained: {token[:10]}...")
        else:
            print("❌ Marzban connection failed: Could not get token.")
    except Exception as e:
        print(f"❌ Marzban connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_all())
