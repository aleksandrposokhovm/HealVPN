import logging
import asyncio
from aiogram import Bot, Dispatcher
from bot.config import config
from bot.handlers import router
from bot.database import init_db
from bot.scheduler import setup_scheduler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def main():
    # Initialize DB (creates tables if they don't exist)
    await init_db()
    
    bot = Bot(token=config.BOT_TOKEN.get_secret_value())
    dp = Dispatcher()
    
    dp.include_router(router)
    
    # Setup and start scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    
    print("Bot started [Aiogram 3.x]...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
