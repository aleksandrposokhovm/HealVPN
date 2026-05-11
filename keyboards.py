from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu(is_active=False) -> InlineKeyboardMarkup:
    purchase_text = "💳 Продлить подписку" if is_active else "💳 Приобрести подписку"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=purchase_text, callback_data="tariffs")],
        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="subscription_mgmt")],
        [InlineKeyboardButton(text="ℹ️ Информация о нас", callback_data="about")]
    ])

def tariffs_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 5 устройств", callback_data="devices_5")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def pay_menu(payment_url: str, payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить подписку на 1 месяц", url=payment_url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_pay:{payment_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tariffs")]
    ])

def subscription_management_menu(key: str = None) -> InlineKeyboardMarkup:
    # Aiogram 3 doesn't have native CopyTextButton, usually we just send the key in markdown
    # and users can tap to copy. Or use url if it's a URL.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Скопировать ключ", callback_data="copy_key")],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", callback_data="instruction")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def instruction_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="subscription_mgmt")]
    ])

def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def success_payment_menu(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Показать ключ", callback_data="copy_key")],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", callback_data="instruction")],
        [InlineKeyboardButton(text="🔙 На главное меню", callback_data="main_menu")]
    ])

def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/HealVPN")],
        [InlineKeyboardButton(text="👤 Связаться с менеджером", url="https://t.me/heal_vpn_support")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
