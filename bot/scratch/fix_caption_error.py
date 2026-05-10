import sys

path = '/Users/aleksandrposokhov/Life/02_Business/01_HealVPN/bot/handlers.py'
with open(path, 'r') as f:
    content = f.read()

# Fix devices_callback
old_devices_edit = """        # Step 1: Show initial "Pay" button only
        await query.edit_message_caption(
            caption=text,
            reply_markup=kb.pre_pay_menu(payment_id),
            parse_mode=constants.ParseMode.MARKDOWN,
        )"""

new_devices_edit = """        # Step 1: Show initial "Pay" button only
        if query.message.photo:
            await query.edit_message_caption(
                caption=text,
                reply_markup=kb.pre_pay_menu(payment_id),
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        else:
            await query.edit_message_text(
                text=text,
                reply_markup=kb.pre_pay_menu(payment_id),
                parse_mode=constants.ParseMode.MARKDOWN,
            )"""

content = content.replace(old_devices_edit, new_devices_edit)

# Fix init_pay_callback
old_init_edit = """        await query.edit_message_caption(
            caption=text,
            reply_markup=kb.pay_menu(payment_url, payment_id),
            parse_mode=constants.ParseMode.MARKDOWN
        )"""

new_init_edit = """        if query.message.photo:
            await query.edit_message_caption(
                caption=text,
                reply_markup=kb.pay_menu(payment_url, payment_id),
                parse_mode=constants.ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(
                text=text,
                reply_markup=kb.pay_menu(payment_url, payment_id),
                parse_mode=constants.ParseMode.MARKDOWN
            )"""

content = content.replace(old_init_edit, new_init_edit)

with open(path, 'w') as f:
    f.write(content)
print("Success")
