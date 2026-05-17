import asyncio
import logging
import sys
import os
from datetime import datetime, timezone, timedelta

# Add the project root to sys.path to allow imports from bot
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.marzban_api import marzban_api
from bot.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"

def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} — expected {expected!r}, got {actual!r}")

async def run_live_tests():
    print("\n" + "═" * 70)
    print("  HealVPN — Live Marzban Panel Integration Tests")
    print("═" * 70)
    
    test_user = f"live_test_{int(datetime.now().timestamp())}"
    
    try:
        # ─────────────────────────────────────────────────────────────
        # TEST 1: Authenticate with Live Marzban Panel
        # ─────────────────────────────────────────────────────────────
        print("1. Authenticating with Marzban...")
        token = await marzban_api.get_token()
        assert token is not None and token != "", "Authentication failed: token is empty"
        print(f"   {PASS} Successfully authenticated. Base URL: {marzban_api.base_url}")

        # ─────────────────────────────────────────────────────────────
        # TEST 2: Create a new user and verify initial properties
        # ─────────────────────────────────────────────────────────────
        print(f"2. Creating test user: {test_user}...")
        now = datetime.now(timezone.utc)
        initial_expire_ts = int((now + timedelta(days=30)).timestamp())
        
        user_res = await marzban_api.create_user(username=test_user, expire=initial_expire_ts)
        assert user_res is not None, "Failed to create user"
        assert_eq(user_res.get("username"), test_user, "Username match")
        assert_eq(user_res.get("status"), "active", "Initial status must be active")
        
        # Verify that expire time matches what we set (Marzban might have sub-second variance or exact match)
        api_expire = user_res.get("expire")
        assert abs(api_expire - initial_expire_ts) < 5, f"Initial expire mismatch: API={api_expire}, expected={initial_expire_ts}"
        print(f"   {PASS} User successfully created with correct expiration date.")

        # ─────────────────────────────────────────────────────────────
        # TEST 3: Retrieve subscription link and extract token
        # ─────────────────────────────────────────────────────────────
        print("3. Retrieving subscription link and token...")
        sub_url = user_res.get("subscription_url") or (user_res.get("links")[0] if user_res.get("links") else None)
        assert sub_url is not None, "No subscription link returned by Marzban"
        
        extracted_token = marzban_api.extract_token(sub_url)
        assert extracted_token is not None, f"Could not extract token from URL: {sub_url}"
        print(f"   {PASS} Extracted subscription token: {extracted_token[:15]}...")

        # ─────────────────────────────────────────────────────────────
        # TEST 4: Extend subscription and verify link functional validity
        # ─────────────────────────────────────────────────────────────
        print("4. Extending subscription date by 30 more days...")
        extended_expire_ts = initial_expire_ts + 30 * 24 * 3600
        
        extended_user = await marzban_api.sync_user_subscription(
            username=test_user,
            expire_ts=extended_expire_ts,
            forced_token=extracted_token
        )
        assert extended_user is not None, "Failed to sync/extend subscription"
        
        # Verify date is extended correctly
        api_extended_expire = extended_user.get("expire")
        assert abs(api_extended_expire - extended_expire_ts) < 5, f"Extended expire mismatch: API={api_extended_expire}, expected={extended_expire_ts}"
        
        # Verify subscription link & token validity
        ext_sub_url = extended_user.get("subscription_url") or (extended_user.get("links")[0] if extended_user.get("links") else None)
        
        # Form absolute URLs if relative
        from bot.config import config
        base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
        
        abs_initial_url = sub_url if not sub_url.startswith('/') else f"{base_url}{sub_url}"
        abs_ext_url = ext_sub_url if not ext_sub_url.startswith('/') else f"{base_url}{ext_sub_url}"
        
        initial_valid = await marzban_api.validate_subscription(abs_initial_url)
        extended_valid = await marzban_api.validate_subscription(abs_ext_url)
        
        assert initial_valid, "CRITICAL: Initial subscription URL stopped working after extension!"
        assert extended_valid, "CRITICAL: Extended subscription URL is not working!"
        
        print(f"   {PASS} Subscription extended. Expiration updated, both initial and new links are 100% valid!")

        # ─────────────────────────────────────────────────────────────
        # TEST 5: Auto-preservation of token validity without forced_token
        # ─────────────────────────────────────────────────────────────
        print("5. Syncing again WITHOUT passing forced_token (testing auto-extraction logic)...")
        further_expire_ts = extended_expire_ts + 15 * 24 * 3600
        
        auto_sync_user = await marzban_api.sync_user_subscription(
            username=test_user,
            expire_ts=further_expire_ts
        )
        assert auto_sync_user is not None, "Auto-sync failed"
        
        auto_expire = auto_sync_user.get("expire")
        assert abs(auto_expire - further_expire_ts) < 5, f"Further expire mismatch: API={auto_expire}, expected={further_expire_ts}"
        
        auto_sub_url = auto_sync_user.get("subscription_url") or (auto_sync_user.get("links")[0] if auto_sync_user.get("links") else None)
        abs_auto_url = auto_sub_url if not auto_sub_url.startswith('/') else f"{base_url}{auto_sub_url}"
        
        auto_valid = await marzban_api.validate_subscription(abs_auto_url)
        assert auto_valid, "CRITICAL: Auto-sync subscription URL is not working!"
        print(f"   {PASS} Auto-preservation succeeded. Subscription link is active and valid!")

        # ─────────────────────────────────────────────────────────────
        # TEST 6: Silent 404 / Non-existent user handling
        # ─────────────────────────────────────────────────────────────
        print("6. Verifying get_user behavior on non-existent user...")
        non_existent_username = f"non_existent_{int(datetime.now().timestamp())}"
        res = await marzban_api.get_user(non_existent_username)
        assert res is None, "Expected None for non-existent user"
        print(f"   {PASS} Non-existent user correctly returned None without throwing exceptions.")

        # ─────────────────────────────────────────────────────────────
        # TEST 7: Delete test user and clean up
        # ─────────────────────────────────────────────────────────────
        print(f"7. Deleting test user {test_user}...")
        del_success = await marzban_api.delete_user(test_user)
        assert del_success is True, "Failed to delete test user"
        
        # Verify the user is gone
        deleted_check = await marzban_api.get_user(test_user)
        assert deleted_check is None, "User should no longer exist after deletion"
        print(f"   {PASS} User successfully deleted. Clean-up completed.")

        print("\n" + "═" * 70)
        print(f"  🎉 ALL LIVE INTEGRATION TESTS PASSED SUCCESSFULLY!")
        print("═" * 70 + "\n")
        
    except Exception as e:
        print(f"\n   {FAIL} Live Integration Test failed with exception:")
        print(f"          {e}")
        # Clean up in case of failure
        try:
            await marzban_api.delete_user(test_user)
            print(f"   Clean-up: deleted {test_user} after failure.")
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_live_tests())
