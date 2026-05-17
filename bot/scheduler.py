import logging
import uuid
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, or_
from .models import User
from . import database as db
from .marzban_api import marzban_api
from .config import config, get_yookassa_headers
from .payment_service import process_successful_payment

notified_cache = {}

async def create_auto_payment(user_id: int, payment_method_id: str, idempotence_key: str) -> dict:
    """Create an automatic payment using saved payment method. No user interaction needed."""
    headers = get_yookassa_headers().copy()
    headers["Idempotence-Key"] = idempotence_key
    
    data = {
        "amount": {"value": "88.00", "currency": "RUB"},
        "capture": True,
        "payment_method_id": payment_method_id,
        "description": f"Автопродление HealVPN для пользователя {user_id}",
        "metadata": {"user_id": str(user_id), "plan": "auto_renew"}
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

            # Create idempotence key based on current subscription end and fail count
            sub_end_ts = int(user.subscription_ends.timestamp())
            idem_key = f"autorenew_{user.id}_{sub_end_ts}_{user.failed_payments}"

            # 1. Create auto-payment via YooKassa
            payment = await create_auto_payment(user.id, user.payment_method_id, idem_key)
            status = payment.get("status")
            payment_id = payment.get("id")

            if payment_id:
                # Add to pending payment queue for background resilience
                await db.add_pending_payment(payment_id, user.id, "auto_renew", 88.0)

            if status == "pending" and payment_id:
                # Poll a few times just in case it finishes quickly
                import asyncio
                for _ in range(3):
                    await asyncio.sleep(2)
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=get_yookassa_headers())
                        if resp.status_code == 200:
                            payment = resp.json()
                            status = payment.get("status")
                            if status != "pending":
                                break

            if status == "succeeded":
                # Ensure timezone awareness to prevent incorrect local-time timestamp conversions
                if not user.subscription_ends.tzinfo:
                    user.subscription_ends = user.subscription_ends.replace(tzinfo=timezone.utc)

                # 2. Extend/Sync in Marzban
                new_end = user.subscription_ends + timedelta(days=30)
                expire_ts = int(new_end.timestamp())
                
                forced_token = marzban_api.extract_token(user.vpn_key)
                if forced_token:
                    logging.info(f"Auto-renew: extracted forced_token {forced_token[:12]}... for user {user.id}")

                # Синхронизируем пользователя (создаст или обновит с сохранением токена)
                user_res = await marzban_api.sync_user_subscription(
                    username=str(user.id),
                    expire_ts=expire_ts,
                    forced_token=forced_token
                )
                
                if not user_res:
                    logging.error(f"Auto-renew: failed to sync user {user.id} in Marzban")
                    continue
                
                # 3. Получаем актуальный ключ и проверяем преемственность
                sub_url = user_res.get("subscription_url") or (user_res.get("links")[0] if user_res.get("links") else user.vpn_key)
                if sub_url and sub_url.startswith('/'):
                    base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
                    sub_url = f"{base_url}{sub_url}"
                
                new_key = sub_url
                
                new_token = marzban_api.extract_token(sub_url)
                
                actual_token = new_token or forced_token
                old_token = marzban_api.extract_token(user.vpn_key)
                
                if old_token and actual_token and old_token == actual_token:
                    new_key = user.vpn_key
                    logging.info(f"Auto-renew: token matched for {user.id}, preserving existing key: {user.vpn_key}")
                elif old_token and not new_token:
                    new_key = user.vpn_key
                    logging.info(f"Auto-renew: new link not sub, but old was. Preserving for {user.id}")

                # 4. Extend in DB
                success = await db.activate_subscription(
                    user_id=user.id, 
                    plan_name="Стандарт", 
                    duration_days=30, 
                    vpn_key=new_key,
                    payment_id=payment_id,
                    amount=float((payment.get("amount") or {}).get("value", 88.0)),
                    plan="auto_renew"
                )
                
                if not success:
                    logging.info(f"Auto-renew payment {payment_id} already processed for user {user.id}")
                    if payment_id:
                        await db.remove_pending_payment(payment_id)
                    continue

                await db.reset_failed_payments(user.id)
                if payment_id:
                    await db.remove_pending_payment(payment_id)
                
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
            
            elif status == "canceled":
                if payment_id:
                    await db.remove_pending_payment(payment_id)
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
    # 1. 24h Reminder (Manual only)
    # Window: 23.5 - 24.5 hours
    async with db.async_session() as session:
        now = datetime.now(timezone.utc)
        
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.auto_renew == False, # Only for manual
                User.subscription_ends >= now + timedelta(hours=23),
                User.subscription_ends <= now + timedelta(hours=24, minutes=15)
            )
        )
        for user in result.scalars().all():
            cache_key = f"{user.id}_24h"
            if cache_key in notified_cache:
                continue
            notified_cache[cache_key] = True
            
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
                    (User.subscription_ends >= now + timedelta(hours=11)) & (User.subscription_ends <= now + timedelta(hours=12, minutes=15)),
                    (User.subscription_ends >= now) & (User.subscription_ends <= now + timedelta(hours=1))
                )
            )
        )
        for user in result.scalars().all():
            try:
                if not user.subscription_ends.tzinfo:
                    user.subscription_ends = user.subscription_ends.replace(tzinfo=timezone.utc)

                remains = user.subscription_ends - now
                
                if timedelta(hours=11) <= remains <= timedelta(hours=12, minutes=15):
                    cache_key = f"{user.id}_12h"
                    if cache_key in notified_cache: continue
                    notified_cache[cache_key] = True
                    
                    text = (
                        "⏳ *Важное уведомление (осталось 12 часов)*\n\n"
                        "До отключения VPN осталось всего 12 часов. Чтобы не остаться без любимых сервисов "
                        "в самый неподходящий момент, пожалуйста, продлите подписку в меню бота. ✨"
                    )
                    await bot.send_message(user.id, text, parse_mode="Markdown")
                    
                elif timedelta(seconds=0) <= remains <= timedelta(hours=1):
                    cache_key = f"{user.id}_30m"
                    if cache_key in notified_cache: continue
                    notified_cache[cache_key] = True
                    
                    text = (
                        "🚨 *Финальный отсчет: менее часа*\n\n"
                        "Ваша подписка HealVPN истекает совсем скоро. Скоро доступ будет ограничен. "
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

async def check_pending_payments(bot: Bot):
    """Background job: check pending YooKassa payments up to 25 mins old."""
    pending_payments = await db.get_pending_payments(max_age_minutes=25)
    if not pending_payments:
        return
        
    headers = get_yookassa_headers()
    
    async with httpx.AsyncClient() as client:
        for pp in pending_payments:
            try:
                response = await client.get(f"https://api.yookassa.ru/v3/payments/{pp.payment_id}", headers=headers)
                if response.status_code != 200:
                    logging.error(f"YooKassa API Error checking pending payment {pp.payment_id}: {response.status_code}")
                    continue
                    
                payment = response.json()
                status = payment.get("status")
                
                if status == "succeeded":
                    logging.info(f"Pending payment {pp.payment_id} succeeded! Activating...")
                    success = await process_successful_payment(
                        bot=bot,
                        user_id=pp.user_id,
                        payment_id=pp.payment_id,
                        payment=payment,
                        is_background=True
                    )
                    # Always remove from pending queue — either activated or already processed
                    await db.remove_pending_payment(pp.payment_id)
                    if success:
                        logging.info(f"Background payment {pp.payment_id} activated for user {pp.user_id}")
                    else:
                        logging.info(f"Background payment {pp.payment_id} was already processed (race condition caught)")
                elif status == "canceled":
                    # Payment definitively failed — remove from queue
                    logging.info(f"Pending payment {pp.payment_id} canceled, removing from queue")
                    await db.remove_pending_payment(pp.payment_id)
                elif status == "waiting_for_capture":
                    # 2-stage payment: needs manual capture — leave in queue, log only
                    logging.info(f"Pending payment {pp.payment_id} waiting_for_capture — leaving in queue")
                # else: still "pending" — will be rechecked next cycle
            except Exception as e:
                logging.error(f"Error checking pending payment {pp.payment_id}: {e}", exc_info=True)
                
    # Clean up very old payments that stuck
    await db.cleanup_old_pending_payments(max_age_minutes=30)

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    # Run every 15 minutes, starting right now
    now = datetime.now(timezone.utc)
    
    # Check for expired subscriptions
    scheduler.add_job(
        db.deactivate_expired_subscriptions,
        'interval',
        minutes=15,
        next_run_time=now,
        id='deactivate_expired'
    )
    
    # Check pending payments
    scheduler.add_job(
        check_pending_payments,
        'interval',
        seconds=60,
        args=[bot],
        next_run_time=now + timedelta(seconds=5),
        id='check_pending_payments'
    )
    
    # Auto-renew subscriptions
    scheduler.add_job(
        auto_renew_subscriptions,
        'interval',
        minutes=15,
        args=[bot],
        next_run_time=now + timedelta(seconds=10),
        id='auto_renew'
    )
    
    # Notify users about expiring subscriptions
    scheduler.add_job(
        notify_expiring_subscriptions,
        'interval',
        minutes=15,
        args=[bot],
        next_run_time=now + timedelta(seconds=20),
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
