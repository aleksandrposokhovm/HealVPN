from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu(is_active=False):
    purchase_text = "💳 Продлить подписку" if is_active else "💳 Приобрести подписку"
    keyboard = [
        [InlineKeyboardButton(purchase_text, callback_data="tariffs", style="success")],
        [InlineKeyboardButton("⚙️ Управление подпиской", callback_data="subscription_mgmt", style="success")],
        [InlineKeyboardButton("ℹ️ Информация о нас", callback_data="about")]
    ]
    return InlineKeyboardMarkup(keyboard)

def tariffs_menu():
    keyboard = [
        [InlineKeyboardButton("📱 5 устройств", callback_data="devices_5", style="success")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def pay_menu(payment_url: str, payment_id: str):
    keyboard = [
        [InlineKeyboardButton("💳 Оплатить подписку на 1 месяц", url=payment_url, style="success")],
        [InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_pay:{payment_id}", style="success")],
        [InlineKeyboardButton("🔙 Назад", callback_data="tariffs")]
    ]
    return InlineKeyboardMarkup(keyboard)

from telegram import CopyTextButton

def subscription_management_menu(key=None):
    if key:
        copy_btn = InlineKeyboardButton("🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), style="success")
    else:
        copy_btn = InlineKeyboardButton("🔑 Скопировать ключ", callback_data="copy_key", style="success")

    keyboard = [
        [copy_btn],
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
def success_payment_menu(key):
    keyboard = [
        [InlineKeyboardButton("Скопировать ключ", copy_text=CopyTextButton(text=key), style="success")],
        [InlineKeyboardButton("Инструкция по подключению", callback_data="instruction", style="success")],
        [InlineKeyboardButton("На главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def about_menu():
    keyboard = [
        [InlineKeyboardButton("📢 Наш канал", url="https://t.me/HealVPN")],
        [InlineKeyboardButton("👤 Связаться с менеджером", url="https://t.me/heal_vpn_support")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
