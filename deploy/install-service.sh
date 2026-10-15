#!/usr/bin/env bash
# Ставит бота на автозапуск через systemd: работает круглосуточно,
# поднимается после перезагрузки сервера и после сбоев.
# Запускать из папки бота после того, как ./start.sh хотя бы раз отработал:
#   sudo ./deploy/install-service.sh
# Обновление бота: git pull && sudo ./deploy/install-service.sh
set -e
cd "$(dirname "$0")/.."
DIR="$(pwd)"
SERVICE=beauty-bot

if [ "$(id -u)" -ne 0 ]; then
  echo "Нужны права администратора: sudo ./deploy/install-service.sh"; exit 1
fi
if [ ! -f .env ] || [ ! -x .venv/bin/python ]; then
  echo "Сначала запустите ./start.sh — он создаст .env и установит зависимости."; exit 1
fi

# Новые зависимости после обновления (если появились)
.venv/bin/pip install --quiet -r requirements.txt

RUN_USER="${SUDO_USER:-root}"
chown -R "$RUN_USER" "$DIR"

cat > /etc/systemd/system/$SERVICE.service <<UNIT
[Unit]
Description=Beauty Studio Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m bot
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable $SERVICE
systemctl restart $SERVICE   # повторный запуск скрипта = обновление: бот перезапустится с новым кодом
sleep 3
systemctl --no-pager --lines=5 status $SERVICE || true
echo
echo "Готово! Бот работает в фоне и сам запустится после перезагрузки."
echo "  Логи:        journalctl -u $SERVICE -f"
echo "  Перезапуск:  sudo systemctl restart $SERVICE"
echo "  Остановить:  sudo systemctl stop $SERVICE"
