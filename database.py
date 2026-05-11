from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select
from models import Base, User
from config import config
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
            # We don't delete vpn_key so user can still see it in the panel, it's just disabled on Marzban side (Marzban handles its own expiration if set)
            if u.id in sub_cache:
                del sub_cache[u.id]
        await session.commit()
