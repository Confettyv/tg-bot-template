"""Сценарии целиком: настоящие объекты telebot на входе, поддельный API записывает ответы бота."""
import itertools
from datetime import datetime
from types import SimpleNamespace as Call

import pytest
from telebot import types

import bot as app

ADMIN, USER = 1, 42
_ids = itertools.count(100)


class FakeApi:
    """Вместо сети — список вызовов с теми же именами, что у telebot.TeleBot."""

    def __init__(self) -> None:
        self.calls: list = []

    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, link_preview_options=None):
        self.calls.append(Call(method="send", chat_id=chat_id, text=text, reply_markup=reply_markup))
        return Call(message_id=next(_ids))

    def edit_message_text(self, text, chat_id, message_id, **kw):
        self.calls.append(Call(method="edit", chat_id=chat_id, text=text))

    def answer_callback_query(self, callback_query_id, text=None, show_alert=None):
        self.calls.append(Call(method="answer", chat_id=None, text=text))


class Harness:
    def __init__(self, tmp_path) -> None:
        app.store = app.Store(str(tmp_path / "t.db"))
        self.api = FakeApi()

    def _user(self, uid):
        return {"id": uid, "is_bot": False, "first_name": "Вася", "username": f"u{uid}"}

    def _msg(self, uid, **content):
        return {"message_id": next(_ids), "date": int(datetime.now().timestamp()),
                "chat": {"id": uid, "type": "private"}, "from": self._user(uid), **content}

    def text(self, uid, text):
        self.api.calls.clear()
        app.on_message(self.api, types.Message.de_json(self._msg(uid, text=text)))
        return self.api.calls

    def press(self, uid, data, card_text="карточка"):
        self.api.calls.clear()
        cb = {"id": str(next(_ids)), "from": self._user(uid), "chat_instance": "1", "data": data,
              "message": self._msg(uid, text=card_text)}
        app.on_callback(self.api, types.CallbackQuery.de_json(cb))
        return self.api.calls


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def buttons_of(call):
    return [b.callback_data for row in call.reply_markup.keyboard for b in row]


def test_item_reaches_admin_and_user_gets_verdict(h):
    h.text(USER, app.BTN_NEW)
    calls = h.text(USER, "Нужен бот для записи")
    card = next(c for c in calls if c.chat_id == ADMIN)
    assert "Нужен бот для записи" in card.text and "i:ok:1" in buttons_of(card)
    calls = h.press(ADMIN, "i:ok:1")
    assert any(c.chat_id == USER and "принята" in c.text for c in calls)


def test_double_press_is_harmless(h):
    h.text(USER, app.BTN_NEW)
    h.text(USER, "заявка")
    h.press(ADMIN, "i:ok:1")
    calls = h.press(ADMIN, "i:no:1")
    assert [c.text for c in calls if c.method == "answer"] == ["Уже обработана"]
    assert not any(c.chat_id == USER for c in calls)


def test_only_admin_can_decide(h):
    h.text(USER, app.BTN_NEW)
    h.text(USER, "заявка")
    calls = h.press(USER, "i:ok:1")
    assert app.store.get(1)["status"] == "new"
    assert [c.method for c in calls] == ["answer"]


def test_menu_works_from_any_step_and_state_survives_restart(h, tmp_path):
    h.text(USER, app.BTN_NEW)
    app.store = app.Store(str(tmp_path / "t.db"))  # перезапуск: шаг диалога из базы
    calls = h.text(USER, "после перезапуска")
    assert any(c.chat_id == ADMIN for c in calls)
    h.text(USER, app.BTN_NEW)
    assert "Выбери действие" in h.text(USER, "/start")[0].text
