import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import database as db

async def check_user(user_id):
    sub = await db.get_user_subscription(user_id)
    print(f"User {user_id} sub info: {sub}")

if __name__ == "__main__":
    asyncio.run(check_user(857124130))
