"""Заготовка бота под заказ: меню, заявка текстом, карточка админу с кнопками.

Каркас взят из gamepass-bot и shop-bot: pyTelegramBotAPI (~40 МБ, влезает в «Пробный» Amvera),
SQLite для данных и шага диалога (переживают перезапуск), настройки в .env, логика принимает
`api` параметром — тесты подставляют поддельный (tests/test_bot.py). Переименуй ITEM/шаги под задачу.
"""
import html
import json
import logging
import os
import sqlite3
import time

import telebot
from dotenv import load_dotenv
from telebot import apihelper, types

load_dotenv()
log = logging.getLogger("bot")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


BOT_TOKEN = _env("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in _env("ADMIN_ID").replace(" ", "").split(",") if x.lstrip("-").isdigit()]
DB_PATH = _env("DB_PATH", "bot.db")
PROXY = _env("PROXY")

BTN_NEW = "📝 Оставить заявку"
BTN_HELP = "💬 Поддержка"
ASK_TEXT = "ask_text"  # шаги диалога — в таблице states
NO_PREVIEW = types.LinkPreviewOptions(is_disabled=True)


def esc(value: object) -> str:
    return html.escape(str(value))


def user_label(user) -> str:
    return f"@{user.username}" if user.username else esc(user.first_name or user.id)


class Store:
    """Заявки и шаг диалога. Статус меняется только из ожидаемого — двойное нажатие кнопки безопасно."""

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, user_label TEXT,
                text TEXT, status TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS states (user_id INTEGER PRIMARY KEY, state TEXT, data TEXT);
        """)
        self.db.commit()

    def add(self, **fields) -> int:
        fields.setdefault("created", time.time())
        cur = self.db.execute(f"INSERT INTO items ({', '.join(fields)}) VALUES "
                              f"({', '.join('?' for _ in fields)})", tuple(fields.values()))
        self.db.commit()
        return int(cur.lastrowid)

    def get(self, item_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    def move(self, item_id: int, frm: str, to: str) -> bool:
        cur = self.db.execute("UPDATE items SET status = ? WHERE id = ? AND status = ?", (to, item_id, frm))
        self.db.commit()
        return cur.rowcount == 1

    def state(self, user_id: int) -> tuple[str | None, dict]:
        row = self.db.execute("SELECT state, data FROM states WHERE user_id = ?", (user_id,)).fetchone()
        return (row["state"], json.loads(row["data"] or "{}")) if row else (None, {})

    def set_state(self, user_id: int, state: str, **data) -> None:
        self.db.execute("INSERT OR REPLACE INTO states VALUES (?, ?, ?)", (user_id, state, json.dumps(data)))
        self.db.commit()

    def clear_state(self, user_id: int) -> None:
        self.db.execute("DELETE FROM states WHERE user_id = ?", (user_id,))
        self.db.commit()


store: Store  # создаётся в main(), тесты подставляют свой


def menu() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(BTN_NEW, BTN_HELP)
    return kb


def buttons(*rows: list) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for row in rows:
        kb.row(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in row])
    return kb


def say(api, chat_id: int, text: str, markup=None) -> None:
    api.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup, link_preview_options=NO_PREVIEW)


def to_admin(api, text: str, markup=None) -> None:
    for admin in ADMIN_IDS:
        try:
            say(api, admin, text, markup)
        except Exception:  # админ не нажал /start — остальным всё равно шлём
            log.warning("не доставлено админу %s", admin, exc_info=True)


def start(api, m) -> None:
    store.clear_state(m.from_user.id)
    say(api, m.chat.id, "👋 Привет! Выбери действие в меню 👇", menu())


def new_item(api, m) -> None:
    store.set_state(m.from_user.id, ASK_TEXT)
    say(api, m.chat.id, "Опиши заявку одним сообщением 👇", buttons([("✖️ Отмена", "x")]))


def save_item(api, m) -> None:
    uid = m.from_user.id
    item_id = store.add(user_id=uid, user_label=user_label(m.from_user), text=m.text, status="new")
    store.clear_state(uid)
    say(api, m.chat.id, "✅ Заявка отправлена, ответим здесь.", menu())
    to_admin(api, f"🆕 <b>Заявка #{item_id}</b> от {user_label(m.from_user)}\n{esc(m.text)}",
             buttons([("✅ Принять", f"i:ok:{item_id}"), ("❌ Отклонить", f"i:no:{item_id}")]))


def item_action(api, cb) -> None:
    _, verdict, raw = cb.data.split(":")
    item = store.get(int(raw))
    to = "done" if verdict == "ok" else "rejected"
    if item is None or not store.move(item["id"], "new", to):
        return api.answer_callback_query(cb.id, "Уже обработана")
    api.edit_message_text(f"{cb.message.html_text}\n\n<i>{'Принята' if to == 'done' else 'Отклонена'}</i>",
                          cb.message.chat.id, cb.message.message_id, parse_mode="HTML")
    say(api, item["user_id"], f"Заявка #{item['id']}: {'принята ✅' if to == 'done' else 'отклонена ❌'}")
    api.answer_callback_query(cb.id)


MENU = {BTN_NEW: new_item, BTN_HELP: lambda api, m: say(api, m.chat.id, "Напиши вопрос — передам админу.")}


def on_message(api, m) -> None:
    """Команды и кнопки меню работают с любого шага, дальше — текущий шаг диалога."""
    if m.chat.type != "private":
        return
    text = m.text or ""
    if text.split(" ")[0].split("@")[0] == "/start":
        return start(api, m)
    if text in MENU:
        return MENU[text](api, m)
    state, _ = store.state(m.from_user.id)
    if state == ASK_TEXT:
        return save_item(api, m) if m.text else say(api, m.chat.id, "Нужен текст 👇")
    say(api, m.chat.id, "Не понял 🤔 Выбери действие в меню 👇", menu())


def on_callback(api, cb) -> None:
    data = cb.data or ""
    if data == "x":
        store.clear_state(cb.from_user.id)
        api.answer_callback_query(cb.id, "Отменено")
    elif data.startswith("i:") and cb.from_user.id in ADMIN_IDS:
        item_action(api, cb)
    else:
        api.answer_callback_query(cb.id)


def main() -> None:
    global store
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    missing = [n for n, v in (("BOT_TOKEN", BOT_TOKEN), ("ADMIN_ID", ADMIN_IDS)) if not v]
    if missing:
        raise SystemExit(f"Заполни в .env: {', '.join(missing)}")
    if PROXY:
        apihelper.proxy = {"http": PROXY, "https": PROXY}
    store = Store(DB_PATH)
    api = telebot.TeleBot(BOT_TOKEN, threaded=False)
    api.message_handler(func=lambda m: True, content_types=telebot.util.content_type_media)(
        lambda m: on_message(api, m))
    api.callback_query_handler(func=lambda c: True)(lambda c: on_callback(api, c))
    log.info("Run polling for bot @%s", api.get_me().username)
    api.infinity_polling(timeout=30, long_polling_timeout=25)


if __name__ == "__main__":
    main()
