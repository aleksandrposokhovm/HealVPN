import os
import uuid
import base64
import httpx
import logging
import asyncio
from datetime import datetime, timezone
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from config import config
import keyboards as kb
import database as db
from marzban_api import marzban_api

router = Router()

LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "website", "assets", "logo_horizontal.png"
))
LOGO_FILE_ID = None

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

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    global LOGO_FILE_ID
    user = message.from_user
    
    await db.add_user(user.id, user.username, user.first_name)
    sub = await db.get_user_subscription(user.id)
    
    is_active = sub[3] if sub else False
    reply_markup = kb.main_menu(is_active=is_active)
    
    welcome_text = (
        "Вижу твой интерес! 👋 Позволь рассказать, почему HealVPN станет твоим лучшим выбором:\n\n"
        "⚡️ **Скорость** — мгновенная загрузка любого контента.\n"
        "🛡 **Приватность** — защита данных от слежки в любой сети.\n"
        "🌐 **Доступ** — стабильная связь с глобальными ресурсами.\n"
        "🖥 **Надёжность** — работа 24/7 и подключение в одно касание.\n\n"
        "Ваш интернет под надёжной защитой. Жми кнопку ниже и лети! 🚀"
    )

    if os.path.exists(LOGO_PATH) or LOGO_FILE_ID:
        try:
            photo = LOGO_FILE_ID if LOGO_FILE_ID else FSInputFile(LOGO_PATH)
            sent_msg = await message.answer_photo(
                photo=photo,
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            if not LOGO_FILE_ID:
                LOGO_FILE_ID = sent_msg.photo[-1].file_id
        except Exception as e:
            logging.error(f"Error sending photo: {e}")
            await message.answer(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.answer(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    is_active = sub[3] if sub else False
    text = "Главное меню:"
    reply_markup = kb.main_menu(is_active=is_active)
    
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup)
    await callback.answer()

@router.callback_query(F.data == "tariffs")
async def tariffs_callback(callback: CallbackQuery):
    text = "💳 *Выберите количество устройств:*"
    reply_markup = kb.tariffs_menu()
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "devices_5")
async def devices_callback(callback: CallbackQuery):
    bot_info = await callback.bot.me()
    payment_data = {
        "amount": {"value": "111.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"https://t.me/{bot_info.username}"},
        "capture": True,
        "description": f"Подписка HealVPN на 1 месяц для пользователя {callback.from_user.id}",
        "metadata": {"user_id": str(callback.from_user.id), "plan": "1_month"}
    }

    try:
        headers = get_yookassa_headers().copy()
        headers["Idempotence-Key"] = str(uuid.uuid4())
        
        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.yookassa.ru/v3/payments", json=payment_data, headers=headers)
            payment = response.json()
            
            if "id" not in payment:
                raise Exception(f"Failed to create payment: {payment}")
            
            text = "💳 *Оплата подписки*\n\nПосле завершения оплаты в браузере нажмите кнопку «Проверить оплату»."
            reply_markup = kb.pay_menu(payment["confirmation"]["confirmation_url"], payment['id'])
            
            if callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error in devices_callback: {e}")
        error_text = "❌ Произошла ошибка. Попробуйте еще раз."
        if callback.message.photo:
            await callback.message.edit_caption(caption=error_text, reply_markup=kb.back_to_main())
        else:
            await callback.message.edit_text(text=error_text, reply_markup=kb.back_to_main())
    await callback.answer()

@router.callback_query(F.data == "subscription_mgmt")
async def subscription_mgmt_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    
    if sub and sub[3]:
        plan, end_date, key, active, devices = sub
        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)
        delta = end_date - datetime.now(timezone.utc)
        text = f"✅ *Активна подписка*\n📅 Осталось: `{max(0, delta.days)} дн.`\n🔑 Ключ доступен по кнопке ниже."
        reply_markup = kb.subscription_management_menu(key=key)
    else:
        text = "❌ *Нет активной подписки*"
        reply_markup = kb.tariffs_menu()
        
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("check_pay:"))
async def check_payment_callback(callback: CallbackQuery):
    payment_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    await callback.answer("Проверяю... ⏳")

    try:
        headers = get_yookassa_headers()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=headers)
            
            if response.status_code != 200:
                logging.error(f"YooKassa API Error: {response.status_code} - {response.text}")
                response.raise_for_status()
                
            payment = response.json()
        
        if payment.get('status') == 'succeeded':
            # Integrate with Marzban
            marzban_username = str(user_id)
            user_response = await marzban_api.create_user(
                username=marzban_username,
                data_limit=0, # Unlimited
                expire=0 # Expiration is handled by DB for now, but could be set in Marzban
            )
            
            sub_url = ""
            if user_response and "subscription_url" in user_response:
                sub_url = user_response["subscription_url"]
                
                # Health-check
                is_valid = await marzban_api.validate_subscription(sub_url)
                if not is_valid:
                    logging.warning(f"Subscription URL for {marzban_username} failed health-check!")
                    # We still continue but log it
            else:
                logging.error(f"Failed to get subscription_url from Marzban for user {user_id}")
                await callback.answer("Ошибка при создании VPN аккаунта. Обратитесь в поддержку.", show_alert=True)
                return

            await db.activate_subscription(user_id, "Стандарт", 30, sub_url)
            
            success_text = "✨ *Оплата прошла успешно!*\nВаша подписка активирована. 🚀"
            reply_markup = kb.success_payment_menu(sub_url)
            
            if callback.message.photo:
                await callback.message.edit_caption(caption=success_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await callback.message.edit_text(text=success_text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await callback.answer("Оплата еще не поступила. ⌛", show_alert=True)
    except Exception as e:
        logging.error(f"Error in check_payment_callback: {e}", exc_info=True)
        await callback.answer("Ошибка при проверке. Пожалуйста, обратитесь в поддержку.", show_alert=True)

@router.callback_query(F.data == "copy_key")
async def copy_key_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    if sub and sub[3]:
        await callback.answer("Отправляю ключ...")
        await callback.message.answer(f"Ваш ключ:\n\n`{sub[2]}`", parse_mode="Markdown")
    else:
        await callback.answer("Ключ не найден", show_alert=True)

@router.callback_query(F.data == "instruction")
async def instruction_callback(callback: CallbackQuery):
    text = "📖 *Инструкция*\n1. Скачайте приложение (v2rayNG, Vultr, Streisand, etc.).\n2. Скопируйте ссылку и импортируйте профиль.\nГотово! ✅"
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=kb.instruction_menu(), parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=kb.instruction_menu(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "about")
async def about_callback(callback: CallbackQuery):
    text = "ℹ️ *О нас*\nHealVPN — быстрый и анонимный сервис."
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=kb.about_menu(), parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=kb.about_menu(), parse_mode="Markdown")
    await callback.answer()

@router.message(Command("status"))
async def status_cmd(message: Message):
    sub = await db.get_user_subscription(message.from_user.id)
    await message.answer(f"Статус: {'Активен' if sub and sub[3] else 'Неактивен'}")

@router.message()
async def save_text(message: Message):
    await message.answer("Используйте кнопки меню!", reply_markup=kb.main_menu())
