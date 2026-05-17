#!/bin/bash

# Скрипт автоматического деплоя HealVPN
# Запускается локально с вашего Mac

SERVER_IP="144.31.245.51"
PROJECT_DIR="/opt/HealVPN"
SERVICE_NAME="healvpn"

echo "=========================================="
echo " 🚀 Запуск автоматического деплоя HealVPN "
echo "=========================================="

# 1. Отправка последних локальных изменений на GitHub
echo "👉 Шаг 1: Пушим изменения на GitHub..."
git push origin main

# 2. Обновление кода на сервере и перезапуск сервиса
echo "👉 Шаг 2: Подключаемся к серверу $SERVER_IP..."
ssh -i ~/.ssh/id_ed25519 root@$SERVER_IP "
  echo '✔️ Успешно подключились!' && \
  cd $PROJECT_DIR && \
  echo '👉 Шаг 3: Скачиваем последние обновления с GitHub на сервер...' && \
  git pull origin main && \
  echo '👉 Шаг 4: Перезапускаем Telegram-бота...' && \
  systemctl restart $SERVICE_NAME && \
  echo '👉 Шаг 5: Проверяем статус сервиса...' && \
  systemctl status $SERVICE_NAME --no-pager -n 5
"

echo "=========================================="
echo " 🎉 Деплой успешно завершен! Бот обновлен. "
echo "=========================================="
