import asyncio
import argparse
import sys
from datetime import datetime, timezone
from bot.database import delete_user, update_subscription_date, async_session
from bot.models import User
from sqlalchemy import select

async def get_user_info(user_id: int):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        if user:
            print(f"--- User Info: {user_id} ---")
            print(f"Username: {user.username}")
            print(f"Active: {user.is_active}")
            print(f"Sub Ends: {user.subscription_ends}")
            print(f"Auto Renew: {user.auto_renew}")
            print(f"Last Trial: {user.last_trial_date}")
            print(f"Failed Payments: {user.failed_payments}")
        else:
            print(f"User {user_id} not found in database.")

async def main():
    parser = argparse.ArgumentParser(description="HealVPN Admin CLI Tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete user from database")
    delete_parser.add_argument("user_id", type=int, help="Telegram User ID")

    # Set sub date command
    sub_parser = subparsers.add_parser("set-sub", help="Set subscription end date")
    sub_parser.add_argument("user_id", type=int, help="Telegram User ID")
    sub_parser.add_argument("date", type=str, help="Date in YYYY-MM-DD format")

    # Info command
    info_parser = subparsers.add_parser("info", help="Get user information")
    info_parser.add_argument("user_id", type=int, help="Telegram User ID")

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return

    if args.command == "delete":
        success = await delete_user(args.user_id)
        if success:
            print(f"Successfully deleted user {args.user_id}")
        else:
            print(f"User {args.user_id} not found.")

    elif args.command == "set-sub":
        try:
            # Parse date and set to UTC midnight
            dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # Add some time to make it end of day or just keep it midnight
            success = await update_subscription_date(args.user_id, dt)
            if success:
                print(f"Successfully updated subscription for {args.user_id} to {dt}")
            else:
                print(f"User {args.user_id} not found.")
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD.")

    elif args.command == "info":
        await get_user_info(args.user_id)

if __name__ == "__main__":
    asyncio.run(main())
