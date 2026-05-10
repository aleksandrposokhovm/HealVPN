import sys

path = '/Users/aleksandrposokhov/Life/02_Business/01_HealVPN/bot/handlers.py'
with open(path, 'r') as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if 'async def auto_check_payment' in line:
        start_idx = i
    if start_idx != -1 and 'async def check_payment_callback' in line:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    new_func = [
        'async def init_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):\n',
        '    query = update.callback_query\n',
        '    await query.answer()\n',
        '    payment_id = query.data.split(":")[1]\n',
        '    try:\n',
        '        headers = await get_yookassa_headers()\n',
        '        client = await get_http_client()\n',
        '        response = await client.get(f"https://api.yookassa.ru/v3/payments/{payment_id}", headers=headers)\n',
        '        payment = response.json()\n',
        '        if "confirmation" not in payment:\n',
        '            await query.answer("Ошибка: ссылка на оплату не найдена.", show_alert=True)\n',
        '            return\n',
        '        payment_url = payment["confirmation"]["confirmation_url"]\n',
        '        text = "💳 **Оплата подписки**\\n\\nТариф: **Стандарт (1 месяц)**\\nСумма: **111 рублей**\\n\\nПерейдите по ссылке ниже для оплаты. После завершения обязательно вернитесь и нажмите кнопку **«Проверить оплату»**."\n',
        '        await query.edit_message_caption(caption=text, reply_markup=kb.pay_menu(payment_url, payment_id), parse_mode=constants.ParseMode.MARKDOWN)\n',
        '    except Exception as e:\n',
        '        print(f"Error in init_pay: {e}")\n',
        '        await query.answer("Произошла ошибка при получении ссылки.", show_alert=True)\n',
        '\n\n'
    ]
    lines[start_idx:end_idx] = new_func
    with open(path, 'w') as f:
        f.writelines(lines)
    print("Success")
else:
    print(f"Indices not found: start={start_idx}, end={end_idx}")
