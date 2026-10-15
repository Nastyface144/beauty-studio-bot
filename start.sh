#!/usr/bin/env bash
# Запуск бота бьюти-студии на своём компьютере или VPS.
# Первый раз спросит токен бота, ваш Telegram ID и (по желанию) платёжный токен, сохранит их в .env.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Нужен токен бота от @BotFather (вида 123456:AA...)"
  read -r -p "Вставьте токен и нажмите Enter: " token
  [ -n "$token" ] || { echo "Токен не введён — выходим."; exit 1; }

  echo "Ваш Telegram ID — чтобы получать уведомления и открывать /admin (узнать: @userinfobot)"
  read -r -p "Вставьте ID и нажмите Enter: " admin_id

  echo "Платёжный токен ЮKassa (тест). Можно оставить пустым — тогда оплата будет демо-кнопкой"
  read -r -p "Вставьте токен или нажмите Enter, чтобы пропустить: " pay_token

  printf 'BOT_TOKEN=%s\nADMIN_ID=%s\nPAYMENT_TOKEN=%s\nTIMEZONE=Europe/Moscow\n' \
    "$token" "$admin_id" "$pay_token" > .env
  echo "Настройки сохранены в .env (этот файл не попадёт в git). Остальные параметры — в .env.example."
fi

if [ ! -d .venv ]; then
  echo "Готовлю окружение…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

echo "Бот запущен. Напишите ему /start в Telegram. Остановить — Ctrl+C."
exec .venv/bin/python -m bot
