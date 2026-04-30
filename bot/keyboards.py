from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("⚙️ Как подключить", callback_data="instructions")],
        [InlineKeyboardButton("🆘 Поддержка", url="https://t.me/your_support_handle")]
    ]
    return InlineKeyboardMarkup(keyboard)

def tariffs_menu():
    keyboard = [
        [InlineKeyboardButton("🚀 1 месяц — 150₽", callback_data="buy_1_month")],
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_main():
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
