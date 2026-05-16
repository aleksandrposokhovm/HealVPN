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

router = Router()

LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "logo_horizontal.png"
))
LOGO_FILE_ID = None

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    global LOGO_FILE_ID
    user = message.from_user

    await db.add_user(user.id, user.username, user.first_name)
    sub = await db.get_user_subscription(user.id)
    trial_avail = await db.is_trial_available(user.id)

    is_active = sub[3] if sub else False
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

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
    trial_avail = await db.is_trial_available(callback.from_user.id)
    text = "Главное меню:"
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup)
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
    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
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
        "amount": {"value": "11.00", "currency": "RUB"},
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

            text = ("🎁 *Пробный период на 7 дней*\n\n"
                    "Стоимость: 11 рублей.\n\n"
                    "После завершения оплаты в браузере нажмите кнопку «✅ Проверить оплату».\n\n"
                    "Оплачивая пробный период, вы активируете автопродление. Спустя неделю подписка будет продлена на стандартный месяц за 88₽ со счета привязанной карты.\n\n"
                    "Автопродление срабатывает за 24 часа до окончания срока. Отключить его можно в любой момент в разделе «⚙️ Управление подпиской».")
            reply_markup = kb.pay_menu(payment["confirmation"]["confirmation_url"], payment['id'], is_trial=True)

            if callback.message.photo:
                await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error in trial_callback: {e}")
        error_text = "❌ Произошла ошибка. Попробуйте еще раз."
        await callback.message.answer(error_text, reply_markup=kb.back_to_main())
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
        "amount": {"value": "88.00", "currency": "RUB"},
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

            text = ("💳 *Оплата подписки*\n\n"
                    "После завершения оплаты в браузере нажмите кнопку «✅ Проверить оплату».\n\n"
                    "Оплачивая подписку, вы соглашаетесь на её автопродление. Оно будет срабатывать за 24 часа до окончания срока действия текущего тарифа. Средства спишутся со счета, с которого был совершен последний платеж.\n\n"
                    "Отключить автопродление можно в любой момент в разделе «⚙️ Управление подпиской».")
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
        total_seconds = int(delta.total_seconds())

        if total_seconds > 0:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            time_left = f"{days} дн. {hours} ч. {minutes} мин."
        else:
            time_left = "0 дн. 0 ч. 0 мин."

        auto_renew, has_pm = await db.get_user_auto_renew_status(callback.from_user.id)
        renew_status = ""
        if has_pm:
            renew_status = "\n🔄 Автопродление: " + ("ВКЛ" if auto_renew else "ВЫКЛ")

        text = f"✅ *Активна подписка*\n📅 Осталось: `{time_left}`{renew_status}\n🔑 Ключ доступен по кнопке ниже."
        reply_markup = kb.subscription_management_menu(key=key, auto_renew=auto_renew, has_pm=has_pm)
    else:
        trial_avail = await db.is_trial_available(callback.from_user.id)
        text = "❌ *Подписка не активна.*\nАктивируйте её прямо сейчас, чтобы наслаждаться быстрым интернетом без границ! ✨"
        reply_markup = kb.tariffs_menu(trial_available=trial_avail)

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
            metadata = payment.get('metadata', {})
            plan = metadata.get('plan', '1_month')
            days = 7 if plan == 'trial_7_days' else 30

            marzban_username = str(user_id)

            # Check existing subscription in DB to properly add days on renewal
            existing_sub = await db.get_user_subscription(user_id)
            now_utc = datetime.now(timezone.utc)

            if existing_sub and existing_sub[3] and existing_sub[1]:
                # Active subscription exists — extend from its current end date
                sub_end = existing_sub[1]
                if not sub_end.tzinfo:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)
                # If subscription is somehow in the past, extend from now
                base_ts = max(sub_end, now_utc)
            else:
                # New subscription — start from now
                base_ts = now_utc

            expire_ts = int(base_ts.timestamp()) + days * 24 * 3600

            # Try to create user in Marzban (returns existing user on 409)
            user_response = await marzban_api.create_user(
                username=marzban_username,
                data_limit=0,
                expire=expire_ts
            )

            if user_response and "subscription_url" in user_response:
                sub_url = user_response["subscription_url"]

                # If user already existed (renewal case), update their expire in Marzban
                if existing_sub and existing_sub[3]:
                    await marzban_api.update_user_expire(marzban_username, expire_ts)

                # Health-check
                is_valid = await marzban_api.validate_subscription(sub_url)
                if not is_valid:
                    logging.warning(f"Subscription URL for {marzban_username} failed health-check!")
            else:
                logging.error(f"Failed to get subscription_url from Marzban for user {user_id}")
                await callback.answer("Ошибка при создании VPN аккаунта. Обратитесь в поддержку.", show_alert=True)
                return

            # Save payment method for auto-renewal
            pm_id = payment.get("payment_method", {}).get("id")
            if pm_id:
                await db.save_payment_method(user_id, pm_id)
                logging.info(f"Saved payment method {pm_id} for user {user_id}")

            # Save to DB — activate_subscription already handles adding days correctly
            await db.activate_subscription(user_id, "Стандарт", days, sub_url)
            await db.reset_failed_payments(user_id)

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
    sub = await db.get_user_subscription(message.from_user.id)
    is_active = sub[3] if sub else False
    trial_avail = await db.is_trial_available(message.from_user.id)
    await message.answer("Используйте кнопки меню!", reply_markup=kb.main_menu(is_active=is_active, trial_available=trial_avail))
