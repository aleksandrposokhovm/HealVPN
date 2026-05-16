import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.marzban_api import marzban_api
from datetime import datetime, timezone, timedelta

async def test_subscription_link_persistence():
    """
    Test that extending a subscription does NOT change the subscription link/token.
    This is critical for user experience.
    """
    username = f"test_persist_{int(datetime.now().timestamp())}"
    expire_ts = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    
    # 1. Initial creation
    print(f"\nCreating user {username}...")
    user_data = await marzban_api.sync_user_subscription(username, expire_ts)
    assert user_data is not None, "Failed to create user"
    
    initial_sub_url = user_data.get("subscription_url")
    assert initial_sub_url is not None, "Marzban did not return a subscription URL"
    
    initial_token = marzban_api.extract_token(initial_sub_url)
    assert initial_token is not None, "Failed to extract token from initial URL"
    
    print(f"Initial Token: {initial_token}")
    
    # 2. Extension
    print("Extending subscription...")
    new_expire_ts = expire_ts + 3600
    user_data_extended = await marzban_api.sync_user_subscription(username, new_expire_ts)
    assert user_data_extended is not None, "Failed to extend subscription"
    
    extended_sub_url = user_data_extended.get("subscription_url")
    extended_token = marzban_api.extract_token(extended_sub_url)
    
    print(f"Extended Token: {extended_token}")
    
    # Verification
    assert initial_token == extended_token, f"Token CHANGED after extension! {initial_token} -> {extended_token}"
    
    # 3. Extension with a forced token (simulating fragmented key in DB)
    print("Extending with forced token (simulating fragment)...")
    fragmented_token = initial_token
    user_data_forced = await marzban_api.sync_user_subscription(username, new_expire_ts + 3600, forced_token=fragmented_token)
    
    forced_sub_url = user_data_forced.get("subscription_url")
    forced_token_res = marzban_api.extract_token(forced_sub_url)
    
    assert forced_token_res == initial_token, "Token changed after forcing with fragmented source"
    
    # Cleanup
    await marzban_api.delete_user(username)
    print(f"Test passed and user {username} deleted.")

if __name__ == "__main__":
    asyncio.run(test_subscription_link_persistence())
