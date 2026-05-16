from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton

# Constants for easy maintenance
INSTRUCTION_URL = "https://teletype.in/@aleksandrpos/GWmBr-MmbsK"
CHANNEL_URL = "https://t.me/HealVPN"
SUPPORT_URL = "https://t.me/heal_vpn_support"
PRICE_TRIAL = 11
PRICE_MONTH = 88

def main_menu(is_active=False, trial_available=False) -> InlineKeyboardMarkup:
    """Main menu of the bot."""
    purchase_text = "💳 Продлить подписку" if is_active else "💳 Приобрести подписку"
    buttons = []
    
    if trial_available and not is_active:
        buttons.append([InlineKeyboardButton(text=f"🎁 Попробовать 7 дней за {PRICE_TRIAL}₽", callback_data="trial")])
    
    buttons.extend([
        [InlineKeyboardButton(text=purchase_text, callback_data="tariffs", style="success")],
        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="subscription_mgmt", style="success")],
        [InlineKeyboardButton(text="ℹ️ Информация о нас", callback_data="about")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tariffs_menu(trial_available=False) -> InlineKeyboardMarkup:
    """Menu with available tariffs."""
    buttons = []
    if trial_available:
        buttons.append([InlineKeyboardButton(text=f"🎁 Попробовать 7 дней за {PRICE_TRIAL}₽", callback_data="trial")])
    
    buttons.extend([
        [InlineKeyboardButton(text="📱 5 устройств", callback_data="devices_5", style="success")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def pay_menu(payment_url: str, payment_id: str, is_trial=False) -> InlineKeyboardMarkup:
    """Menu with payment link and verification button."""
    text = f"💳 Оплатить 7 дней за {PRICE_TRIAL} ₽" if is_trial else f"💳 Оплатить 1 месяц за {PRICE_MONTH} ₽"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, url=payment_url, style="success")],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_pay:{payment_id}", style="success")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tariffs")]
    ])

def subscription_management_menu(key: str = None, auto_renew: bool = True) -> InlineKeyboardMarkup:
    """Menu for managing active subscription."""
    copy_btn = (
        InlineKeyboardButton(text="🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), style="success")
        if key
        else InlineKeyboardButton(text="🔑 Скопировать ключ", callback_data="copy_key", style="success")
    )
    
    buttons = [
        [copy_btn],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", url=INSTRUCTION_URL, style="success")],
    ]
    
    # Show auto-renew toggle
    if auto_renew:
        buttons.append([InlineKeyboardButton(text="❌ Выключить автопродление", callback_data="disable_auto_renew")])
    else:
        buttons.append([InlineKeyboardButton(text="✅ Включить автопродление", callback_data="enable_auto_renew")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_to_main() -> InlineKeyboardMarkup:
    """Simple back to main menu button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def success_payment_menu(key: str) -> InlineKeyboardMarkup:
    """Menu shown after successful payment."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), style="success")],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", url=INSTRUCTION_URL, style="success")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def about_menu() -> InlineKeyboardMarkup:
    """Information menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Наш канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="👤 Связаться с менеджером", url=SUPPORT_URL)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
