from telegram import Update, constants
from telegram.ext import ContextTypes
import keyboards as kb
import database as db
import os
from datetime import datetime
from groq import Groq
from config import config

# Initialize Groq client
groq_client = Groq(api_key=config.GROQ_API_KEY.get_secret_value())

# Directory for saved files
DOWNLOADS_DIR = "downloads"
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user.id, user.username, user.full_name)
    
    await update.message.reply_text(
        f"Привет, {user.full_name}! 👋\n\n"
        "Добро пожаловать в **HealVPN**. Мы обеспечиваем быстрый и безопасный доступ к интернету с функцией раздельного туннелирования.\n\n"
        "Выбери действие ниже:",
        reply_markup=kb.main_menu(),
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Главное меню:",
        reply_markup=kb.main_menu()
    )

async def tariffs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💳 **Наши тарифы:**\n\n"
        "🔹 **Стандарт**\n"
        "— 1 месяц доступа\n"
        "— Все локации\n"
        "— Раздельное туннелирование\n"
        "— Цена: **150 рублей**",
        reply_markup=kb.tariffs_menu(),
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    sub = await db.get_user_subscription(user_id)
    
    if sub:
        plan, end_date, key, active = sub
        text = (
            f"👤 **Профиль**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📊 Статус: {'✅ Активен' if active else '❌ Неактивен'}\n"
            f"📅 Истекает: {end_date}\n"
            f"🔑 Ваш ключ: `{key}`"
        )
    else:
        text = (
            f"👤 **Профиль**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📊 Подписка: **Не найдена**\n\n"
            "Оформите подписку в разделе «Тарифы», чтобы получить доступ."
        )
    
    await query.answer()
    await query.edit_message_text(
        text, 
        reply_markup=kb.back_to_main(), 
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def instructions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ **Как подключить HealVPN:**\n\n"
        "1. Скачайте приложение [WireGuard](https://www.wireguard.com/install/) или [Outline](https://getoutline.org/).\n"
        "2. Скопируйте ваш ключ из раздела «Мой профиль».\n"
        "3. Добавьте новый сервер в приложении, используя ваш ключ.\n"
        "4. Включите VPN и наслаждайтесь свободным интернетом!",
        reply_markup=kb.back_to_main(),
        parse_mode=constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Функция оплаты в процессе интеграции. Скоро здесь появится ссылка на ЮKassa!")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **Справка**\n\n"
        "/start — Главное меню\n"
        "/status — Проверить статус подписки\n"
        "/help — Показать это сообщение\n\n"
        "Вы также можете отправить текст, фото, голос или документ для сохранения.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub = await db.get_user_subscription(user_id)
    
    if sub:
        plan, end_date, key, active = sub
        status_text = "✅ Активен" if active else "❌ Неактивен"
        await update.message.reply_text(f"📊 Ваш статус: {status_text}\n📅 Истекает: {end_date}")
    else:
        await update.message.reply_text("📊 Подписка не найдена.")

async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    try:
        # Show typing status
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Ты — помощник HealVPN. Отвечай вежливо и кратко."},
                {"role": "user", "content": text}
            ],
            model="llama3-8b-8192",
        )
        response = chat_completion.choices[0].message.content
        await update.message.reply_text(response)
    except Exception as e:
        print(f"Error in save_text: {e}")
        await update.message.reply_text("Извините, я не смог обработать ваш запрос.")

async def save_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Show typing status
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        file = await update.message.voice.get_file()
        file_path = os.path.join(DOWNLOADS_DIR, f"voice_{update.effective_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg")
        await file.download_to_drive(file_path)
        
        # Transcribe using Groq
        with open(file_path, "rb") as file_data:
            transcription = groq_client.audio.transcriptions.create(
                file=(file_path, file_data.read()),
                model="whisper-large-v3",
                response_format="text",
            )
        
        await update.message.reply_text(f"🎤 **Расшифровка:**\n\n{transcription}", parse_mode=constants.ParseMode.MARKDOWN)
        
        # Optional: Answer based on transcription
        # await save_text_logic(update, transcription)
        
    except Exception as e:
        print(f"Error in save_voice: {e}")
        await update.message.reply_text("Не удалось расшифровать голосовое сообщение.")

async def save_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_path = os.path.join(DOWNLOADS_DIR, f"doc_{update.effective_user.id}_{update.message.document.file_name}")
    await file.download_to_drive(file_path)
    await update.message.reply_text(f"📄 Документ сохранен: {update.message.document.file_name}")

async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the largest photo
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_path = os.path.join(DOWNLOADS_DIR, f"photo_{update.effective_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    await file.download_to_drive(file_path)
    await update.message.reply_text(f"📸 Фото сохранено.")
