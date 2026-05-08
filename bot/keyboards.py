from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💳 Приобрести подписку", callback_data="tariffs", style="success")],
        [InlineKeyboardButton("⚙️ Управление подпиской", callback_data="subscription_mgmt", style="success")],
        [InlineKeyboardButton("ℹ️ Информация о нас", callback_data="about")]
    ]
    return InlineKeyboardMarkup(keyboard)

def tariffs_menu():
    keyboard = [
        [InlineKeyboardButton("📱 10 устройств", callback_data="devices_10", style="success")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def pay_menu(payment_url: str):
    """Return a keyboard with a direct payment URL for a 1‑month subscription.
    Args:
        payment_url: The URL generated via the ЮKassa API.
    """
    keyboard = [
        [InlineKeyboardButton("💳 Оплатить подписку на 1 месяц", url=payment_url, style="success")],
        [InlineKeyboardButton("🔙 Назад", callback_data="tariffs")]
    ]
    return InlineKeyboardMarkup(keyboard)

def subscription_management_menu():
    keyboard = [
        [InlineKeyboardButton("🔑 Скопировать ключ", callback_data="copy_key", style="success")],
        [InlineKeyboardButton("📖 Инструкция по подключению", callback_data="instruction", style="success")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def instruction_menu():
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="subscription_mgmt")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_main():
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
def about_menu():
    keyboard = [
        [InlineKeyboardButton("📢 Наш канал", url="https://t.me/HealVPN")],
        [InlineKeyboardButton("👤 Связаться с менеджером", url="https://t.me/P777MP77")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
