"""Решение «что делать с сообщением» — без Telegram, чистые функции и маленький счётчик флуда."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .config import Rules
from .normalize import variants

LINK = re.compile(r"(https?://|www\.|t\.me/|@[a-z0-9_]{5,}|\b[a-z0-9-]+\.(ru|com|net|org|io|me|shop|xyz|top)\b)",
                  re.IGNORECASE)


@dataclass
class MessageInfo:
    user_id: int
    full_name: str = ""
    username: str = ""
    text: str = ""                 # текст или подпись к фото/видео
    is_admin: bool = False
    is_forward: bool = False
    attachment: str | None = None  # photo, video, document, voice, audio, sticker, animation...
    joined_at: float | None = None  # когда вошёл в чат (если знаем)
    date: float = field(default_factory=time.time)


@dataclass
class Verdict:
    action: str        # ban | delete | mute
    rule: str          # какое правило сработало — для журнала и отчёта
    detail: str = ""


def _match(patterns: list[re.Pattern], text: str) -> re.Pattern | None:
    for v in variants(text):
        for p in patterns:
            if p.search(v):
                return p
    return None


def check_name(rules: Rules, full_name: str, username: str = "") -> Verdict | None:
    for value in (full_name, username):
        p = _match(rules.name_ban_patterns, value or "")
        if p:
            return Verdict("ban", "name", f"имя «{value}» ~ {p.pattern}")
    return None


class FloodTracker:
    """Скользящее окно: сколько сообщений пользователь отправил за последние N секунд."""

    def __init__(self):
        self.times: dict[tuple[int, int], deque] = defaultdict(deque)

    def hit(self, chat_id: int, user_id: int, now: float, window: int) -> int:
        q = self.times[(chat_id, user_id)]
        q.append(now)
        while q and q[0] < now - window:
            q.popleft()
        return len(q)


def check_message(rules: Rules, msg: MessageInfo, flood: FloodTracker | None = None, chat_id: int = 0) -> Verdict | None:
    """Порядок важен: сначала самое тяжёлое (бан), потом удаление, потом флуд."""
    if msg.is_admin and rules.admins_exempt:
        return None
    name = check_name(rules, msg.full_name, msg.username)
    if name:
        return name
    p = _match(rules.ban_patterns, msg.text)
    if p:
        return Verdict("ban", "ban_pattern", p.pattern)
    if msg.is_forward and rules.delete_forwards:
        return Verdict("delete", "forward")
    if msg.attachment and msg.attachment not in rules.allowed_attachments:
        return Verdict("delete", "attachment", msg.attachment)
    if (rules.newbie_hours and msg.joined_at is not None
            and msg.date - msg.joined_at < rules.newbie_hours * 3600 and LINK.search(msg.text or "")):
        return Verdict("delete", "newbie_link", f"ссылка в первые {rules.newbie_hours} ч")
    p = _match(rules.hide_patterns, msg.text)
    if p:
        return Verdict("delete", "hide_pattern", p.pattern)
    if flood and rules.flood_messages:
        count = flood.hit(chat_id, msg.user_id, msg.date, rules.flood_seconds)
        if count > rules.flood_messages:
            return Verdict("mute", "flood", f"{count} сообщений за {rules.flood_seconds} с")
    return None
