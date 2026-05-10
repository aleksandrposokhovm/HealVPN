# Инструкция по деплою HealVPN Bot

## 1. Подготовка сервера (Ubuntu/Debian)
```bash
# Обновляем пакеты
sudo apt update && sudo apt upgrade -y

# Устанавливаем Python и pip (если нет)
sudo apt install python3 python3-pip python3-venv -y
```

## 2. Копирование файлов
Перенесите папку `bot` на сервер (например, через `scp` или `git clone`).

## 3. Настройка окружения
```bash
cd bot

# Создаем виртуальное окружение
python3 -m venv venv

# Активируем его
source venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt
```

## 4. Настройка .env
Убедитесь, что в папке `bot` есть файл `.env` со всеми актуальными ключами:
- `BOT_TOKEN`
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `MARZBAN_URL`
- `MARZBAN_ADMIN_USERNAME`
- `MARZBAN_ADMIN_PASSWORD`

## 5. Запуск через systemd (стабильная работа)
Чтобы бот работал всегда и перезапускался сам при сбоях:

```bash
# Создаем файл сервиса
sudo nano /etc/systemd/system/healvpn-bot.service
```

Вставьте следующее содержимое (замените `YOUR_USER` и `/path/to/bot` на реальные данные):
```ini
[Unit]
Description=HealVPN Telegram Bot
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/path/to/bot
ExecStart=/path/to/bot/venv/bin/python3 run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**Активация сервиса:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable healvpn-bot
sudo systemctl start healvpn-bot

# Проверка статуса
sudo systemctl status healvpn-bot
```

## 6. Логи
Логи теперь пишутся в файл `bot/bot.log` и в консоль одновременно.
Для просмотра логов в реальном времени:
```bash
tail -f bot.log
# или через systemd:
journalctl -u healvpn-bot -f
```
