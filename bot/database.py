from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select
from .models import Base, User
from .config import config
from datetime import datetime, timezone, timedelta
import logging

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Cache with 10 minute TTL for subscriptions to reduce DB hits
sub_cache = {}
CACHE_TTL = 600 

async def add_user(user_id: int, username: str, first_name: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        
        if not user:
            user = User(id=user_id, username=username, first_name=first_name)
            session.add(user)
        else:
            user.username = username
            user.first_name = first_name
            
        await session.commit()

async def get_user_subscription(user_id: int):
    import time
    now = time.time()
    
    if user_id in sub_cache:
        data, timestamp = sub_cache[user_id]
        if now - timestamp < CACHE_TTL:
            return data
            
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        
        if user:
            res = (
                "Стандарт",
                user.subscription_ends,
                user.vpn_key,
                user.is_active,
                user.available_devices
            )
            sub_cache[user_id] = (res, now)
            return res
            
    return None

async def activate_subscription(user_id: int, plan_name: str, duration_days: int, vpn_key: str):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        
        if not user:
            # Auto-create the user if they were missing from the DB
            user = User(id=user_id, username=str(user_id), first_name="User")
            session.add(user)
            await session.commit() # Commit to ensure it exists
            # We don't return here, we proceed to activate
            
        now = datetime.now(timezone.utc)
        
        if user.subscription_ends and user.subscription_ends > now:
            start_from = user.subscription_ends
        else:
            start_from = now
            
        user.subscription_ends = start_from + timedelta(days=duration_days)
        user.is_active = True
        user.vpn_key = vpn_key
        user.available_devices = 5
        user.last_payment_date = now
        
        # If it's a trial (detected by duration or passed flag), set last_trial_date
        if duration_days == 7: # 7 days is the new trial duration
            user.last_trial_date = now
            
        await session.commit()
        
        if user_id in sub_cache:
            del sub_cache[user_id]

async def deactivate_expired_subscriptions():
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(User).where(User.is_active == True, User.subscription_ends <= now)
        )
        users = result.scalars().all()
        for u in users:
            u.is_active = False
            if u.id in sub_cache:
                del sub_cache[u.id]
        await session.commit()

async def save_payment_method(user_id: int, payment_method_id: str):
    """Save YooKassa payment method ID for auto-renewal."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            user.payment_method_id = payment_method_id
            user.auto_renew = True
            user.failed_payments = 0
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]

async def toggle_auto_renew(user_id: int) -> bool:
    """Toggle auto-renewal for user. Returns new state."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            user.auto_renew = not user.auto_renew
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]
            return user.auto_renew
    return False

async def get_user_auto_renew_status(user_id: int) -> tuple:
    """Returns (auto_renew: bool, has_payment_method: bool)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            return (user.auto_renew, user.payment_method_id is not None)
    return (False, False)

async def get_users_for_auto_renew():
    """Find users whose subscription expires very soon (within 1 hour) or has already expired, but have auto-renew enabled."""
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        threshold = now + timedelta(hours=1)
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.auto_renew == True,
                User.payment_method_id.isnot(None),
                User.subscription_ends <= threshold,
                User.failed_payments < 2 # 0 = first attempt, 1 = after grace period
            )
        )
        return result.scalars().all()

async def grant_grace_period(user_id: int, hours: int = 12):
    """Grant bonus hours to user and increment failed_payments."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            now = datetime.now(timezone.utc)
            start_from = max(user.subscription_ends, now)
            user.subscription_ends = start_from + timedelta(hours=hours)
            user.failed_payments += 1
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]

async def increment_failed_payments(user_id: int) -> int:
    """Increment failed payment counter. Returns new count. Disables auto_renew at 3."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            user.failed_payments += 1
            if user.failed_payments >= 3:
                user.auto_renew = False
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]
            return user.failed_payments
    return 0

async def reset_failed_payments(user_id: int):
    """Reset failed payment counter after successful payment."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            user.failed_payments = 0
            await session.commit()

async def get_users_expiring_tomorrow():
    """Find users whose subscription expires in 23-25 hours (for day-before notification)."""
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        lower = now + timedelta(hours=23)
        upper = now + timedelta(hours=24)
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.subscription_ends >= lower,
                User.subscription_ends <= upper,
            )
        )
        return result.scalars().all()

async def is_trial_available(user_id: int) -> bool:
    """Check if user can use the trial period (never or more than 3 months ago)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return True
        
        if not user.last_trial_date:
            return True
            
        now = datetime.now(timezone.utc)
        three_months_ago = now - timedelta(days=90)
        return user.last_trial_date < three_months_ago

async def get_users_for_trial_reminder():
    """Find users whose trial ended approximately 90 days ago (within the last 24h) and who are not active."""
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        # Check users who became eligible in the last 24 hours
        target_date_start = now - timedelta(days=90, hours=24)
        target_date_end = now - timedelta(days=90)
        
        result = await session.execute(
            select(User).where(
                User.is_active == False,
                User.last_trial_date >= target_date_start,
                User.last_trial_date <= target_date_end
            )
        )
        return result.scalars().all()
