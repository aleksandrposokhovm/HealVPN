from telegram import Update, constants
from telegram.ext import ContextTypes
import keyboards as kb
import database as db
import os
from datetime import datetime
from groq import Groq
from config import config
from yookassa import Configuration, Payment
import uuid
import secrets
import string

# YuKassa Configuration
Configuration.account_id = config.YOOKASSA_SHOP_ID
Configuration.secret_key = config.YOOKASSA_SECRET_KEY.get_secret_value()

# Initialize Groq client
groq_client = Groq(api_key=config.GROQ_API_KEY.get_secret_value())

# Directory for saved files
DOWNLOADS_DIR = "downloads"
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

LOGO_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "website", "assets", "logo_horizontal.png"
))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user.id, user.username, user.full_name)

    welcome_text = (
        "Вижу твой интерес! 👋 Позволь рассказать, почему HealVPN станет твоим лучшим выбором:\n\n"
        "⚡️ **Скорость** — мгновенная загрузка любого контента.\n"
        "🛡 **Приватность** — защита данных от слежки в любой сети.\n"
        "🌐 **Доступ** — стабильная связь с глобальными ресурсами.\n"
        "🖥 **Надёжность** — работа 24/7 и подключение в одно касание.\n\n"
        "Ваш интернет под надёжной защитой. Жми кнопку ниже и лети! 🚀"
    )



    if os.path.exists(LOGO_PATH):
        try:
            with open(LOGO_PATH, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=welcome_text,
                    reply_markup=kb.main_menu(),
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            print("DEBUG: reply_photo successful")
        except Exception as e:
            print(f"DEBUG: Error sending photo: {e}")
            await update.message.reply_text(
                welcome_text,
                reply_markup=kb.main_menu(),
                parse_mode=constants.ParseMode.MARKDOWN,
            )
    else:
        print("DEBUG: LOGO_PATH does not exist, falling back to text")
        await update.message.reply_text(
            welcome_text,
            reply_markup=kb.main_menu(),
            parse_mode=constants.ParseMode.MARKDOWN,
        )


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = "Главное меню:"
    reply_markup = kb.main_menu()

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

    text = (
        "🚀 **Тариф: 10 устройств**\n\n"
        "Доступ на 1 месяц для 10 ваших устройств.\n"
        "Цена: **111 рублей**"
    )
    # Create payment and provide direct payment URL keyboard
    try:
        payment = Payment.create({
            "amount": {"value": "111.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": f"https://t.me/{context.bot.username}"},
            "capture": True,
            "description": f"Подписка HealVPN на 1 месяц для пользователя {query.from_user.id}",
            "metadata": {"user_id": query.from_user.id, "plan": "1_month"}
        }, uuid.uuid4())
        payment_url = payment.confirmation.confirmation_url
        payment_id = payment.id
        # Edit message to show payment info with direct URL button
        text = (
            "💳 **Оплата подписки**\n\n"
            "Тариф: **Стандарт (1 месяц)**\n"
            "Сумма: **111 рублей**\n\n"
            "Нажмите кнопку ниже, чтобы перейти к оплате. Оплата будет проверена автоматически сразу после завершения платежа."
        )
        sent_message = await query.edit_message_caption(
            caption=text,
            reply_markup=kb.pay_menu(payment_url),
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        # Schedule automatic payment check
        context.job_queue.run_repeating(
            auto_check_payment,
            interval=2,
            first=2,
            data={
                "payment_id": payment_id,
                "user_id": query.from_user.id,
                "chat_id": query.message.chat_id,
                "message_id": sent_message.message_id,
            },
            name=f"check_{payment_id}"
        )
    except Exception as e:
        print(f"Error creating payment: {e}")
        await query.edit_message_caption(
            caption="❌ Произошла ошибка при создании платежа. Попробуйте позже или обратитесь в поддержку.",
            reply_markup=kb.back_to_main()
        )
        return

    return

async def subscription_mgmt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    sub = await db.get_user_subscription(user_id)

    if sub:
        plan, end_date, key, active = sub
        # Calculate days remaining
        if isinstance(end_date, str):
            try:
                if "." in end_date:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S.%f")
                else:
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                end_dt = datetime.fromisoformat(end_date)
        else:
            end_dt = end_date

        days_left = (end_dt - datetime.now()).days
        if days_left < 0: days_left = 0

        text = (
            f"✅ **У вас активна подписка**\n\n"
            f"📅 Осталось дней: `{days_left}`\n"
            f"📱 Доступно устройств: `10`\n\n"
            f"🔑 Ваш ключ: `{key}`"
        )
        reply_markup = kb.subscription_management_menu()
    else:
        text = (
            f"❌ **У вас нет активной подписки**\n\n"
            "Выберите количество устройств для оформления подписки и получения доступа к HealVPN:"
        )
        reply_markup = kb.tariffs_menu()

    await query.answer()
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)

async def copy_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    sub = await db.get_user_subscription(user_id)

    if sub:
        plan, end_date, key, active = sub
        await query.answer("Ключ скопирован!", show_alert=True)
        # Send the key in a separate message with mono font for easy copying
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Ваш ключ (нажмите, чтобы скопировать):\n\n`{key}`",
            parse_mode=constants.ParseMode.MARKDOWN
        )
    else:
        await query.answer("У вас нет активного ключа", show_alert=True)

