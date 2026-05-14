# Полное руководство по деплою HealVPN бота (с нуля)

Данное руководство описывает процесс развертывания бота на чистом сервере под управлением **Ubuntu 22.04 / 24.04**. Мы установим все необходимые зависимости, настроим базу данных PostgreSQL и обернем бота в системный сервис (systemd), чтобы он работал 24/7 и автоматически перезапускался при сбоях или перезагрузке сервера.

---

## Шаг 1. Подготовка сервера

Подключитесь к вашему серверу по SSH:
```bash
ssh root@IP_ВАШЕГО_СЕРВЕРА
```

Обновите систему и установите базовые утилиты:
```bash
apt update && apt upgrade -y
apt install -y git curl wget nano htop
```

## Шаг 2. Установка и настройка PostgreSQL

Поскольку бот теперь использует реляционную базу данных PostgreSQL, ее необходимо установить.

1. **Установите PostgreSQL:**
```bash
apt install -y postgresql postgresql-contrib
```

2. **Зайдите в консоль PostgreSQL:**
```bash
sudo -u postgres psql
```

3. **Создайте базу данных и пользователя:**
Выполните следующие команды в открывшейся консоли PostgreSQL. Обязательно замените `your_strong_password` на надежный пароль.
```sql
CREATE DATABASE healvpn_db;
CREATE USER healvpn_user WITH PASSWORD 'your_strong_password';
ALTER ROLE healvpn_user SET client_encoding TO 'utf8';
ALTER ROLE healvpn_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE healvpn_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE healvpn_db TO healvpn_user;
-- Для PostgreSQL 15+ также нужно выдать права на public схему:
\c healvpn_db
GRANT ALL ON SCHEMA public TO healvpn_user;
\q
```

## Шаг 3. Установка Python и настройка окружения

Бот написан на Python, поэтому нам нужен Python версии 3.10 или выше и инструмент для создания виртуальных окружений.

```bash
apt install -y python3 python3-pip python3-venv
```

Создадим директорию для бота (например, в `/opt`) и клонируем/скопируем туда код:
```bash
mkdir -p /opt/healvpn
cd /opt/healvpn
```
> [!NOTE]
> Загрузите файлы вашего проекта в папку `/opt/healvpn` (например, через git clone, SFTP или SCP). 
> *Пример с git:* `git clone https://github.com/ВАШ/РЕПОЗИТОРИЙ.git .`

Создайте виртуальное окружение:
```bash
python3 -m venv venv
```

Активируйте его и установите зависимости:
```bash
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Шаг 4. Настройка конфигурации (.env)

Находясь в директории бота (`/opt/healvpn`), создайте или отредактируйте файл `.env`:
```bash
nano .env
```

Заполните его вашими данными. Обратите внимание на `DATABASE_URL` — вставьте туда данные, которые вы создали на Шаге 2.

```env
BOT_TOKEN=123456789:YOUR_TELEGRAM_BOT_TOKEN
YOOKASSA_SHOP_ID=ВАШ_SHOP_ID
YOOKASSA_SECRET_KEY=ВАШ_СЕКРЕТНЫЙ_КЛЮЧ

VPN_SERVER_IP=111.222.333.444
VPN_API_URL=https://your-marzban-domain.com

MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=super_secret_marzban_password

# Формат: postgresql+asyncpg://пользователь:пароль@localhost/имя_базы
DATABASE_URL=postgresql+asyncpg://healvpn_user:your_strong_password@localhost/healvpn_db
```
Сохраните (`Ctrl+O`, `Enter`) и закройте (`Ctrl+X`).

## Шаг 5. Тестовый запуск бота

Убедитесь, что вы находитесь в виртуальном окружении (в начале строки консоли должно быть написано `(venv)`). Запустите бота:
```bash
python run_bot.py
```
> [!TIP]
> При первом запуске SQLAlchemy автоматически подключится к PostgreSQL и создаст все необходимые таблицы.

Убедитесь, что в консоли нет ошибок и бот отвечает в Telegram. Остановите бота комбинацией `Ctrl+C`.

## Шаг 6. Настройка systemd (Автозапуск 24/7)

Чтобы бот работал в фоновом режиме, запускался при старте системы и перезапускался при ошибках, мы создадим systemd сервис.

1. Создайте файл сервиса:
```bash
nano /etc/systemd/system/healvpn.service
```

2. Вставьте в него следующую конфигурацию:
```ini
[Unit]
Description=HealVPN Telegram Bot
After=network.target postgresql.service

[Service]
User=root
Group=root
WorkingDirectory=/opt/healvpn
Environment="PATH=/opt/healvpn/venv/bin"
ExecStart=/opt/healvpn/venv/bin/python run_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
*(Если вы положили бота не в `/opt/healvpn`, измените пути в `WorkingDirectory`, `Environment` и `ExecStart`)*.

3. Сохраните и закройте файл.

4. Перезагрузите конфигурацию systemd и запустите сервис:
```bash
systemctl daemon-reload
systemctl enable healvpn
systemctl start healvpn
```

## Шаг 7. Управление и Мониторинг

Ваш бот теперь работает! Вот полезные команды для управления:

**Проверить статус бота:**
```bash
systemctl status healvpn
```

**Посмотреть логи (в реальном времени):**
```bash
journalctl -u healvpn -f
```

**Остановить бота:**
```bash
systemctl stop healvpn
```

**Перезапустить бота (после обновления кода):**
```bash
systemctl restart healvpn
```

---

> [!SUCCESS]
> **Готово!** Бот полностью развернут, подключен к боевой базе данных PostgreSQL и работает как надежный системный демон.
