import logging
import uuid
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from . import database as db
from .marzban_api import marzban_api
from .config import config, get_yookassa_headers

async def create_auto_payment(user_id: int, payment_method_id: str) -> dict:
    """Create an automatic payment using saved payment method. No user interaction needed."""
    headers = get_yookassa_headers().copy()
    headers["Idempotence-Key"] = str(uuid.uuid4())
    
    data = {
        "amount": {"value": "88.00", "currency": "RUB"},
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
    """Background job: auto-renew subscriptions at 24h, 12h, and 30m before expiry."""
    users = await db.get_users_for_auto_renew()
    
    if not users:
        return
    
    logging.info(f"Auto-renew: checking {len(users)} users")
    
    for user in users:
        try:
            # Pre-check Marzban connection before attempting to charge
            token = await marzban_api.get_token()
            if not token:
                logging.error(f"Auto-renew skipped for {user.id} because Marzban is unreachable.")
                continue

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
                        "💳 Списано: 88 ₽",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                
                logging.info(f"Auto-renewed subscription for user {user.id}")
            
            elif payment.get("status") in ["canceled", "pending_capture"]:
                # Payment failed — handle based on attempt number
                new_fail_count = await db.increment_failed_payments(user.id)
                
                text = ""
                if new_fail_count == 1:
                    # 24h attempt failed
                    text = (
                        "❌ *Проблема с оплатой (осталось 24 часа)*\n\n"
                        "К сожалению, нам не удалось списать средства для продления вашей подписки HealVPN. "
                        "Мы попробуем совершить повторный платеж через 12 часов. "
                        "Пожалуйста, проверьте баланс вашей карты, чтобы не потерять доступ к сервису! 🛡"
                    )
                elif new_fail_count == 2:
                    # 12h attempt failed
                    text = (
                        "🚨 *Важное уведомление (осталось 12 часов)*\n\n"
                        "Повторная попытка продлить подписку не удалась. До отключения VPN осталось всего 12 часов. "
                        "Чтобы не остаться без любимых сервисов, пожалуйста, пополните карту или продлите подписку вручную в меню «Управление подпиской». ✨"
                    )
                elif new_fail_count >= 3:
                    # 30m attempt failed
                    text = (
                        "⚠️ *Доступ будет ограничен через 30 минут*\n\n"
                        "К сожалению, финальная попытка продлить подписку автоматически не удалась. "
                        "Через полчаса срок действия вашего ключа истечет и VPN перестанет работать. "
                        "Вы можете продлить подписку вручную в любой момент в меню бота. Мы будем очень вас ждать! 🛡"
                    )
                
                if text:
                    try:
                        await bot.send_message(user.id, text, parse_mode="Markdown")
                    except Exception:
                        pass
                
                logging.info(f"Auto-renew attempt {new_fail_count} failed for user {user.id}")
            
        except Exception as e:
            logging.error(f"Auto-renew error for user {user.id}: {e}", exc_info=True)

async def notify_expiring_subscriptions(bot: Bot):
    """Background job: notify users whose subscription expires in 24h, 12h, or 30m (for manual renewal)."""
    from datetime import datetime, timezone, timedelta
    
    # 1. 24h Reminder (Manual only)
    # Window: 23.5 - 24.5 hours
    async with db.async_session() as session:
        from sqlalchemy import select, or_
        from .models import User
        now = datetime.now(timezone.utc)
        
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.auto_renew == False, # Only for manual
                User.subscription_ends >= now + timedelta(hours=23, minutes=30),
                User.subscription_ends <= now + timedelta(hours=24, minutes=30)
            )
        )
        for user in result.scalars().all():
            try:
                text = (
                    "⏰ *Напоминание (осталось 24 часа)*\n\n"
                    "Ваша подписка HealVPN истекает завтра. Продлите её сейчас в меню «Управление подпиской», "
                    "чтобы не потерять стабильный доступ к любимым ресурсам и высокую скорость! 🛡🚀"
                )
                await bot.send_message(user.id, text, parse_mode="Markdown")
            except Exception: pass

    # 2. 12h and 30m Reminders (Manual only)
    async with db.async_session() as session:
        now = datetime.now(timezone.utc)
        # 12h window: 11.5 - 12.5 hours
        # 30m window: 0 - 1 hour (deactivator will handle expired)
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.auto_renew == False,
                or_(
                    (User.subscription_ends >= now + timedelta(hours=11, minutes=30)) & (User.subscription_ends <= now + timedelta(hours=12, minutes=30)),
                    (User.subscription_ends >= now) & (User.subscription_ends <= now + timedelta(hours=1))
                )
            )
        )
        for user in result.scalars().all():
            try:
                remains = user.subscription_ends - now
                if timedelta(hours=11, minutes=30) <= remains <= timedelta(hours=12, minutes=30):
                    text = (
                        "⏳ *Важное уведомление (осталось 12 часов)*\n\n"
                        "До отключения VPN осталось всего 12 часов. Чтобы не остаться без любимых сервисов "
                        "в самый неподходящий момент, пожалуйста, продлите подписку в меню бота. ✨"
                    )
                    await bot.send_message(user.id, text, parse_mode="Markdown")
                elif timedelta(seconds=0) <= remains <= timedelta(hours=1):
                    text = (
                        "🚨 *Финальный отсчет: 30 минут*\n\n"
                        "Ваша подписка HealVPN истекает совсем скоро. Через полчаса доступ будет ограничен. "
                        "Продлите его прямо сейчас в меню, чтобы не прерывать работу! 🚀"
                    )
                    await bot.send_message(user.id, text, parse_mode="Markdown")
            except Exception: pass

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
