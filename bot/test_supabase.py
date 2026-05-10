import asyncio
from database import get_supabase, add_user, get_user_subscription

async def test_connection():
    print("Testing connection to Supabase...")
    try:
        # Try to add a test user
        await add_user(user_id=123456789, username="test_user", first_name="Test")
        print("Successfully added test user.")
        
        # Try to fetch the user
        sub = await get_user_subscription(123456789)
        print(f"Successfully fetched test user subscription: {sub}")
        
        print("Supabase connection and table structure are CORRECT!")
    except Exception as e:
        print(f"Error during test: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
