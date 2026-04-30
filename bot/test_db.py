
import asyncio
from database import init_db, add_user
import os

async def test():
    if os.path.exists("healvpn.db"):
        os.remove("healvpn.db")
    await init_db()
    await add_user(123, "testuser", "Test User")
    print("User added")

asyncio.run(test())
