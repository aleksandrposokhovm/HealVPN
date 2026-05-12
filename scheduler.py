import logging
import uuid
import base64
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
import database as db
from marzban_api import marzban_api
from config import config

def get_yookassa_headers():
    auth_str = f"{config.YOOKASSA_SHOP_ID}:{config.YOOKASSA_SECRET_KEY.get_secret_value()}"
    auth_bytes = auth_str.encode('ascii')
    base64_auth = base64.b64encode(auth_bytes).decode('ascii')
    return {
        "Authorization": f"Basic {base64_auth}",
        "Content-Type": "application/json"
    }

async def create_auto_payment(user_id: int, payment_method_id: str) -> dict:
    """Create an automatic payment using saved payment method. No user interaction needed."""
    headers = get_yookassa_headers().copy()
    headers["Idempotence-Key"] = str(uuid.uuid4())
    
    data = {
        "amount": {"value": "111.00", "currency": "RUB"},
        "capture": True,
        "payment_method_id": payment_method_id,
        "description": f"Автопродление HealVPN для пользователя {user_id}"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.yookassa.ru/v3/payments",
            json=data, headers=headers
        )
        return response.json()

async def auto_renew_subscriptions(bot: Bot):
    """Background job: auto-renew subscriptions expiring within 24 hours."""
    users = await db.get_users_for_auto_renew()
    
    if not users:
        return
    
    logging.info(f"Auto-renew: checking {len(users)} users")
    
    for user in users:
        try:
            # 1. Create auto-payment via YooKassa
            payment = await create_auto_payment(user.id, user.payment_method_id)
            
            if payment.get("status") == "succeeded":
                # 2. Extend expiry in Marzban
                from datetime import timedelta
                new_end = user.subscription_ends + timedelta(days=30)
                expire_ts = int(new_end.timestamp())
                await marzban_api.update_user_expire(str(user.id), expire_ts)
                
                # 3. Extend in DB
                await db.activate_subscription(user.id, "Стандарт", 30, user.vpn_key)
                await db.reset_failed_payments(user.id)
                
                # 4. Notify user
                try:
                    await bot.send_message(
                        user.id,
                        "✅ *Подписка автоматически продлена* на 30 дней!\n"
                        "💳 Списано: 111 ₽",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass  # User might have blocked the bot
                
                logging.info(f"Auto-renewed subscription for user {user.id}")
            
            elif payment.get("status") == "canceled":
                # Payment failed (insufficient funds, expired card, etc.)
                count = await db.increment_failed_payments(user.id)
                
                if count >= 3:
                    try:
                        await bot.send_message(
                            user.id,
                            "❌ *Не удалось продлить подписку*\n\n"
                            "Автопродление отключено после 3 неудачных попыток.\n"
                            "Продлите подписку вручную через меню бота.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    logging.warning(f"Auto-renew disabled for user {user.id} after 3 failures")
                else:
                    try:
                        await bot.send_message(
                            user.id,
                            f"⚠️ Не удалось списать 111 ₽ для продления подписки.\n"
                            f"Попытка {count}/3. Проверьте баланс карты.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    logging.warning(f"Auto-payment failed for user {user.id}, attempt {count}/3")
            else:
                # Pending or other status — will retry next hour
                logging.info(f"Auto-payment for user {user.id} has status: {payment.get('status')}")
                
        except Exception as e:
            logging.error(f"Auto-renew error for user {user.id}: {e}", exc_info=True)

async def notify_expiring_subscriptions(bot: Bot):
    """Background job: notify users whose subscription expires tomorrow."""
    users = await db.get_users_expiring_tomorrow()
    
    for user in users:
        try:
            auto_renew, has_pm = await db.get_user_auto_renew_status(user.id)
            
            if has_pm and auto_renew:
                text = (
                    "⏰ *Напоминание*\n\n"
                    "Ваша подписка HealVPN истекает завтра.\n"
                    "💳 С вашей карты будет автоматически списано *111 ₽*.\n\n"
                    "_Отключить автопродление можно в меню «Управление подпиской»._"
                )
            else:
                text = (
                    "⏰ *Напоминание*\n\n"
                    "Ваша подписка HealVPN истекает завтра.\n"
                    "Продлите подписку, чтобы не потерять доступ! 🚀"
                )
            
            await bot.send_message(user.id, text, parse_mode="Markdown")
        except Exception:
            pass  # User might have blocked the bot

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    # Check for expired subscriptions every hour
    scheduler.add_job(
        db.deactivate_expired_subscriptions,
        'interval',
        hours=1,
        id='deactivate_expired'
    )
    
    # Auto-renew subscriptions every hour
    scheduler.add_job(
        auto_renew_subscriptions,
        'interval',
        hours=1,
        args=[bot],
        id='auto_renew'
    )
    
    # Notify users about expiring subscriptions every hour
    scheduler.add_job(
        notify_expiring_subscriptions,
        'interval',
        hours=1,
        args=[bot],
        id='notify_expiring'
    )
    
    return scheduler