async def instruction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "📖 **Инструкция по подключению**\n\n"
        "1. Скачайте приложение **Outline** или **WireGuard**.\n"
        "2. Скопируйте ваш ключ из раздела управления подпиской.\n"
        "3. В приложении нажмите «Добавить сервер» и вставьте ключ.\n"
        "4. Нажмите «Подключиться».\n\n"
        "Если у вас возникли вопросы, обратитесь в поддержку: @P777MP77"
    )
    reply_markup = kb.instruction_menu()

    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN)

async def connect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🔗 **Как подключиться?**\n\n"
        "1. Скопируйте ваш ключ из раздела профиля.\n"
        "2. Установите приложение **Outline**.\n"
        "3. Добавьте новый сервер и вставьте ключ.\n\n"
        "Если возникли сложности, обратитесь в поддержку."
    )
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN)

async def my_devices_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📱 **Ваши устройства**\n\nПо вашей подписке доступно одновременное подключение до **10 устройств**."
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await query.edit_message_text(text=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN)

async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📢 **Инструкция и поддержка**\n\n"
        "⚙️ **Как подключить:**\n"
        "1. Скачайте приложение [WireGuard](https://www.wireguard.com/install/) или [Outline](https://getoutline.org/).\n"
        "2. Скопируйте ваш ключ из раздела «Мой профиль».\n"
        "3. Добавьте новый сервер в приложении.\n\n"
        "🆘 **Поддержка:**\n"
        "Если у вас возникли вопросы, пишите нашему администратору: @P777MP77"
    )
    reply_markup = kb.back_to_main()

    if query.message.photo:
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    else:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "🔥 **Реферальная программа**\n\n"
        "Приглашайте друзей и получайте бонусы! 🎁\n"
        "Ваша реферальная ссылка: (в разработке)\n\n"
        "За каждого приведенного друга вы получите 15 дней бесплатного доступа."
    )
    await query.edit_message_caption(caption=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN) if query.message.photo else await query.edit_message_text(text=text, reply_markup=kb.back_to_main(), parse_mode=constants.ParseMode.MARKDOWN)

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "✦ **Информация о нас**\n\n"
        "HealVPN — это проект, созданный для обеспечения свободного и безопасного доступа к информации.\n\n"
        "✅ Высокая скорость\n"
        "✅ Полная анонимность\n"
        "✅ Поддержка 24/7\n\n"
        "Мы используем современные протоколы шифрования, чтобы ваши данные оставались в безопасности."
    )
    await query.edit_message_caption(caption=text, reply_markup=kb.about_menu(), parse_mode=constants.ParseMode.MARKDOWN) if query.message.photo else await query.edit_message_text(text=text, reply_markup=kb.about_menu(), parse_mode=constants.ParseMode.MARKDOWN)

async def auto_check_payment(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    payment_id = job.data["payment_id"]
    user_id = job.data["user_id"]
    chat_id = job.data["chat_id"]
    message_id = job.data["message_id"]
    
    # Increment attempt counter
    attempts = job.data.get("attempts", 0)
    if attempts > 300:  # Stop after 10 minutes (300 * 2s)
        job.schedule_removal()
        return
    job.data["attempts"] = attempts + 1

    try:
        payment = Payment.find_one(payment_id)

        if payment.status == 'succeeded':
            import secrets
            import string
            new_key = "ss://" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)) + "@123.123.123.123:1234/?outline=1"
            await db.activate_subscription(user_id, "Стандарт", 30, new_key)

            success_text = (
                "🎉 **Оплата прошла успешно!**\n\n"
                "Ваша подписка на 1 месяц активирована.\n\n"
                f"🔑 Ваш ключ доступа:\n`{new_key}`\n\n"
                "Нажмите на ключ, чтобы скопировать его. Инструкции по подключению в разделе «Помощь»."
            )

            # Edit the original payment message
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=success_text,
                reply_markup=kb.main_menu(),
                parse_mode=constants.ParseMode.MARKDOWN
            )

            # Also send a fresh message so the user gets a notification
            await context.bot.send_message(
                chat_id=chat_id,
                text=success_text,
                reply_markup=kb.main_menu(),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            job.schedule_removal()
        elif payment.status == 'canceled':
            fail_text = "❌ **Оплата не прошла**, давай попробуем еще раз"
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=fail_text,
                reply_markup=kb.tariffs_menu(),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            job.schedule_removal()
    except Exception as e:
        print(f"Error in auto_check_payment: {e}")

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
