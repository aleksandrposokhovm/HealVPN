from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, update, event
from sqlalchemy.exc import IntegrityError
from .models import Base, User, ProcessedPayment, PendingPayment
from .config import config
from datetime import datetime, timezone, timedelta
import logging
import time

# Optimize engine configuration for SQLite: timeout to prevent lockouts, WAL mode for concurrent write-read
connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args["timeout"] = 30.0

engine = create_async_engine(config.DATABASE_URL, echo=False, connect_args=connect_args)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

if config.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

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

async def activate_subscription(user_id: int, plan_name: str, duration_days: int, vpn_key: str, payment_id: str = None, amount: float = None, plan: str = None):
    """
    Activates or extends a subscription. 
    If payment_id is provided, also records it in ProcessedPayment table within the same transaction.
    Uses with_for_update() to prevent race conditions.
    Returns True if activated, False if payment was already processed (idempotent).
    """
    # Fast pre-check outside transaction to avoid unnecessary locking
    if payment_id and await is_payment_processed(payment_id):
        logging.warning(f"Payment {payment_id} already processed (pre-check), skipping activation.")
        return False

    async with async_session() as session:
        try:
            async with session.begin():
                # Lock the user row to prevent concurrent activations for same user
                result = await session.execute(
                    select(User).where(User.id == user_id).with_for_update(skip_locked=False)
                )
                user = result.scalars().first()
                
                if not user:
                    user = User(id=user_id, username=str(user_id), first_name="User")
                    session.add(user)
                
                # Double-check inside transaction (prevents TOCTOU race)
                if payment_id:
                    check_pay = await session.execute(
                        select(ProcessedPayment).where(ProcessedPayment.payment_id == payment_id)
                    )
                    if check_pay.scalars().first():
                        logging.warning(f"Payment {payment_id} already processed (in-tx check), skipping activation.")
                        # Raise to abort session.begin() cleanly — no commit
                        raise _AlreadyProcessed()

                now = datetime.now(timezone.utc)
                
                if user.subscription_ends:
                    if not user.subscription_ends.tzinfo:
                        user.subscription_ends = user.subscription_ends.replace(tzinfo=timezone.utc)
                    if user.subscription_ends > now:
                        start_from = user.subscription_ends
                    else:
                        start_from = now
                else:
                    start_from = now
                    
                user.subscription_ends = start_from + timedelta(days=duration_days)
                user.is_active = True
                user.vpn_key = vpn_key
                user.available_devices = 5
                user.last_payment_date = now
                
                if duration_days == 7:
                    user.last_trial_date = now
                
                if payment_id:
                    proc_payment = ProcessedPayment(
                        payment_id=payment_id,
                        user_id=user_id,
                        amount=amount,
                        plan=plan,
                        processed_at=now
                    )
                    session.add(proc_payment)
                
        except _AlreadyProcessed:
            return False
        except IntegrityError:
            logging.warning(f"Payment {payment_id} already processed (IntegrityError), skipping activation.")
            return False
            
        if user_id in sub_cache:
            del sub_cache[user_id]
        return True

class _AlreadyProcessed(Exception):
    """Internal sentinel to abort a transaction cleanly when payment is duplicate."""
    pass

async def is_payment_processed(payment_id: str) -> bool:
    """Check if payment ID already exists in processed_payments table."""
    async with async_session() as session:
        result = await session.execute(
            select(ProcessedPayment).where(ProcessedPayment.payment_id == payment_id)
        )
        return result.scalars().first() is not None

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

async def set_auto_renew(user_id: int, status: bool):
    """Set auto-renewal status for user."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            user.auto_renew = status
            if status:
                user.failed_payments = 0
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]

async def get_user_auto_renew_status(user_id: int) -> tuple:
    """Returns (auto_renew: bool, has_payment_method: bool)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            return (user.auto_renew, user.payment_method_id is not None)
    return (False, False)

