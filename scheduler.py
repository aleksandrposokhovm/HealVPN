import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import deactivate_expired_subscriptions
from aiogram import Bot

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    
    # Check for expired subscriptions every hour
    scheduler.add_job(
        deactivate_expired_subscriptions,
        'interval',
        hours=1,
        id='deactivate_expired'
    )
    
    # We could also add jobs to notify users before expiration here
    
    return scheduler
