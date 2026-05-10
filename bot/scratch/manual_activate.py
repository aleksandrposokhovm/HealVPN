import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from yookassa import Configuration, Payment
from config import config
import asyncio
import database as db

Configuration.account_id = config.YOOKASSA_SHOP_ID
Configuration.secret_key = config.YOOKASSA_SECRET_KEY.get_secret_value()

async def check_and_activate(payment_id):
    try:
        payment = Payment.find_one(payment_id)
        print(f"Payment ID: {payment.id}")
        print(f"Status: {payment.status}")
        print(f"Test mode: {payment.test}")
        print(f"Metadata: {payment.metadata}")
        
        if payment.status == 'succeeded':
            user_id = int(payment.metadata.get('user_id'))
            if user_id:
                print(f"Activating subscription for user {user_id}...")
                new_key = "ss://test_manual_activation@123.123.123.123:1234/?outline=1"
                await db.activate_subscription(user_id, "Стандарт", 30, new_key)
                print("Subscription activated successfully!")
            else:
                print("User ID not found in metadata.")
        else:
            print("Payment has not succeeded yet.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    payment_id = "31928dfe-000f-5000-8000-1a194e39dbaf"
    asyncio.run(check_and_activate(payment_id))
