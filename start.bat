@echo off
chcp 65001 >nul
rem Запуск бота бьюти-студии на Windows. Первый раз спросит токен бота, ваш Telegram ID и платёжный токен.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 goto nopython

if exist .env goto venv

echo Нужен токен бота от @BotFather (вида 123456:AA...)
set /p token="Вставьте токен и нажмите Enter: "
if "%token%"=="" goto notoken

echo Ваш Telegram ID - чтобы получать уведомления и открывать /admin (узнать: @userinfobot)
set /p admin_id="Вставьте ID и нажмите Enter: "

echo Платёжный токен ЮKassa (тест). Можно оставить пустым - тогда оплата будет демо-кнопкой
set "pay_token="
set /p pay_token="Вставьте токен или нажмите Enter, чтобы пропустить: "

> .env echo BOT_TOKEN=%token%
>> .env echo ADMIN_ID=%admin_id%
>> .env echo PAYMENT_TOKEN=%pay_token%
>> .env echo TIMEZONE=Europe/Moscow
echo Настройки сохранены в .env

:venv
if exist .venv goto run
echo Готовлю окружение, это займёт минуту...
python -m venv .venv
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet -r requirements.txt
if errorlevel 1 goto pipfail

:run
echo Запускаю бота... Когда появится строка "Бот @... запущен", напишите ему /start в Telegram. Остановить - Ctrl+C.
.venv\Scripts\python -m bot
pause
exit /b

:nopython
echo Не найден Python. Установите Python 3.10+ с https://www.python.org/downloads/
echo При установке отметьте галочку "Add python.exe to PATH", затем запустите start.bat снова.
pause
exit /b 1

:notoken
echo Токен не введён - выходим.
pause
exit /b 1

:pipfail
echo Не удалось установить зависимости. Проверьте интернет и запустите start.bat снова.
rmdir /s /q .venv
pause
exit /b 1