async def get_users_for_auto_renew():
    """
    Find users for auto-renewal based on three attempts:
    1. 24 hours before (failed_payments == 0)
    2. 12 hours before (failed_payments <= 1) — self-healing if 24h attempt was missed
    3. 30 minutes before (failed_payments <= 2) — self-healing if 24h/12h attempts were missed
    """
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        
        # We use slightly wider windows to ensure the hourly scheduler doesn't miss anyone,
        # but the failed_payments check ensures we only try once per window.
        
        # Window 1: 24h attempt (23-25 hours left)
        # Window 2: 12h attempt (11-13 hours left)
        # Window 3: 30m attempt (0-1 hour left)
        
        result = await session.execute(
            select(User).where(
                User.is_active == True,
                User.auto_renew == True,
                User.payment_method_id.isnot(None),
                (
                    ((User.subscription_ends <= now + timedelta(hours=25)) & (User.subscription_ends > now + timedelta(hours=23)) & (User.failed_payments == 0)) |
                    ((User.subscription_ends <= now + timedelta(hours=13)) & (User.subscription_ends > now + timedelta(hours=11)) & (User.failed_payments <= 1)) |
                    ((User.subscription_ends <= now + timedelta(hours=1)) & (User.subscription_ends > now) & (User.failed_payments <= 2))
                )
            )
        )
        return result.scalars().all()


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
            if user_id in sub_cache:
                del sub_cache[user_id]

async def is_trial_available(user_id: int) -> bool:
    """Check if user can use the trial period (never or more than 3 months ago since ANY subscription ended)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if not user:
            return True
        
        now = datetime.now(timezone.utc)
        three_months_ago = now - timedelta(days=90)
        
        # Check if trial was used recently
        if user.last_trial_date:
            if not user.last_trial_date.tzinfo:
                user.last_trial_date = user.last_trial_date.replace(tzinfo=timezone.utc)
            if user.last_trial_date > three_months_ago:
                return False
                
        # Check if ANY subscription ended recently
        if user.subscription_ends:
            if not user.subscription_ends.tzinfo:
                user.subscription_ends = user.subscription_ends.replace(tzinfo=timezone.utc)
            if user.subscription_ends > three_months_ago:
                return False
            
        return True

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

async def delete_user(user_id: int):
    """Delete user from database."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            await session.delete(user)
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]
            return True
    return False

async def update_subscription_date(user_id: int, expiry_date: datetime):
    """Update user's subscription end date and activation status."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            if not expiry_date.tzinfo:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            user.subscription_ends = expiry_date
            user.is_active = expiry_date > datetime.now(timezone.utc)
            await session.commit()
            if user_id in sub_cache:
                del sub_cache[user_id]
            return True
    return False

async def add_pending_payment(payment_id: str, user_id: int, plan: str, amount: float):
    """Add a payment to the pending queue for background polling."""
    async with async_session() as session:
        result = await session.execute(select(PendingPayment).where(PendingPayment.payment_id == payment_id))
        if not result.scalars().first():
            pp = PendingPayment(payment_id=payment_id, user_id=user_id, plan=plan, amount=amount)
            session.add(pp)
            await session.commit()

async def get_pending_payments(max_age_minutes: int = 25):
    """Get pending payments created within the last max_age_minutes, excluding already-processed ones."""
    from sqlalchemy import not_, exists
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_age_minutes)
        # Exclude payments that have already been processed — prevents redundant API calls
        already_processed = select(ProcessedPayment.payment_id).where(
            ProcessedPayment.payment_id == PendingPayment.payment_id
        )
        result = await session.execute(
            select(PendingPayment).where(
                PendingPayment.created_at >= cutoff,
                not_(exists(already_processed))
            )
        )
        return result.scalars().all()

async def remove_pending_payment(payment_id: str):
    """Remove a pending payment from the queue."""
    async with async_session() as session:
        result = await session.execute(select(PendingPayment).where(PendingPayment.payment_id == payment_id))
        pp = result.scalars().first()
        if pp:
            await session.delete(pp)
            await session.commit()

async def cleanup_old_pending_payments(max_age_minutes: int = 30):
    """Delete pending payments older than max_age_minutes."""
    async with async_session() as session:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_age_minutes)
        result = await session.execute(
            select(PendingPayment).where(PendingPayment.created_at < cutoff)
        )
        for pp in result.scalars().all():
            await session.delete(pp)
        await session.commit()
