import asyncio
import logging
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot import database as db
from bot.models import User, ProcessedPayment
from bot.marzban_api import marzban_api
from bot.payment_service import process_successful_payment
from bot.config import config
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def test_live_renewal_preservation():
    print("\n" + "═" * 80)
    print("  HealVPN — Standalone Live Renewal & Key Preservation Test")
    print("═" * 80)
    
    # 1. Clean up potential leftover test data
    test_user_id = 77777777
    username = str(test_user_id)
    payment_id = "test_renewal_pay_99999"
    
    print(f"[1] Cleaning up pre-existing test records for {test_user_id}...")
    await marzban_api.delete_user(username)
    
    async with db.async_session() as session:
        # Delete user
        u = (await session.execute(select(User).where(User.id == test_user_id))).scalars().first()
        if u:
            await session.delete(u)
        # Delete payment
        p = (await session.execute(select(ProcessedPayment).where(ProcessedPayment.payment_id == payment_id))).scalars().first()
        if p:
            await session.delete(p)
        await session.commit()
    
    # Clear database cache
    db.sub_cache.clear()
    
    try:
        # 2. Add user to database initially (simulate a user with an active 30-day sub)
        print(f"[2] Adding initial user {test_user_id} to database...")
        now = datetime.now(timezone.utc)
        initial_expire = now + timedelta(days=30)
        
        # Create user in Marzban first to get a valid URL
        print("    Creating user in Marzban to get initial link...")
        marzban_user = await marzban_api.sync_user_subscription(username, int(initial_expire.timestamp()))
        assert marzban_user is not None, "Failed to create user in Marzban"
        
        initial_url = marzban_user.get("subscription_url") or (marzban_user.get("links")[0] if marzban_user.get("links") else None)
        if initial_url.startswith('/'):
            base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
            initial_url = f"{base_url}{initial_url}"
            
        print(f"    Initial URL: {initial_url}")
        
        # Write to SQLite DB
        async with db.async_session() as session:
            db_user = User(
                id=test_user_id,
                username="test_renewer",
                first_name="Test Renewer User",
                subscription_ends=initial_expire,
                is_active=True,
                vpn_key=initial_url,
                auto_renew=True
            )
            session.add(db_user)
            await session.commit()
            
        print(f"    User recorded in DB with expiration: {initial_expire}")
        
        # 3. Simulate payment processing (adding 30 more days)
        print("\n[3] Simulating payment processing (adding 30 more days)...")
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(return_value=True)
        
        fake_payment = {
            "id": payment_id,
            "status": "succeeded",
            "metadata": {"user_id": str(test_user_id), "plan": "1_month"},
            "amount": {"value": "150.00"},
            "payment_method": {"id": "pm_mock_test_123"}
        }
        
        # Force a sleep of 2 seconds so that current system time is strictly different
        # from the timestamp in the initial link
        print("    Sleeping 2 seconds to ensure clock ticks forward...")
        await asyncio.sleep(2.0)
        
        # Trigger core payment activation service
        success = await process_successful_payment(
            bot=mock_bot,
            user_id=test_user_id,
            payment_id=payment_id,
            payment=fake_payment,
            is_background=False
        )
        
        assert success is True, "Payment activation service failed!"
        print("    Payment processed successfully by payment_service.")
        
        # 4. Fetch results from database and panel
        print("\n[4] Querying database and Marzban for updated states...")
        
        # A. Query SQLite database
        async with db.async_session() as session:
            updated_db_user = (await session.execute(select(User).where(User.id == test_user_id))).scalars().first()
            
        assert updated_db_user is not None, "User disappeared from database!"
        db_expire = updated_db_user.subscription_ends.replace(tzinfo=timezone.utc)
        db_vpn_key = updated_db_user.vpn_key
        
        # B. Query Marzban Panel
        updated_marzban_user = await marzban_api.get_user(username)
        assert updated_marzban_user is not None, "User disappeared from Marzban panel!"
        marzban_expire_ts = updated_marzban_user.get("expire")
        marzban_expire = datetime.fromtimestamp(marzban_expire_ts, timezone.utc)
        
        # 5. Assertions (The critical part of the test)
        print("\n[5] Executing strict assertions...")
        
        # Expected expiration date: initial_expire + 30 days
        expected_expire = initial_expire + timedelta(days=30)
        
        # Check DB Expiration
        db_diff = abs((db_expire - expected_expire).total_seconds())
        print(f"    Initial DB expiration: {initial_expire}")
        print(f"    Expected DB expiration: {expected_expire}")
        print(f"    Actual DB expiration: {db_expire} (diff: {db_diff}s)")
        assert db_diff < 5, f"Database expiration mismatch! Expected {expected_expire}, got {db_expire}"
        print(f"    {db.PASS if hasattr(db, 'PASS') else '✅'} Database expiration successfully extended by 30 days.")
        
        # Check Marzban Expiration
        marzban_diff = abs((marzban_expire - expected_expire).total_seconds())
        print(f"    Actual Marzban expiration: {marzban_expire} (diff: {marzban_diff}s)")
        assert marzban_diff < 5, f"Marzban expiration mismatch! Expected {expected_expire}, got {marzban_expire}"
        print(f"    ✅ Marzban expiration successfully extended by 30 days.")
        
        # Check VPN Key String Identity in Database
        print(f"    Initial VPN Key: {initial_url}")
        print(f"    Actual DB VPN Key: {db_vpn_key}")
        assert db_vpn_key == initial_url, "CRITICAL ERROR: Database VPN key changed after renewal!"
        print(f"    ✅ Database VPN key is 100% identical to the original key (character-by-character).")
        
        # Check Bot Keyboard Markup Link Identity
        # Look at the markup passed to bot.send_message. It should contain success payment menu with correct key.
        assert mock_bot.send_message.called, "Bot failed to send success message!"
        call_args = mock_bot.send_message.call_args
        reply_markup = call_args[1].get("reply_markup") or call_args[0][2]
        
        # Extract key from markup keyboard copy_text button
        button_key = None
        for row in reply_markup.inline_keyboard:
            for button in row:
                if hasattr(button, "copy_text") and button.copy_text:
                    button_key = button.copy_text.text
                    break
        
        print(f"    Keyboard button copy_text: {button_key}")
        assert button_key == initial_url, f"CRITICAL ERROR: The key in the copy button changed! Expected {initial_url}, got {button_key}"
        print(f"    ✅ Telegram bot copy button contains 100% identical original key (character-by-character).")
        
        print("\n" + "═" * 80)
        print("  🎉 TEST PASSED SUCCESSFULLY: DATES PERFECTLY EXTENDED & KEY COMPLETELY PRESERVED!")
        print("═" * 80 + "\n")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # 6. Cleanup
        print("[6] Cleaning up test records...")
        await marzban_api.delete_user(username)
        async with db.async_session() as session:
            # Delete user
            u = (await session.execute(select(User).where(User.id == test_user_id))).scalars().first()
            if u:
                await session.delete(u)
            # Delete payment
            p = (await session.execute(select(ProcessedPayment).where(ProcessedPayment.payment_id == payment_id))).scalars().first()
            if p:
                await session.delete(p)
            await session.commit()
        db.sub_cache.clear()
        print("    Clean-up complete.")

if __name__ == "__main__":
    asyncio.run(test_live_renewal_preservation())
