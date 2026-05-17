import logging
from datetime import datetime, timezone
from aiogram import Bot
from aiogram.types import Message
from . import database as db
from . import keyboards as kb
from .marzban_api import marzban_api
from .config import config
from .utils import send_menu_with_logo

async def process_successful_payment(
    bot: Bot, 
    user_id: int, 
    payment_id: str, 
    payment: dict, 
    is_background: bool = False, 
    message_to_edit: Message = None
) -> bool:
    """
    Handles the core logic of activating a subscription after a successful payment.
    Returns True if activated successfully, False if it was already processed.
    """
    try:
        # 3. Подготовка данных
        metadata = payment.get('metadata') or {}
        plan = metadata.get('plan', '1_month')
        days = 7 if plan == 'trial_7_days' else 30
        amount = float((payment.get('amount') or {}).get('value', 0))
        marzban_username = str(user_id)
        now = datetime.now(timezone.utc)

        # 4. Взаимодействие с Marzban
        existing_sub = await db.get_user_subscription(user_id)
        
        base_ts = now
        if existing_sub and existing_sub[3] and existing_sub[1]:
            sub_end = existing_sub[1].replace(tzinfo=timezone.utc) if not existing_sub[1].tzinfo else existing_sub[1]
            base_ts = max(sub_end, now)

        expire_ts = int(base_ts.timestamp()) + days * 24 * 3600

        # 1. Извлекаем токен
        existing_key = existing_sub[2] if existing_sub else None
        forced_token = marzban_api.extract_token(existing_key) if existing_key else None
        
        if forced_token:
            logging.info(f"Extracted forced_token {forced_token[:12]}... from existing key for user {user_id}")
        elif existing_key and "vless://" in existing_key:
            logging.info(f"Existing key for {user_id} is VLESS, skipping token extraction.")

        # 2. Синхронизируем
        user_response = await marzban_api.sync_user_subscription(
            username=marzban_username,
            expire_ts=expire_ts,
            forced_token=forced_token
        )
        
        if not user_response:
            raise Exception(f"Failed to sync user {marzban_username} in Marzban")

        sub_url = user_response.get("subscription_url") or (user_response.get("links")[0] if user_response.get("links") else None)

        if not sub_url:
            raise Exception(f"No subscription URL returned for user {marzban_username}")

        if sub_url.startswith('/'):
            base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
            sub_url = f"{base_url}{sub_url}"

        # Определяем ключ: если у пользователя уже есть ссылка подписки, мы просто сохраняем её!
        vpn_key_to_save = sub_url
        
        if existing_key and "/sub/" in existing_key:
            vpn_key_to_save = existing_key
            logging.info(f"User {user_id} already has a subscription link. Keeping existing link: {existing_key}")
        elif existing_key:
            logging.info(f"Upgrading user {user_id} from VLESS/config to subscription link.")

        # 5. Активация в БД
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
            return False

        await db.reset_failed_payments(user_id)

        # Сохраняем метод оплаты
        pm_id = payment.get("payment_method", {}).get("id")
        if pm_id:
            await db.save_payment_method(user_id, pm_id)

        # 6. Отправка уведомления
        if is_background:
            success_text = "✨ *Оплата получена в фоновом режиме!*\nВаша подписка успешно активирована. 🚀"
        else:
            success_text = "✨ *Оплата прошла успешно!*\nВаша подписка активирована. 🚀"

        reply_markup = kb.success_payment_menu(vpn_key_to_save)

        try:
            await send_menu_with_logo(
                bot=bot,
                chat_id=user_id,
                text=success_text,
                reply_markup=reply_markup,
                message_to_edit=message_to_edit if not is_background else None
            )
        except Exception as e:
            logging.error(f"Failed to send success payment menu: {e}")

        return True

    except Exception as e:
        logging.error(f"Error in process_successful_payment for {user_id}: {e}", exc_info=True)
        raise
