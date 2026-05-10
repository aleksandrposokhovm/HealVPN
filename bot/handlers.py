import asyncio
from telegram import Update, constants
from telegram.ext import ContextTypes
import keyboards as kb
import database as db
import os
from datetime import datetime
from config import config
import httpx
import base64
import json
import uuid
import secrets
import string
import time
import logging

# Optimized Persistent HTTP client with connection pooling and timeouts
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(5.0, connect=2.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
    headers={"Connection": "keep-alive"}
)

async def get_http_client():
    global _http_client
    if _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
        )
    return _http_client

_yookassa_headers = None

def get_yookassa_headers():
    global _yookassa_headers
    if _yookassa_headers is None:
        auth_str = f"{config.YOOKASSA_SHOP_ID}:{config.YOOKASSA_SECRET_KEY.get_secret_value()}"
        auth_bytes = auth_str.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')
        _yookassa_headers = {
            "Authorization": f"Basic {base64_auth}",
            "Content-Type": "application/json"
        }
    return _yookassa_headers

# Directory for saved files
DOWNLOADS_DIR = "downloads"
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "website", "assets", "logo_horizontal.png"
))

# Cache for Telegram file_id to speed up sending
LOGO_FILE_ID = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LOGO_FILE_ID
    user = update.effective_user
    logging.info(f"DEBUG: Start handler triggered by user {user.id} ({user.username})")
    
    # Run DB tasks in parallel
    start_time = time.time()
    db_tasks = [
        db.add_user(user.id, user.username, user.first_name),
        db.get_user_subscription(user.id)
    ]
    try:
        _, sub = await asyncio.gather(*db_tasks)
    except Exception as e:
        logging.error(f"Error in start handler DB tasks: {e}")
        sub = None
    
    welcome_text = (
        "Вижу твой интерес! 👋 Позволь рассказать, почему HealVPN станет твоим лучшим выбором:\n\n"
        "⚡️ **Скорость** — мгновенная загрузка любого контента.\n"
        "🛡 **Приватность** — защита данных от слежки в любой сети.\n"
        "🌐 **Доступ** — стабильная связь с глобальными ресурсами.\n"
        "🖥 **Надёжность** — работа 24/7 и подключение в одно касание.\n\n"
        "Ваш интернет под надёжной защитой. Жми кнопку ниже и лети! 🚀"
    )

    is_active = sub[3] if sub else False
    reply_markup = kb.main_menu(is_active=is_active)

    if os.path.exists(LOGO_PATH) or LOGO_FILE_ID:
        try:
            photo_to_send = LOGO_FILE_ID if LOGO_FILE_ID else open(LOGO_PATH, 'rb')
            sent_msg = await update.message.reply_photo(
                photo=photo_to_send,
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            if not LOGO_FILE_ID:
                LOGO_FILE_ID = sent_msg.photo[-1].file_id
                if hasattr(photo_to_send, 'close'):
                    photo_to_send.close()
        except Exception as e:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    logging.info(f"DEBUG: Start took {time.time() - start_time:.2f}s")

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    sub = await db.get_user_subscription(query.from_user.id)
    is_active = sub[3] if sub else False
    text = "Главное меню:"
    reply_markup = kb.main_menu(is_active=is_active)
    
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup)

async def tariffs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "💳 **Выберите количество устройств:**"
    reply_markup = kb.tariffs_menu()
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)

