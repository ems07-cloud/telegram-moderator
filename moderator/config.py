"""Правила модерации из TOML-файла (tomllib — в стандартной библиотеке) + токен из окружения."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Rules:
    ban_patterns: list[re.Pattern] = field(default_factory=list)       # сообщение → удалить и забанить
    hide_patterns: list[re.Pattern] = field(default_factory=list)      # сообщение → удалить
    name_ban_patterns: list[re.Pattern] = field(default_factory=list)  # имя или @username → бан
    delete_forwards: bool = True
    allowed_attachments: set[str] = field(default_factory=lambda: {"photo", "video", "animation", "sticker"})
    newbie_hours: int = 24              # столько часов после входа новичку нельзя ссылки
    captcha: bool = True
    captcha_seconds: int = 120
    flood_messages: int = 5             # больше N сообщений за flood_seconds → мут
    flood_seconds: int = 10
    flood_mute_minutes: int = 30
    admins_exempt: bool = True
    notify_chat: int | None = None      # куда слать отчёт о действиях
    chat_ids: set[int] = field(default_factory=set)   # какие чаты модерировать (пусто — все)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def load_rules(path: str | Path) -> Rules:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    f, b = data.get("filters", {}), data.get("behaviour", {})
    rules = Rules(
        ban_patterns=_compile(f.get("ban_patterns", [])),
        hide_patterns=_compile(f.get("hide_patterns", [])),
        name_ban_patterns=_compile(f.get("name_ban_patterns", [])),
    )
    for key in ("delete_forwards", "newbie_hours", "captcha", "captcha_seconds", "flood_messages",
                "flood_seconds", "flood_mute_minutes", "admins_exempt", "notify_chat"):
        if key in b:
            setattr(rules, key, b[key])
    if "allowed_attachments" in b:
        rules.allowed_attachments = set(b["allowed_attachments"])
    rules.chat_ids = set(b.get("chat_ids", []))
    return rules


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
RULES_PATH = os.getenv("RULES_PATH", "rules.toml")
DB_PATH = os.getenv("DB_PATH", "moderator.sqlite")
