from supabase import create_async_client, AsyncClient
from config import config

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
        print(f"Error adding user to Supabase: {e}")

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

async def activate_subscription(user_id: int, plan_name: str, duration_days: int, vpn_key: str):
    """Activates/Updates a subscription in Supabase. Extends if already active."""
    from datetime import datetime, timedelta, timezone
    supabase = await get_supabase()
    
    # Get current subscription status
    current_sub = await get_user_subscription(user_id)
    now = datetime.now(timezone.utc)
    
    if current_sub:
        plan, end_date_str, current_key, active, devices = current_sub
        try:
            if end_date_str:
                if isinstance(end_date_str, str):
                    # Handle Z and other ISO formats
                    current_end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                else:
                    current_end_date = end_date_str
                
                # Ensure aware
                if current_end_date.tzinfo is None:
                    current_end_date = current_end_date.replace(tzinfo=timezone.utc)

                if current_end_date > now:
                    # Extend from the end of current sub
                    start_from = current_end_date
                else:
                    start_from = now
            else:
                start_from = now
        except Exception as e:
            print(f"Error parsing date during extension: {e}")
            start_from = now
    else:
        start_from = now

    end_date = start_from + timedelta(days=duration_days)
    
    try:
        await supabase.table("Users").update({
            "is_active": True,
            "subscription_ends": end_date.isoformat(),
            "vpn_key": vpn_key,
            "available_devices": 5 # Default for this plan
        }).eq("id", user_id).execute()
        
        # Invalidate cache so the user sees the update immediately
        if user_id in sub_cache:
            del sub_cache[user_id]
            
    except Exception as e:
        import logging
        logging.error(f"Error activating sub in Supabase for user {user_id}: {e}", exc_info=True)
