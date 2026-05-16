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

processed_payments_cache = {}
LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "logo_horizontal.png"
))
LOGO_FILE_ID = None

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
    global LOGO_FILE_ID
    user = message.from_user

    await db.add_user(user.id, user.username, user.first_name)
    sub = await db.get_user_subscription(user.id)
    trial_avail = await db.is_trial_available(user.id)

    is_active = sub[3] if sub else False
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

    if os.path.exists(LOGO_PATH) or LOGO_FILE_ID:
        try:
            photo = LOGO_FILE_ID if LOGO_FILE_ID else FSInputFile(LOGO_PATH)
            sent_msg = await message.answer_photo(
                photo=photo,
                caption=WELCOME_TEXT,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            if not LOGO_FILE_ID:
                LOGO_FILE_ID = sent_msg.photo[-1].file_id
        except Exception as e:
            logging.error(f"Error sending photo: {e}")
            await message.answer(WELCOME_TEXT, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.answer(WELCOME_TEXT, reply_markup=reply_markup, parse_mode="Markdown")


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    sub = await db.get_user_subscription(callback.from_user.id)
    is_active = sub[3] if sub else False
    trial_avail = await db.is_trial_available(callback.from_user.id)
    reply_markup = kb.main_menu(is_active=is_active, trial_available=trial_avail)

    if callback.message.photo:
        await callback.message.edit_caption(caption=WELCOME_TEXT, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=WELCOME_TEXT, reply_markup=reply_markup, parse_mode="Markdown")
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

            text = ("🎁 *Пробный период на 7 дней*\n\n"
                    f"Стоимость: {kb.PRICE_TRIAL} рублей.\n\n"
                    "После завершения оплаты в браузере нажмите кнопку «✅ Проверить оплату».\n\n"
                    f"Оплачивая пробный период, вы активируете автопродление. Спустя неделю подписка будет продлена на стандартный месяц за {kb.PRICE_MONTH}₽ со счета привязанной карты.\n\n"
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

            text = ("💳 *Подписка на 1 месяц*\n\n"
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

    if callback.message.photo:
        await callback.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
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
            # 3. Подготовка данных
            metadata = payment.get('metadata', {})
            plan = metadata.get('plan', '1_month')
            days = 7 if plan == 'trial_7_days' else 30
            amount = float(payment.get('amount', {}).get('value', 0))
            marzban_username = str(user_id)

            # 4. Взаимодействие с Marzban
            # Рассчитываем время окончания
            existing_sub = await db.get_user_subscription(user_id)
            
            base_ts = now
            if existing_sub and existing_sub[3] and existing_sub[1]:
                sub_end = existing_sub[1].replace(tzinfo=timezone.utc) if not existing_sub[1].tzinfo else existing_sub[1]
                base_ts = max(sub_end, now)

            expire_ts = int(base_ts.timestamp()) + days * 24 * 3600

            # 1. Извлекаем токен из существующей ссылки, чтобы гарантировать преемственность
            forced_token = marzban_api.extract_token(existing_key)
            if forced_token:
                logging.info(f"Extracted forced_token {forced_token[:12]}... from existing key for user {user_id}")
            elif existing_key and "vless://" in existing_key:
                # Если это VLESS ссылка, мы не можем легко вытащить токен подписки
                logging.info(f"Existing key for {user_id} is VLESS, skipping token extraction.")

            # 2. Синхронизируем пользователя в Marzban (создаст или обновит)
            user_response = await marzban_api.sync_user_subscription(
                username=marzban_username,
                expire_ts=expire_ts,
                forced_token=forced_token
            )
            
            if not user_response:
                raise Exception(f"Failed to sync user {marzban_username} in Marzban")

            # 3. Получаем актуальную ссылку из ответа Marzban
            sub_url = user_response.get("subscription_url") or (user_response.get("links")[0] if user_response.get("links") else None)

            if not sub_url:
                raise Exception(f"No subscription URL returned for user {marzban_username}")

            if sub_url.startswith('/'):
                base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
                sub_url = f"{base_url}{sub_url}"

            # 4. Определяем какой ключ сохранить
            # ПРАВИЛО: Если у нас был ключ и это была ссылка на подписку, мы ОЧЕНЬ хотим ее оставить.
            # Если Marzban вернул ту же самую ссылку (или с тем же токеном), оставляем старую.
            
            vpn_key_to_save = sub_url # По умолчанию берем новую
            
            # Пробуем вытащить токен из новой ссылки (если она есть)
            new_token = marzban_api.extract_token(sub_url)
            
            # Если в ответе Marzban нет /sub/ ссылки, но мы ее нашли выше в sync_user_subscription (в links)
            # или если мы точно знаем какой токен мы форсировали
            actual_token = new_token or forced_token
            
            if existing_key and "/sub/" in existing_key:
                # Пытаемся понять, изменился ли токен в новой ссылке по сравнению со старой
                old_token = marzban_api.extract_token(existing_key)
                
                if old_token and actual_token and old_token == actual_token:
                    # Токены совпали! Значит ссылка по сути та же. 
                    # Оставляем существующую (она может иметь другой домен или параметры, которые юзеру привычнее)
                    vpn_key_to_save = existing_key
                    logging.info(f"Token matched for user {user_id}, preserving existing key: {existing_key}")
                elif old_token and not new_token:
                    # Если новая ссылка — не подписка, а старая была подпиской, 
                    # и мы знаем, что токен не менялся (потому что мы его форсировали)
                    # то ОСТАВЛЯЕМ старую ссылку.
                    vpn_key_to_save = existing_key
                    logging.info(f"New link is not sub, but old was. Preserving existing key for {user_id}")
                else:
                    logging.warning(f"Token CHANGED for user {user_id}! Old: {old_token}, New: {new_token}. Updating to new link.")
            elif existing_key:
                # Если старый ключ был VLESS, а новый - подписка, переходим на подписку
                logging.info(f"Upgrading user {user_id} from VLESS to subscription link.")

            success = await db.activate_subscription(
                user_id=user_id,
                plan_name="Стандарт",
                duration_days=days,
                vpn_key=vpn_key_to_save,
                payment_id=payment_id,
                amount=amount,
                plan=plan
            )

            if not success:
                # Значит платеж уже был обработан кем-то другим (race condition в БД пресечен)
                await callback.answer("Эта оплата уже была успешно обработана. ✅", show_alert=True)
                return

            await db.reset_failed_payments(user_id)

            # Сохраняем метод оплаты для автопродления
            pm_id = payment.get("payment_method", {}).get("id")
            if pm_id:
                await db.save_payment_method(user_id, pm_id)

            # 6. Финальное обновление кэша и интерфейса
            processed_payments_cache[payment_id] = datetime.now(timezone.utc)

            success_text = "✨ *Оплата прошла успешно!*\nВаша подписка активирована. 🚀"
                
            reply_markup = kb.success_payment_menu(vpn_key_to_save)

            if callback.message.photo:
                await callback.message.edit_caption(caption=success_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                await callback.message.edit_text(text=success_text, reply_markup=reply_markup, parse_mode="Markdown")

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
