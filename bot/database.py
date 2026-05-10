from supabase import create_async_client, AsyncClient
from config import config
from marzban_api import marzban
import logging

_supabase_client = None

async def get_supabase() -> AsyncClient:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = await create_async_client(
            config.SUPABASE_URL,
            config.SUPABASE_KEY.get_secret_value()
        )
    return _supabase_client

async def init_db():
    # Supabase tables are managed via the dashboard
    pass

# Cache with 10 minute TTL for subscriptions to reduce Supabase hits
sub_cache = {}
CACHE_TTL = 600

# Cache for user existence (permanent for the session)
user_existence_cache = set()

# Pre-created Supabase client for instant access
_supabase_client = None

async def add_user(user_id: int, username: str, first_name: str):
    """Adds a user to the Supabase database or updates if they exist."""
    # Skip if we already added/updated them in this session (simple optimization)
    if user_id in user_existence_cache:
        return

    supabase = await get_supabase()
    data = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    try:
        # upsert handles "INSERT OR UPDATE" based on 'id'
        await supabase.table("Users").upsert(data).execute()
        user_existence_cache.add(user_id)
    except Exception as e:
        logging.error(f"Error adding user to Supabase: {e}")

# Subscription retrieval with caching
async def get_user_subscription(user_id: int):
    """Retrieves user subscription data with caching and fallback."""
    import time
    from datetime import datetime, timezone
    now = time.time()

    # Check cache
    if user_id in sub_cache:
        data, timestamp = sub_cache[user_id]
        if now - timestamp < CACHE_TTL:
            return data

    try:
        supabase = await get_supabase()
        response = await supabase.table("Users").select(
            "is_active", "subscription_ends", "vpn_key", "available_devices"
        ).eq("id", user_id).execute()

        if response.data:
            user_data = response.data[0]
            # Return data even if not active, so handlers can show status correctly
            res = (
                "Стандарт",
                user_data.get("subscription_ends"),
                user_data.get("vpn_key"),
                bool(user_data.get("is_active", False)),
                user_data.get("available_devices", 0)
            )
            sub_cache[user_id] = (res, now)
            return res
    except Exception as e:
        print(f"Error getting user sub from Supabase: {e}")
        # Fallback to cache even if expired
        if user_id in sub_cache:
            return sub_cache[user_id][0]

    return None

async def activate_subscription(user_id: int, plan_name: str, duration_days: int, vpn_key: str = None):
    """Activates/Updates a subscription in Supabase using Marzban API."""
    from datetime import datetime, timedelta, timezone
    supabase = await get_supabase()
    marzban_username = f"user_{user_id}"

    # Get current subscription status
    current_sub = await get_user_subscription(user_id)
    now = datetime.now(timezone.utc)

    is_extension = False
    if current_sub:
        plan, end_date_str, current_key, active, devices = current_sub
        if current_key:
            is_extension = True

    try:
        # Check if user already exists in Marzban
        user_exists_in_marzban = False
        try:
            marzban_res = await marzban.get_user_info(marzban_username)
            user_exists_in_marzban = True
            logging.info(f"User {marzban_username} already exists in Marzban, switching to extension.")
        except Exception:
            # User doesn't exist, will create
            user_exists_in_marzban = False

        if user_exists_in_marzban or is_extension:
            # Продление существующего пользователя в Marzban
            marzban_res = await marzban.update_user_expiry(marzban_username, duration_days)
            # Сброс статистики при продлении
            await marzban.reset_user_stats(marzban_username)
            logging.info(f"Subscription extended for {marzban_username}")
        else:
            # Создание нового пользователя в Marzban
            marzban_res = await marzban.create_user(marzban_username, data_limit_gb=0, expire_days=duration_days)
            logging.info(f"New Marzban user created: {marzban_username}")

        # Получаем ссылку на подписку
        subscription_url = marzban_res.get("subscription_url")
        if not subscription_url:
            # Если в ответе нет ссылки, пробуем получить через get_info
            info = await marzban.get_user_info(marzban_username)
            subscription_url = info.get("subscription_url")

    except Exception as e:
        logging.error(f"Marzban API error for user {user_id}: {e}")
        # В случае ошибки API используем переданный ключ как запасной (или оставляем старый)
        subscription_url = vpn_key if vpn_key else (current_sub[2] if current_sub else None)

    # Расчет даты окончания (для базы данных)
    if current_sub and current_sub[1]:
        try:
            end_date_str = current_sub[1]
            if isinstance(end_date_str, str):
                current_end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            else:
                current_end_date = end_date_str

            if current_end_date.tzinfo is None:
                current_end_date = current_end_date.replace(tzinfo=timezone.utc)

            start_from = current_end_date if current_end_date > now else now
        except:
            start_from = now
    else:
        start_from = now

    end_date = start_from + timedelta(days=duration_days)

    # Если мы так и не получили ссылку (ошибка Marzban), не обновляем базу как "активную"
    if not subscription_url:
        logging.error(f"Failed to activate subscription for {user_id}: No subscription URL from Marzban")
        return None

    try:
        await supabase.table("Users").update({
            "is_active": True,
            "subscription_ends": end_date.isoformat(),
            "vpn_key": subscription_url,
            "available_devices": 10 # Лимит устройств
        }).eq("id", user_id).execute()

        # Инвалидация кэша
        if user_id in sub_cache:
            del sub_cache[user_id]

        return subscription_url

    except Exception as e:
        logging.error(f"Error updating Supabase for user {user_id}: {e}", exc_info=True)
        return None

async def is_payment_processed(payment_id: str) -> bool:
    """Checks if a payment has already been processed."""
    try:
        supabase = await get_supabase()
        response = await supabase.table("ProcessedPayments").select("payment_id").eq("payment_id", payment_id).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Error checking payment status in Supabase: {e}")
        return False

async def record_payment(payment_id: str, user_id: int):
    """Records a processed payment in Supabase."""
    try:
        supabase = await get_supabase()
        await supabase.table("ProcessedPayments").insert({
            "payment_id": payment_id,
            "user_id": user_id
        }).execute()
    except Exception as e:
        logging.error(f"Error recording payment in Supabase: {e}")
