import os
import uuid
import httpx
import logging
from datetime import datetime, timezone
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from .config import config, get_yookassa_headers
from . import keyboards as kb
from . import database as db
from .marzban_api import marzban_api
from .payment_service import process_successful_payment
from .utils import send_menu_with_logo

router = Router()

processed_payments_cache = {}

WELCOME_TEXT = (
    "Вижу твой интерес! 👋 Позволь рассказать, почему HealVPN станет твоим лучшим выбором:\n\n"
    "⚡️ **Скорость** — мгновенная загрузка любого контента.\n"
    "🛡 **Приватность** — защита данных от слежки в любой сети.\n"
    "🌐 **Доступ** — стабильная связь с глобальными ресурсами.\n"
    "🖥 **Надёжность** — работа 24/7 и подключение в одно касание.\n\n"
    "Ваш интернет под надёжной защитой. Жми кнопку ниже и лети! 🚀"
)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    user = message.from_user

    await db.add_user(user.id, user.username, user.first_name)
    sub = await db.get_user_subscription(user.id)
    trial_avail = await db.is_trial_available(user.id)

    is_active = sub[3] if sub else False
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

    await send_menu_with_logo(
        bot=bot,
        chat_id=message.chat.id,
        text=WELCOME_TEXT,
        reply_markup=reply_markup
    )


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    is_active = sub[3] if sub else False
    trial_avail = await db.is_trial_available(callback.from_user.id)
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

    await send_menu_with_logo(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        text=WELCOME_TEXT,
        reply_markup=reply_markup,
        message_to_edit=callback.message
    )
    await callback.answer()


@router.callback_query(F.data == "tariffs")
async def tariffs_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    is_active = sub[3] if sub else False

    # Show trial only if it's available AND user doesn't have an active subscription
    trial_avail = False
    if not is_active:
        trial_avail = await db.is_trial_available(callback.from_user.id)

    text = "💳 *Выберите количество устройств:*"
    reply_markup = kb.tariffs_menu(trial_available=trial_avail)
    await send_menu_with_logo(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        text=text,
        reply_markup=reply_markup,
        message_to_edit=callback.message
    )
    await callback.answer()

