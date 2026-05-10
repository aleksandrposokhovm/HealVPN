from telegram import InlineKeyboardButton

try:
    btn = InlineKeyboardButton(text="test", callback_data="test", style="success")
    print("Success! Style is supported.")
except TypeError as e:
    print(f"Failed: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
