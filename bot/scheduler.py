import logging
import uuid
import base64
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from . import database as db
from .marzban_api import marzban_api
from .config import config

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
            
            elif payment.get("status") in ["canceled", "pending_capture"]: # Handle both failure and slow payments
                if user.failed_payments == 0:
                    # First failure — Give 12 hours grace period
                    from datetime import timedelta
                    
                    # Update in DB first to get the new end date
                    await db.grant_grace_period(user.id, hours=12)
                    
                    # Fetch updated user to get the exact new expiration
                    updated_sub = await db.get_user_subscription(user.id)
                    if updated_sub:
                        new_grace_end = updated_sub[1]
                        expire_ts = int(new_grace_end.timestamp())
                        await marzban_api.update_user_expire(str(user.id), expire_ts)
                    
                    text = (
                        "⚠️ *Проблема с оплатой*\n\n"
                        "К сожалению, нам не удалось списать средства за подписку с вашей карты. "
                        "Мы добавили вам **12 часов бонусного доступа**, чтобы вы не потеряли связь с любимыми сервисами. 🛡\n\n"
                        "Пожалуйста, пополните карту в течение этого времени. "
                        "Через 12 часов доступ к нашему сервису будет ограничен. Мы будем очень ждать вашего возвращения! ✨"
                    )
                    try:
                        await bot.send_message(user.id, text, parse_mode="Markdown")
                    except Exception:
                        pass
                    logging.info(f"Grace period 12h granted for user {user.id}")
                else:
                    # Second failure — Already had grace period, now deactivate
                    await db.increment_failed_payments(user.id) # will hit 2
                    # The cron job deactivate_expired_subscriptions will handle actual deactivation in DB
                    # but we can do it here too for Marzban
                    await marzban_api.update_user_expire(str(user.id), int(datetime.now(timezone.utc).timestamp()))
                    
                    try:
                        await bot.send_message(
                            user.id,
                            "❌ *Подписка не была продлена*\n\n"
                            "Повторная попытка списания не удалась. Ваш доступ к VPN ограничен.\n"
                            "Пополните карту и продлите подписку вручную в меню бота. Мы всегда вам рады! 👋",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    logging.warning(f"Auto-renew failed again for user {user.id}, stopping.")
            
        except Exception as e:
            logging.error(f"Auto-renew error for user {user.id}: {e}", exc_info=True)

async def notify_expiring_subscriptions(bot: Bot):
    """Background job: notify users whose subscription expires tomorrow or in 12 hours."""
    from datetime import datetime, timezone, timedelta
    
    # 1. Check for 24h reminders (existing logic)
    users_24h = await db.get_users_expiring_tomorrow()
    for user in users_24h:
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
            pass

    # 2. Check for 12h reminders (New requirement)
    async with db.async_session() as session:
        from sqlalchemy import select
        from .models import User
        now = datetime.now(timezone.utc)
        lower = now + timedelta(hours=11)
        upper = now + timedelta(hours=12)
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.subscription_ends >= lower,
                User.subscription_ends <= upper,
            )
        )
        users_12h = result.scalars().all()
        
        for user in users_12h:
            try:
                auto_renew, has_pm = await db.get_user_auto_renew_status(user.id)
                if has_pm and auto_renew:
                    text = (
                        "⏳ *Важное уведомление*\n\n"
                        "Пробный период (или подписка) истекает через 12 часов.\n"
                        "💳 Будет произведено автоматическое списание *111 ₽* для продления доступа на месяц.\n\n"
                        "Оставайтесь под защитой HealVPN! 🛡"
                    )
                    await bot.send_message(user.id, text, parse_mode="Markdown")
            except Exception:
                pass

async def notify_trial_available_again(bot: Bot):
    """Notify users who haven't used trial for 3 months."""
    users = await db.get_users_for_trial_reminder()
    for user in users:
        try:
            text = (
                "🎁 *Для вас снова доступен пробный период!*\n\n"
                "Прошло уже 3 месяца с вашего последнего теста, и мы приглашаем вас вернуться.\n"
                "Попробуйте HealVPN еще раз: всего **11 рублей за 7 дней**! 🚀"
            )
            await bot.send_message(user.id, text, parse_mode="Markdown")
        except Exception:
            pass

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

    # Check for new trial opportunities every 24 hours
    scheduler.add_job(
        notify_trial_available_again,
        'interval',
        hours=24,
        args=[bot],
        id='notify_trial_again'
    )
    
    return scheduler
