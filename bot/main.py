import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN
from handlers import (
    start, 
    main_menu_callback, 
    tariffs_callback, 
    devices_callback,
    subscription_mgmt_callback,
    instruction_callback,
    help_cmd,
    status,
    save_text,
    save_voice,
    save_document,
    save_photo,
    copy_key_callback
)
from database import init_db

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def post_init(application):
    await init_db()

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))

    # Callbacks
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(tariffs_callback, pattern="^tariffs$"))
    app.add_handler(CallbackQueryHandler(devices_callback, pattern="^devices_10$"))
    app.add_handler(CallbackQueryHandler(subscription_mgmt_callback, pattern="^subscription_mgmt$"))
    app.add_handler(CallbackQueryHandler(instruction_callback, pattern="^instruction$"))
    app.add_handler(CallbackQueryHandler(copy_key_callback, pattern="^copy_key$"))

    # Media and Text handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_text))
    app.add_handler(MessageHandler(filters.VOICE, save_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, save_document))
    app.add_handler(MessageHandler(filters.PHOTO, save_photo))

    # Run the bot
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
