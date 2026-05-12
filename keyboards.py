from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton

def main_menu(is_active=False) -> InlineKeyboardMarkup:
    purchase_text = "💳 Продлить подписку" if is_active else "💳 Приобрести подписку"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=purchase_text, callback_data="tariffs", **{"style": "success"})],
        [InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="subscription_mgmt", **{"style": "success"})],
        [InlineKeyboardButton(text="ℹ️ Информация о нас", callback_data="about")]
    ])

def tariffs_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 5 устройств", callback_data="devices_5", **{"style": "success"})],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])

def pay_menu(payment_url: str, payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить подписку на 1 месяц", url=payment_url, **{"style": "success"})],
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
        [InlineKeyboardButton(text="📖 Инструкция по подключению", callback_data="instruction", **{"style": "success"})],
    ]
    
    # Only show auto-renew toggle if user has a saved payment method
    if has_pm:
        status = "ВКЛ ✅" if auto_renew else "ВЫКЛ ❌"
        buttons.append([InlineKeyboardButton(text=f"🔄 Автопродление: {status}", callback_data="toggle_auto_renew")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
        [InlineKeyboardButton(text="🔑 Скопировать ключ", copy_text=CopyTextButton(text=key), **{"style": "success"})],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", callback_data="instruction", **{"style": "success"})],
        [InlineKeyboardButton(text="🔙 На главное меню", callback_data="main_menu")]
    ])

def about_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Наш канал", url="https://t.me/HealVPN")],
        [InlineKeyboardButton(text="👤 Связаться с менеджером", url="https://t.me/heal_vpn_support")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
