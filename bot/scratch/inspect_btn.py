from telegram import InlineKeyboardButton

btn = InlineKeyboardButton(text="test", callback_data="test", style="success")
print(f"Button dict: {btn.to_dict()}")
