import aiosqlite
from config import config

async def init_db():
    async with aiosqlite.connect(config.DB_NAME) as db:
        # Table for users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Table for subscriptions
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_name TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                vpn_key TEXT,
                is_active BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        await db.commit()

async def add_user(user_id: int, username: str, full_name: str):
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        await db.commit()

async def get_user_subscription(user_id: int):
    async with aiosqlite.connect(config.DB_NAME) as db:
        async with db.execute(
            "SELECT plan_name, end_date, vpn_key, is_active FROM subscriptions WHERE user_id = ? AND is_active = 1 ORDER BY end_date DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            return await cursor.fetchone()

async def activate_subscription(user_id: int, plan_name: str, duration_days: int, vpn_key: str):
    from datetime import datetime, timedelta
    start_date = datetime.now()
    end_date = start_date + timedelta(days=duration_days)
    
    async with aiosqlite.connect(config.DB_NAME) as db:
        await db.execute(
            "INSERT INTO subscriptions (user_id, plan_name, start_date, end_date, vpn_key, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, plan_name, start_date, end_date, vpn_key, 1)
        )
        await db.commit()
