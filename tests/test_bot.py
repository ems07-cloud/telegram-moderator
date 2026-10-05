"""Обработчики бота с подменённым Telegram: что удалено, кто забанен, что ушло в отчёт."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from moderator.bot import FREE, MUTED, Captcha, Moderator
from moderator.config import load_rules
from moderator.journal import Journal

CHAT, REPORTS = -100, -200


class FakeBot:
    def __init__(self, admins=()):
        self.calls, self.admins, self.next_id = [], set(admins), 1000

    async def get_chat_administrators(self, chat_id):
        self.calls.append(("admins", chat_id))
        return [SimpleNamespace(user=SimpleNamespace(id=a)) for a in self.admins]

    async def delete_message(self, chat_id, message_id):
        self.calls.append(("delete", message_id))

    async def ban_chat_member(self, chat_id, user_id):
        self.calls.append(("ban", user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=False):
        self.calls.append(("unban", user_id))

    async def restrict_chat_member(self, chat_id, user_id, permissions, until_date=None):
        self.calls.append(("restrict", user_id, "muted" if permissions == MUTED else "free"))

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send", chat_id, text))


def user(uid, name="Иван Петров", username=None):
    return SimpleNamespace(id=uid, full_name=name, username=username, is_bot=False)


def message(bot, frm, text=None, mid=1, **kw):
    sent = []

    async def answer(text, reply_markup=None, **kw2):
        bot.next_id += 1
        sent.append((text, reply_markup))
        return SimpleNamespace(message_id=bot.next_id)

    base = dict(chat=SimpleNamespace(id=CHAT), from_user=frm, bot=bot, message_id=mid, text=text, caption=None,
                forward_origin=None, date=datetime.now(timezone.utc), new_chat_members=None, answer=answer,
                sent=sent)
    for a in ("photo", "video", "animation", "sticker", "document", "voice", "audio", "video_note", "game", "poll"):
        base[a] = None
    base.update(kw)
    return SimpleNamespace(**base)


def moderator(**overrides):
    rules = load_rules(Path(__file__).parent.parent / "rules.example.toml")
    rules.notify_chat = REPORTS
    for k, v in overrides.items():
        setattr(rules, k, v)
    return Moderator(rules, Journal())


def test_spam_is_deleted_author_banned_and_reported():
    mod, bot = moderator(), FakeBot()
    asyncio.run(mod.on_message(message(bot, user(5, username="spammer"), "Заработок 5000 в день, пиши в лс", mid=42)))
    assert ("delete", 42) in bot.calls and ("ban", 5) in bot.calls
    report = next(c for c in bot.calls if c[0] == "send")[2]
    assert report.startswith("🚫 Бан · шаблон бана")
    assert "Иван Петров (@spammer), id 5" in report and "b'" not in report   # в оригинале тут были байты
    assert mod.journal.stats(CHAT) == {"ban_pattern": 1}


def test_admin_list_is_cached():
    mod, bot = moderator(), FakeBot(admins={1})
    for i in range(3):
        asyncio.run(mod.on_message(message(bot, user(1), "казино", mid=i)))
    assert [c for c in bot.calls if c[0] == "admins"] == [("admins", CHAT)]     # один запрос на три сообщения
    assert not any(c[0] in ("delete", "ban") for c in bot.calls)


def test_flood_gets_mute():
    mod, bot = moderator(), FakeBot()
    for i in range(6):
        asyncio.run(mod.on_message(message(bot, user(9), f"привет {i}", mid=i)))
    assert ("restrict", 9, "muted") in bot.calls


def test_bad_name_banned_right_at_join():
    mod, bot = moderator(), FakeBot()
    join = message(bot, user(1), mid=77, new_chat_members=[user(5, "Crypto Signals VIP")])
    asyncio.run(mod.on_join(join))
    assert ("ban", 5) in bot.calls and ("delete", 77) in bot.calls


def test_captcha_passed():
    mod, bot = moderator(captcha_seconds=0.2), FakeBot()

    async def scenario():
        join = message(bot, user(1), new_chat_members=[user(6, "Анна")])
        await mod.on_join(join)
        assert ("restrict", 6, "muted") in bot.calls
        text, markup = join.sent[0]
        assert "Нажмите кнопку" in text
        assert markup.inline_keyboard[0][0].callback_data == Captcha(user_id=6).pack()

        answers = []

        async def cb_answer(text=None, show_alert=False):
            answers.append(text)
        stranger = SimpleNamespace(from_user=user(7), message=SimpleNamespace(chat=SimpleNamespace(id=CHAT)),
                                   bot=bot, answer=cb_answer)
        await mod.on_captcha(stranger, Captcha(user_id=6))           # чужой нажал — не считается
        owner = SimpleNamespace(from_user=user(6), message=SimpleNamespace(chat=SimpleNamespace(id=CHAT)),
                                bot=bot, answer=cb_answer)
        await mod.on_captcha(owner, Captcha(user_id=6))
        await asyncio.sleep(0.3)                                      # таймер вышел, но капча уже пройдена
        return answers

    answers = asyncio.run(scenario())
    assert answers == ["Эта кнопка не для вас 🙂", "Спасибо! Можно писать 👋"]
    assert ("restrict", 6, "free") in bot.calls
    assert ("ban", 6) not in bot.calls


def test_captcha_timeout_kicks_but_allows_return():
    mod, bot = moderator(captcha_seconds=0.1), FakeBot()

    async def scenario():
        await mod.on_join(message(bot, user(1), new_chat_members=[user(8, "Бот-спамер")]))
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    assert ("ban", 8) in bot.calls and ("unban", 8) in bot.calls
    assert mod.journal.stats(CHAT) == {"captcha": 1}


def test_unwatched_chat_is_ignored():
    mod, bot = moderator(chat_ids={-999}), FakeBot()
    asyncio.run(mod.on_message(message(bot, user(5), "казино")))
    assert bot.calls == []


def test_stats_for_admin_only():
    mod, bot = moderator(), FakeBot(admins={1})
    mod.journal.log(CHAT, 5, "ban", "ban_pattern")
    mod.journal.log(CHAT, 6, "delete", "forward")
    mod.journal.log(CHAT, 7, "delete", "forward")
    m_user = message(bot, user(2), "/modstats")
    asyncio.run(mod.on_stats(m_user))
    assert m_user.sent == []
    m_admin = message(bot, user(1), "/modstats")
    asyncio.run(mod.on_stats(m_admin))
    assert "пересланное сообщение: 2" in m_admin.sent[0][0] and "шаблон бана: 1" in m_admin.sent[0][0]
