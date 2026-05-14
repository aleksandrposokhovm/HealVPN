from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton

def main_menu(is_active=False, trial_available=False) -> InlineKeyboardMarkup:
    purchase_text = "💳 Продлить подписку" if is_active else "💳 Приобрести подписку"
    buttons = []
    
    if trial_available and not is_active:
        buttons.append([InlineKeyboardButton(text="🎁 Попробовать 7 дней за 11₽", callback_data="trial", **{"style": "success"})])
    
    buttons.extend([
        [InlineKeyboardButton(text=purchase_text, callback_data="tariffs", **{"style": "success"})],
        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="subscription_mgmt", **{"style": "success"})],
        [InlineKeyboardButton(text="ℹ️ Информация о нас", callback_data="about")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def tariffs_menu(trial_available=False) -> InlineKeyboardMarkup:
    buttons = []
    if trial_available:
        buttons.append([InlineKeyboardButton(text="🎁 Попробовать 7 дней за 11₽", callback_data="trial", **{"style": "success"})])
    
    buttons.extend([
        [InlineKeyboardButton(text="📱 5 устройств", callback_data="devices_5", **{"style": "success"})],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def pay_menu(payment_url: str, payment_id: str, is_trial=False) -> InlineKeyboardMarkup:
    amount_text = "11 рублей" if is_trial else "111 рублей"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {amount_text}", url=payment_url, **{"style": "success"})],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_pay:{payment_id}", **{"style": "success"})],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tariffs")]
    ])

def subscription_management_menu(key: str = None, auto_renew: bool = True, has_pm: bool = False) -> InlineKeyboardMarkup:
    copy_btn = (
        InlineKeyboardButton(text="🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), **{"style": "success"})
        if key
        else InlineKeyboardButton(text="🔑 Скопировать ключ", callback_data="copy_key", **{"style": "success"})
    )
    
    buttons = [
        [copy_btn],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", url="https://teletype.in/@aleksandrpos/GWmBr-MmbsK", **{"style": "success"})],
    ]
    
    # Only show auto-renew toggle if user has a saved payment method
    if has_pm:
        if auto_renew:
            buttons.append([InlineKeyboardButton(text="❌ Выключить автопродление", callback_data="disable_auto_renew")])
        else:
            buttons.append([InlineKeyboardButton(text="✅ Включить автопродление", callback_data="enable_auto_renew")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)



def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def success_payment_menu(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), **{"style": "success"})],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", url="https://teletype.in/@aleksandrpos/GWmBr-MmbsK", **{"style": "success"})],
        [InlineKeyboardButton(text="🔙 На главное меню", callback_data="main_menu")]
    ])

def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/HealVPN")],
        [InlineKeyboardButton(text="👤 Связаться с менеджером", url="https://t.me/heal_vpn_support")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