@router.callback_query(F.data == "trial")
async def trial_callback(callback: CallbackQuery):
    # Verify trial is still available before creating payment
    trial_avail = await db.is_trial_available(callback.from_user.id)
    if not trial_avail:
        await callback.answer("❌ Пробный период уже был использован.", show_alert=True)
        return

    # Health-check Marzban before accepting payment
    token = await marzban_api.get_token()
    if not token:
        await callback.answer("❌ Ошибка соединения с сервером VPN. Попробуйте позже.", show_alert=True)
        return

    bot_info = await callback.bot.me()
    payment_data = {
        "amount": {"value": f"{kb.PRICE_TRIAL}.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"https://t.me/{bot_info.username}"},
        "capture": True,
        "save_payment_method": True,
        "description": f"Пробный период HealVPN на 7 дней для пользователя {callback.from_user.id}",
        "metadata": {"user_id": str(callback.from_user.id), "plan": "trial_7_days"}
    }

    try:
        headers = get_yookassa_headers().copy()
        headers["Idempotence-Key"] = str(uuid.uuid4())

        async with httpx.AsyncClient() as client:
            response = await client.post("https://api.yookassa.ru/v3/payments", json=payment_data, headers=headers)
            payment = response.json()

            if "id" not in payment:
                raise Exception(f"Failed to create trial payment: {payment}")

            await db.add_pending_payment(payment["id"], callback.from_user.id, "trial_7_days", float(kb.PRICE_TRIAL))

            text = ("🎁 *Пробный период на 7 дней*\n\n"
                    "После завершения оплаты в браузере нажмите кнопку «✅ Проверить оплату».\n\n"
                    f"Оплачивая пробный период, вы активируете автопродление. Спустя 6 дней подписка будет продлена на стандартный месяц за {kb.PRICE_MONTH}₽ со счета привязанной карты. Автопродление срабатывает за 24 часа до окончания срока действия подписки. Отключить его можно в любой момент в разделе «⚙️ Управление подпиской».")
            reply_markup = kb.pay_menu(payment["confirmation"]["confirmation_url"], payment['id'], is_trial=True)

            await send_menu_with_logo(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                message_to_edit=callback.message
            )
    except Exception as e:
        logging.error(f"Error in trial_callback: {e}")
        error_text = "❌ Произошла ошибка. Попробуйте еще раз."
        await send_menu_with_logo(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            text=error_text,
            reply_markup=kb.back_to_main(),
            message_to_edit=callback.message
        )
    await callback.answer()

@router.callback_query(F.data == "devices_5")
async def devices_callback(callback: CallbackQuery):
    # Health-check Marzban before accepting payment
    token = await marzban_api.get_token()
    if not token:
        await callback.answer("❌ Ошибка соединения с сервером VPN. Попробуйте позже.", show_alert=True)
        return

    bot_info = await callback.bot.me()
    payment_data = {
        "amount": {"value": f"{kb.PRICE_MONTH}.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": f"https://t.me/{bot_info.username}"},
        "capture": True,
        "save_payment_method": True,
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

            await db.add_pending_payment(payment["id"], callback.from_user.id, "1_month", float(kb.PRICE_MONTH))

            text = ("💳 *Подписка на 1 месяц*\n\n"
                    "После завершения оплаты в браузере нажмите кнопку «✅ Проверить оплату».\n\n"
                    "Оплачивая подписку, вы соглашаетесь на её автопродление. Оно будет срабатывать за 24 часа до окончания срока действия текущего тарифа. Средства спишутся со счета, с которого был совершен последний платеж.\n\n"
                    "Отключить автопродление можно в любой момент в разделе «⚙️ Управление подпиской».")
            reply_markup = kb.pay_menu(payment["confirmation"]["confirmation_url"], payment['id'])

            await send_menu_with_logo(
                bot=callback.bot,
                chat_id=callback.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                message_to_edit=callback.message
            )
    except Exception as e:
        logging.error(f"Error in devices_callback: {e}")
        error_text = "❌ Произошла ошибка. Попробуйте еще раз."
        await send_menu_with_logo(
            bot=callback.bot,
            chat_id=callback.message.chat.id,
            text=error_text,
            reply_markup=kb.back_to_main(),
            message_to_edit=callback.message
        )
    await callback.answer()

@router.callback_query(F.data == "subscription_mgmt")
async def subscription_mgmt_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)

    if sub and sub[3]:
        plan, end_date, key, active, devices = sub
        if not end_date.tzinfo:
            end_date = end_date.replace(tzinfo=timezone.utc)
        delta = end_date - datetime.now(timezone.utc)
        total_seconds = int(delta.total_seconds())

        if total_seconds > 0:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            time_left = f"{days} дн. {hours} ч. {minutes} мин."
        else:
            time_left = "0 дн. 0 ч. 0 мин."

        auto_renew, has_pm = await db.get_user_auto_renew_status(callback.from_user.id)
        status_text = "ВКЛ" if auto_renew else "ВЫКЛ"

        text = (
            f"⚙️ **Управление подпиской**\n\n"
            f"✅ **Активна подписка**\n"
            f"📅 **Осталось**: {time_left}\n"
            f"🔄 **Автопродление**: {status_text}\n"
            f"🔑 Ключ доступен по кнопке ниже."
        )
        reply_markup = kb.subscription_management_menu(key=key, auto_renew=auto_renew)
    else:
        trial_avail = await db.is_trial_available(callback.from_user.id)
        text = "❌ *Подписка не активна.*\nАктивируйте её прямо сейчас, чтобы наслаждаться быстрым интернетом без границ! ✨"
        reply_markup = kb.tariffs_menu(trial_available=trial_avail)

    await send_menu_with_logo(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        text=text,
        reply_markup=reply_markup,
        message_to_edit=callback.message
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_pay:"))
async def check_payment_callback(callback: CallbackQuery):
    payment_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    # 1. Защита от быстрых двойных кликов в рамках одного процесса
    global processed_payments_cache
    now = datetime.now(timezone.utc)

    if payment_id in processed_payments_cache:
        val = processed_payments_cache[payment_id]
        if val == "processing":
            await callback.answer("Проверка уже выполняется... ⏳", show_alert=True)
            return
        elif isinstance(val, datetime):
            await callback.answer("Эта оплата уже была успешно обработана. ✅", show_alert=True)
            return

    # 2. Проверка в базе данных (защита от перезапусков бота и повторных попыток)
    if await db.is_payment_processed(payment_id):
        processed_payments_cache[payment_id] = now # Обновляем локальный кэш
        await callback.answer("Эта оплата уже была успешно обработана. ✅", show_alert=True)
        return

    # Помечаем как "в обработке"
    processed_payments_cache[payment_id] = "processing"
    await callback.answer("Проверяю статус оплаты... ⏳")

    try:
        headers = get_yookassa_headers()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=headers)
            if response.status_code != 200:
                raise Exception(f"YooKassa API Error: {response.status_code}")
            payment = response.json()

        if payment.get('status') == 'succeeded':
            success = await process_successful_payment(
                bot=callback.bot,
                user_id=user_id,
                payment_id=payment_id,
                payment=payment,
                is_background=False,
                message_to_edit=callback.message
            )

            if not success:
                # Значит платеж уже был обработан кем-то другим (race condition в БД пресечен)
                await db.remove_pending_payment(payment_id)
                await callback.answer("Эта оплата уже была успешно обработана. ✅", show_alert=True)
                return

            await db.remove_pending_payment(payment_id)

            # 6. Финальное обновление кэша
            processed_payments_cache[payment_id] = datetime.now(timezone.utc)

        else:
            # Оплата еще не прошла — сбрасываем статус "в обработке", чтобы можно было нажать снова
            if payment_id in processed_payments_cache:
                del processed_payments_cache[payment_id]
            await callback.answer("Оплата еще не поступила. ⌛", show_alert=True)

    except Exception as e:
        # В случае ошибки сбрасываем статус, чтобы пользователь мог попробовать еще раз
        if payment_id in processed_payments_cache:
            del processed_payments_cache[payment_id]

        logging.error(f"Error in check_payment_callback: {e}", exc_info=True)
        await callback.answer("❌ Произошла неизвестная ошибка, пожалуйста, обратитесь к нашему менеджеру", show_alert=True)

@router.callback_query(F.data == "copy_key")
async def copy_key_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    if sub and sub[3]:
        key = sub[2]
        # Send key as plain text so user can tap and copy it
        await callback.message.answer(
            f"🔑 Ваш VPN ключ — нажмите, чтобы скопировать:\n\n`{key}`",
            parse_mode="Markdown"
        )
        await callback.answer()
    else:
        await callback.answer("Ключ не найден. Сначала оформите подписку.", show_alert=True)

@router.callback_query(F.data == "disable_auto_renew")
async def disable_auto_renew_callback(callback: CallbackQuery):
    await db.set_auto_renew(callback.from_user.id, False)
    await callback.answer("❌ Автопродление отключено", show_alert=True)
    # Refresh the subscription management screen
    await subscription_mgmt_callback(callback)

@router.callback_query(F.data == "enable_auto_renew")
async def enable_auto_renew_callback(callback: CallbackQuery):
    await db.set_auto_renew(callback.from_user.id, True)
    await callback.answer("✅ Автопродление включено", show_alert=True)
    # Refresh the subscription management screen
    await subscription_mgmt_callback(callback)

@router.callback_query(F.data == "about")
async def about_callback(callback: CallbackQuery):
    text = "ℹ️ *О нас*\nHealVPN — быстрый и анонимный сервис."
    await send_menu_with_logo(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        text=text,
        reply_markup=kb.about_menu(),
        message_to_edit=callback.message
    )
    await callback.answer()

@router.message(Command("status"))
async def status_cmd(message: Message):
    sub = await db.get_user_subscription(message.from_user.id)
    await send_menu_with_logo(
        bot=message.bot,
        chat_id=message.chat.id,
        text=f"Статус: {'Активен' if sub and sub[3] else 'Неактивен'}"
    )

@router.message()
async def save_text(message: Message):
    sub = await db.get_user_subscription(message.from_user.id)
    is_active = sub[3] if sub else False
    trial_avail = await db.is_trial_available(message.from_user.id)
    await send_menu_with_logo(
        bot=message.bot,
        chat_id=message.chat.id,
        text="Используйте кнопки меню!",
        reply_markup=kb.main_menu(is_active=is_active, trial_available=trial_avail)
    )
