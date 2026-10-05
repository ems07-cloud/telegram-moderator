"""Telegram-часть (aiogram 3): применяем решения core к группе, капча для новичков, отчёты."""
from __future__ import annotations

import asyncio
import html
import logging
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, ChatPermissions, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Rules
from .core import FloodTracker, MessageInfo, Verdict, check_message, check_name
from .journal import Journal

log = logging.getLogger(__name__)
ATTACHMENTS = ("photo", "video", "animation", "sticker", "document", "voice", "audio", "video_note", "game", "poll")
MUTED = ChatPermissions(can_send_messages=False)
FREE = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True,
                       can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                       can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                       can_add_web_page_previews=True)
ACTION_TITLE = {"ban": "🚫 Бан", "delete": "🗑 Удалено", "mute": "🔇 Мут"}
RULE_TITLE = {"name": "имя/ник по шаблону", "ban_pattern": "шаблон бана", "forward": "пересланное сообщение",
              "attachment": "запрещённое вложение", "newbie_link": "ссылка от новичка",
              "hide_pattern": "шаблон скрытия", "flood": "флуд", "captcha": "не прошёл капчу"}


class Captcha(CallbackData, prefix="cap"):
    user_id: int


class Moderator:
    def __init__(self, rules: Rules, journal: Journal, admin_ttl: int = 300):
        self.rules, self.journal = rules, journal
        self.flood = FloodTracker()
        self.admins: dict[int, tuple[float, set[int]]] = {}
        self.admin_ttl = admin_ttl
        self.pending: dict[tuple[int, int], int] = {}      # (чат, пользователь) → id сообщения капчи
        self.tasks: set[asyncio.Task] = set()

    # ---------- вспомогательное ----------

    def watched(self, chat_id: int) -> bool:
        return not self.rules.chat_ids or chat_id in self.rules.chat_ids

    async def is_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Список админов кешируем на 5 минут — не дёргаем Telegram на каждое сообщение."""
        cached = self.admins.get(chat_id)
        if cached is None or cached[0] < time.time():
            members = await bot.get_chat_administrators(chat_id)
            cached = (time.time() + self.admin_ttl, {m.user.id for m in members})
            self.admins[chat_id] = cached
        return user_id in cached[1]

    async def report(self, bot: Bot, chat_id: int, user, verdict: Verdict, text: str = "") -> None:
        self.journal.log(chat_id, user.id, verdict.action, verdict.rule, verdict.detail, text)
        if not self.rules.notify_chat:
            return
        who = html.escape(user.full_name) + (f" (@{html.escape(user.username)})" if user.username else "")
        lines = [f"{ACTION_TITLE[verdict.action]} · {RULE_TITLE.get(verdict.rule, verdict.rule)}",
                 f"👤 {who}, id {user.id}"]
        if verdict.detail:
            lines.append(f"🔎 {html.escape(verdict.detail)}")
        if text:
            lines.append(f"💬 {html.escape(text[:300])}")
        try:
            await bot.send_message(self.rules.notify_chat, "\n".join(lines), disable_web_page_preview=True)
        except Exception as exc:
            log.warning("не удалось отправить отчёт: %s", exc)

    async def apply(self, bot: Bot, chat_id: int, user_id: int, message_id: int | None, verdict: Verdict) -> None:
        if message_id is not None:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception as exc:          # уже удалено или нет прав — дальше всё равно действуем
                log.warning("не удалось удалить %s: %s", message_id, exc)
        if verdict.action == "ban":
            await bot.ban_chat_member(chat_id, user_id)
        elif verdict.action == "mute":
            await bot.restrict_chat_member(chat_id, user_id, MUTED,
                                           until_date=int(time.time()) + self.rules.flood_mute_minutes * 60)

    # ---------- события ----------

    async def on_join(self, message: Message) -> None:
        chat_id, bot = message.chat.id, message.bot
        if not self.watched(chat_id):
            return
        for user in message.new_chat_members:
            if user.is_bot:
                continue
            self.journal.joined(chat_id, user.id)
            verdict = check_name(self.rules, user.full_name, user.username or "")
            if verdict:                                   # оригинал ждал, пока спамер что-то напишет
                await self.apply(bot, chat_id, user.id, message.message_id, verdict)
                await self.report(bot, chat_id, user, verdict)
                continue
            if self.rules.captcha:
                await bot.restrict_chat_member(chat_id, user.id, MUTED)
                kb = InlineKeyboardBuilder()
                kb.button(text="✅ Я человек", callback_data=Captcha(user_id=user.id))
                sent = await message.answer(
                    f"{html.escape(user.full_name)}, добро пожаловать! Нажмите кнопку в течение "
                    f"{self.rules.captcha_seconds} секунд, чтобы писать в чат.", reply_markup=kb.as_markup())
                self.pending[(chat_id, user.id)] = sent.message_id
                task = asyncio.create_task(self.captcha_timeout(bot, chat_id, user))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

    async def captcha_timeout(self, bot: Bot, chat_id: int, user) -> None:
        await asyncio.sleep(self.rules.captcha_seconds)
        msg_id = self.pending.pop((chat_id, user.id), None)
        if msg_id is None:
            return                                         # успел нажать
        verdict = Verdict("ban", "captcha", f"не нажал кнопку за {self.rules.captcha_seconds} с")
        await self.apply(bot, chat_id, user.id, msg_id, verdict)
        await bot.unban_chat_member(chat_id, user.id, only_if_banned=True)   # выгнали, но вернуться можно
        await self.report(bot, chat_id, user, verdict)

    async def on_captcha(self, cb: CallbackQuery, callback_data: Captcha) -> None:
        if cb.from_user.id != callback_data.user_id:
            await cb.answer("Эта кнопка не для вас 🙂", show_alert=True)
            return
        chat_id = cb.message.chat.id
        msg_id = self.pending.pop((chat_id, cb.from_user.id), None)
        await cb.bot.restrict_chat_member(chat_id, cb.from_user.id, FREE)
        if msg_id:
            try:
                await cb.bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
        await cb.answer("Спасибо! Можно писать 👋")

    async def on_message(self, message: Message) -> None:
        chat_id, user, bot = message.chat.id, message.from_user, message.bot
        if not self.watched(chat_id) or user is None or user.is_bot:
            return
        info = MessageInfo(
            user_id=user.id, full_name=user.full_name, username=user.username or "",
            text=message.text or message.caption or "",           # подписи к фото проверяем тоже
            is_admin=await self.is_admin(bot, chat_id, user.id),
            is_forward=message.forward_origin is not None,
            attachment=next((a for a in ATTACHMENTS if getattr(message, a, None)), None),
            joined_at=self.journal.joined_at(chat_id, user.id),
            date=message.date.timestamp(),
        )
        verdict = check_message(self.rules, info, self.flood, chat_id)
        if verdict:
            await self.apply(bot, chat_id, user.id, message.message_id, verdict)
            await self.report(bot, chat_id, user, verdict, info.text)

    async def on_stats(self, message: Message) -> None:
        if not await self.is_admin(message.bot, message.chat.id, message.from_user.id):
            return
        stats = self.journal.stats(message.chat.id)
        if not stats:
            await message.answer("За сутки нарушений не было 🎉")
            return
        lines = ["<b>Модерация за 24 часа</b>", ""]
        lines += [f"• {RULE_TITLE.get(rule, rule)}: {n}" for rule, n in stats.items()]
        await message.answer("\n".join(lines))


def build_router(mod: Moderator) -> Router:
    router = Router()
    groups = F.chat.type.in_({"group", "supergroup"})
    router.message.register(mod.on_stats, Command("modstats"), groups)
    router.message.register(mod.on_join, F.new_chat_members, groups)
    router.callback_query.register(mod.on_captcha, Captcha.filter())
    router.message.register(mod.on_message, groups)
    return router
