"""Сквозной тест через настоящий Dispatcher aiogram: апдейт из «Telegram» проходит фильтры
роутера и доходит до нужного обработчика. Сеть подменена — запросы бота пишутся в список."""
import asyncio
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import BanChatMember, DeleteMessage, GetChatAdministrators, SendMessage
from aiogram.types import Chat, Message, Update

from moderator.bot import Moderator, build_router
from moderator.config import load_rules
from moderator.journal import Journal

GROUP = -100500


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetChatAdministrators):
            return []
        if isinstance(method, SendMessage):
            return Message(message_id=1, date=int(time.time()), chat=Chat(id=method.chat_id, type="supergroup"))
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""


def update(chat_type: str, text: str, uid: int = 5) -> Update:
    return Update.model_validate({
        "update_id": 1,
        "message": {"message_id": 10, "date": int(time.time()), "text": text,
                    "chat": {"id": GROUP if chat_type != "private" else uid, "type": chat_type},
                    "from": {"id": uid, "is_bot": False, "first_name": "Спамер"}},
    })


def run(upd: Update) -> list:
    session = FakeSession()
    bot = Bot("123:TEST", session=session)
    dp = Dispatcher()
    rules = load_rules(Path(__file__).parent.parent / "rules.example.toml")
    dp.include_router(build_router(Moderator(rules, Journal())))
    asyncio.run(dp.feed_update(bot, upd))
    return session.requests


def test_group_spam_goes_through_router_to_ban():
    calls = run(update("supergroup", "Казино, бонус 500%"))
    kinds = [type(c) for c in calls]
    assert DeleteMessage in kinds and BanChatMember in kinds


def test_private_chat_is_ignored():
    assert run(update("private", "Казино, бонус 500%")) == []


def test_join_with_bad_name_is_banned_via_router():
    upd = Update.model_validate({
        "update_id": 2,
        "message": {"message_id": 11, "date": int(time.time()),
                    "chat": {"id": GROUP, "type": "supergroup"},
                    "from": {"id": 7, "is_bot": False, "first_name": "Crypto Signals"},
                    "new_chat_members": [{"id": 7, "is_bot": False, "first_name": "Crypto Signals"}]},
    })
    calls = run(upd)
    assert any(isinstance(c, BanChatMember) and c.user_id == 7 for c in calls)
