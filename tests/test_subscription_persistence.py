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
    
    extended_sub_url = user_data_extended.get("subscription_url") or (user_data_extended.get("links")[0] if user_data_extended.get("links") else None)
    
    # Form absolute URLs if relative
    from bot.config import config
    base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
    abs_initial_url = initial_sub_url if not initial_sub_url.startswith('/') else f"{base_url}{initial_sub_url}"
    abs_extended_url = extended_sub_url if not extended_sub_url.startswith('/') else f"{base_url}{extended_sub_url}"
    
    print("Validating subscription URLs after step 2...")
    initial_valid_step2 = await marzban_api.validate_subscription(abs_initial_url)
    extended_valid_step2 = await marzban_api.validate_subscription(abs_extended_url)
    
    print(f"Initial URL valid after extension (step 2): {initial_valid_step2}")
    print(f"Extended URL valid (step 2): {extended_valid_step2}")
    
    assert initial_valid_step2, "CRITICAL: Initial subscription URL stopped working after extension in step 2!"
    assert extended_valid_step2, "CRITICAL: Extended subscription URL is not working!"
    
    # 3. Extension with a forced token (simulating fragmented key in DB)
    print("Extending with forced token (simulating fragment)...")
    fragmented_token = initial_token
    user_data_forced = await marzban_api.sync_user_subscription(username, new_expire_ts + 3600, forced_token=fragmented_token)
    
    forced_sub_url = user_data_forced.get("subscription_url") or (user_data_forced.get("links")[0] if user_data_forced.get("links") else None)
    
    # Form absolute URLs if relative
    from bot.config import config
    base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
    if initial_sub_url.startswith('/'):
        initial_sub_url = f"{base_url}{initial_sub_url}"
    if forced_sub_url.startswith('/'):
        forced_sub_url = f"{base_url}{forced_sub_url}"
        
    print("Validating subscription URLs...")
    initial_valid = await marzban_api.validate_subscription(initial_sub_url)
    forced_valid = await marzban_api.validate_subscription(forced_sub_url)
    
    print(f"Initial link valid after extension: {initial_valid}")
    print(f"New link valid after extension: {forced_valid}")
    
    assert initial_valid, "CRITICAL: Initial subscription URL stopped working after extension!"
    assert forced_valid, "CRITICAL: New subscription URL is not working!"
    
    # Cleanup
    await marzban_api.delete_user(username)
    print(f"Test passed and user {username} deleted.")

if __name__ == "__main__":
    asyncio.run(test_subscription_link_persistence())
