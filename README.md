# Заготовка Telegram-бота

Каркас небольшого бота: один `bot.py`, pyTelegramBotAPI (~40 МБ в памяти, влезает в бесплатные
тарифы хостингов), SQLite для данных и шага диалога, настройки в `.env`, сценарии покрыты тестами
с поддельным Telegram, без сети.

Новый проект: скопировать папку, переименовать `items` и шаги под задачу, дописать сценарии
в `tests/test_bot.py` (сначала тест из ТЗ, потом код).

    python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest ruff
    .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check .
    cp .env.example .env   # BOT_TOKEN, ADMIN_ID
    .venv/bin/python bot.py

Amvera: `amvera.yml` уже есть, в переменных `DB_PATH=/data/bot.db`.

Лицензия MIT.
