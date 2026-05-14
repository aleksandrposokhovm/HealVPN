# 🛡 Полное руководство администратора HealVPN

Этот документ содержит все необходимые команды для управления ботом, сервером и базой данных.

---

## 🛠 1. Управление пользователями (через CLI)
Запускается локально или на сервере из корня проекта.

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `python3 admin_cli.py info <ID>` | Посмотреть полный статус пользователя в БД | `python3 admin_cli.py info 12345` |
| `python3 admin_cli.py delete <ID>` | Полностью удалить пользователя (для сброса триала) | `python3 admin_cli.py delete 12345` |
| `python3 admin_cli.py set-sub <ID> ГГГГ-ММ-ДД` | Изменить дату окончания подписки | `python3 admin_cli.py set-sub 12345 2026-06-01` |

---

## 🚀 2. Управление ботом на сервере (Systemd)
Эти команды выполняются на удаленном сервере под пользователем `root`.

| Действие | Команда |
| :--- | :--- |
| **Перезагрузить бота** | `systemctl restart healvpn` |
| **Остановить бота** | `systemctl stop healvpn` |
| **Запустить бота** | `systemctl start healvpn` |
| **Статус работы** | `systemctl status healvpn` |
| **Посмотреть логи (Live)** | `journalctl -u healvpn -f` |
| **Посмотреть последние 100 строк логов** | `journalctl -u healvpn -n 100` |

---

## 📦 3. Деплой и обновление кода (Git)
Когда ты внес изменения в код (например, через меня) и хочешь применить их на сервере:

1. **На локальном компьютере:**
   ```bash
   git add .
   git commit -m "Описание изменений"
   git push origin main
   ```

2. **На сервере:**
   ```bash
   cd /opt/HealVPN
   git pull origin main
   systemctl restart healvpn
   ```

---

## 🤖 4. Команды внутри Telegram
Команды, которые можно писать самому боту:

- `/start` — Запуск бота, регистрация, переход в главное меню.
- `/status` — Быстрая проверка статуса твоей подписки.

---

## 🧪 5. Разработка и отладка
Если нужно запустить бота вручную (не через службу), чтобы видеть ошибки прямо в консоли:

```bash
cd /opt/HealVPN
source venv/bin/activate
python3 run_bot.py
```

---

## 🏗 6. Первоначальный деплой (с нуля)
Если ты переезжаешь на новый сервер или настраиваешь всё заново.

### 1. Подготовка сервера
```bash
apt update && apt upgrade -y
apt install -y git python3-pip python3-venv
```

### 2. Клонирование проекта
```bash
cd /opt
git clone https://github.com/aleksandrposokhovm/HealVPN.git
cd HealVPN
```

### 3. Настройка окружения
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Создание .env
Скопируй пример или создай файл вручную:
```bash
nano .env
```
*(Вставь туда все ключи из раздела №7)*

### 5. Регистрация службы (Systemd)
Чтобы бот работал 24/7, создай файл `/etc/systemd/system/healvpn.service`:
```ini
[Unit]
Description=HealVPN Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/opt/HealVPN
ExecStart=/opt/HealVPN/venv/bin/python run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Затем примени настройки:
```bash
systemctl daemon-reload
systemctl enable healvpn
systemctl start healvpn
```

---

## 📂 7. Где лежат ключи и настройки?
- **`.env`** — Самый важный файл. Там лежат:
    - `BOT_TOKEN` — Токен твоего бота.
    - `DATABASE_URL` — Ссылка на базу данных (PostgreSQL/Supabase).
    - `MARZBAN_URL / USERNAME / PASSWORD` — Доступы к VPN-панели.
    - `YOOKASSA_SHOP_ID / SECRET_KEY` — Доступы к оплате.

---

## 📈 8. Мониторинг базы данных
Если база данных находится на **Supabase**, ты можешь зайти в их веб-интерфейс:
- [Supabase Dashboard](https://supabase.com/dashboard)
- Там можно вручную редактировать таблицу `users`, если CLI под рукой нет.

---

## 💡 Полезные советы
*   **Узнать свой TG ID:** Напиши боту `@userinfobot`.
*   **Проблема с оплатой:** Проверь логи (`journalctl -u healvpn -f`). Если там ошибка 401/403 от YooKassa — значит, неверный секретный ключ в `.env`.
*   **VPN не работает:** Проверь, запущен ли Marzban на сервере и верны ли данные в `.env`.