async def devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    payment_data = {
        "amount": {"value": "111.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"https://t.me/{context.bot.username}"},
        "capture": True,
        "description": f"Подписка HealVPN на 1 месяц для пользователя {query.from_user.id}",
        "metadata": {"user_id": str(query.from_user.id), "plan": "1_month"}
    }

    try:
        headers = get_yookassa_headers().copy()
        headers["Idempotence-Key"] = str(uuid.uuid4())
        client = await get_http_client()
        
        # Async YooKassa call
        response = await client.post("https://api.yookassa.ru/v3/payments", json=payment_data, headers=headers)
        payment = response.json()
        
        if "id" not in payment:
            raise Exception(f"Failed to create payment: {payment}")
            
        context.user_data['pending_pay_id'] = payment['id']
        context.user_data['pending_pay_url'] = payment["confirmation"]["confirmation_url"]
        
        text = "💳 **Оплата подписки**\n\nПосле завершения оплаты в браузере нажмите кнопку «Проверить оплату»."
        reply_markup = kb.pay_menu(payment["confirmation"]["confirmation_url"], payment['id'])
        
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
            
    except Exception as e:
        print(f"Error in devices_callback: {e}")
        error_text = "❌ Произошла ошибка. Попробуйте еще раз."
        if query.message.photo:
            await query.edit_message_caption(caption=error_text, reply_markup=kb.back_to_main())
        else:
            await query.edit_message_text(text=error_text, reply_markup=kb.back_to_main())

async def subscription_mgmt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub = await db.get_user_subscription(query.from_user.id)
    
    if sub and sub[3]:
        plan, end_date_str, key, active, devices = sub
        from datetime import timezone
        end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')) if isinstance(end_date_str, str) else end_date_str
        if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)
        delta = end_dt - datetime.now(timezone.utc)
        text = f"✅ **Активна подписка**\n📅 Осталось: `{max(0, delta.days)} дн.`\n🔑 Ключ доступен ниже."
        reply_markup = kb.subscription_management_menu(key=key)
    else:
        text = "❌ **Нет активной подписки**"
        reply_markup = kb.tariffs_menu()
        
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)


async def check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    payment_id = query.data.split(":")[1]
    user_id = query.from_user.id
    try:
        await query.answer("Проверяю... ⏳")
    except Exception as e:
        logging.error(f"Error answering callback query: {e}")

    try:
        headers = get_yookassa_headers()
        client = await get_http_client()
        response = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=headers)
        payment = response.json()
        
        logging.info(f"Payment status for {payment_id}: {payment.get('status')}")
        
        if payment.get('status') == 'succeeded':
            new_key = "ss://" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)) + "@123.123.123.123:1234/?outline=1"
            await db.activate_subscription(user_id, "Стандарт", 30, new_key)
            success_text = "✨ **Оплата прошла успешно!**\nВаша подписка активирована. 🚀"
            reply_markup = kb.success_payment_menu(new_key)
            if query.message.photo:
                await query.edit_message_caption(caption=success_text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
            else:
                await query.edit_message_text(text=success_text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
        else:
            await query.answer("Оплата еще не поступила. ⌛", show_alert=True)
    except Exception as e:
        logging.error(f"Error in check_payment_callback: {e}", exc_info=True)
        await query.answer("Ошибка при проверке. Пожалуйста, обратитесь в поддержку.", show_alert=True)

async def copy_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sub = await db.get_user_subscription(query.from_user.id)
    if sub and sub[3]:
        await query.answer("Ключ скопирован!", show_alert=True)
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"Ваш ключ:\n\n`{sub[2]}`", parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.answer("Ключ не найден", show_alert=True)

async def instruction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📖 **Инструкция**\n1. Скачайте Outline.\n2. Вставьте ключ.\nГотово! ✅"
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=kb.instruction_menu(), parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=kb.instruction_menu(), parse_mode=constants.ParseMode.MARKDOWN)

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "ℹ️ **О нас**\nHealVPN — быстрый и анонимный сервис."
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=kb.about_menu(), parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=kb.about_menu(), parse_mode=constants.ParseMode.MARKDOWN)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — Меню\n/status — Статус")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub = await db.get_user_subscription(update.effective_user.id)
    await update.message.reply_text(f"Статус: {'Активен' if sub and sub[3] else 'Неактивен'}")

async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используйте кнопки меню!", reply_markup=kb.main_menu())

async def save_voice(update: Update, context: ContextTypes.DEFAULT_TYPE): await save_text(update, context)
async def save_document(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Документ получен.")
async def save_photo(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Фото получено.")
