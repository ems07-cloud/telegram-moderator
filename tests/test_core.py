from pathlib import Path

import pytest

from moderator.config import load_rules
from moderator.core import FloodTracker, MessageInfo, check_message, check_name
from moderator.normalize import variants

RULES = load_rules(Path(__file__).parent.parent / "rules.example.toml")
NOW = 1_800_000_000.0


def msg(text="", **kw):
    return MessageInfo(user_id=1, full_name="Иван Петров", text=text, date=NOW, **kw)


def verdict(m, flood=None):
    v = check_message(RULES, m, flood)
    return (v.action, v.rule) if v else None


@pytest.mark.parametrize("text, expected", [
    ("Заработок от 5000 в день без вложений, пиши в лс", ("ban", "ban_pattern")),
    ("З@работок 3000 в день", ("ban", "ban_pattern")),                # подмена букв: @ вместо а
    ("Лучшее kазино", ("ban", "ban_pattern")),                       # латинская k в русском слове
    ("Вступай: t.me/+AbCdEf", ("ban", "ban_pattern")),
    ("Продам бесплатные подписчики", ("delete", "hide_pattern")),
    ("Подскажите, как настроить aiogram?", None),
    ("Работаю с ботами, могу помочь", None),
], ids=["earn", "at-sign", "latin-k", "invite", "hide", "normal", "normal-2"])
def test_text_rules(text, expected):
    assert verdict(msg(text)) == expected


def test_caption_is_checked_like_text():
    """В оригинале подписи к фото не проверялись — спам шёл картинкой с текстом."""
    assert verdict(msg("Казино, бонус 500%", attachment="photo")) == ("ban", "ban_pattern")


def test_admin_is_exempt():
    assert verdict(msg("казино", is_admin=True)) is None


def test_forwards_and_attachments():
    assert verdict(msg("Обычный текст", is_forward=True)) == ("delete", "forward")
    assert verdict(msg("", attachment="voice")) == ("delete", "attachment")
    assert verdict(msg("", attachment="photo")) is None


def test_newbie_cannot_post_links_first_day():
    assert verdict(msg("мой канал t.me/mychannel", joined_at=NOW - 3600)) == ("delete", "newbie_link")
    assert verdict(msg("посмотрите example.ru", joined_at=NOW - 3600)) == ("delete", "newbie_link")
    assert verdict(msg("мой канал t.me/mychannel", joined_at=NOW - 3 * 86400)) is None   # старожилу можно
    assert verdict(msg("без ссылок", joined_at=NOW - 60)) is None


def test_name_ban():
    assert check_name(RULES, "Crypto Signals VIP").action == "ban"
    assert check_name(RULES, "Пётр", "zarabotok_bot") is None
    assert check_name(RULES, "Пётр", "") is None


def test_flood_mutes_after_limit():
    flood = FloodTracker()
    results = [verdict(MessageInfo(user_id=7, text=f"сообщение {i}", date=NOW + i), flood) for i in range(6)]
    assert results[:5] == [None] * 5 and results[5] == ("mute", "flood")
    # через окно счётчик сбрасывается
    assert verdict(MessageInfo(user_id=7, text="позже", date=NOW + 60), flood) is None


def test_variants_strip_invisible_and_fold():
    v = variants("К​АЗИНО")             # невидимый пробел нулевой ширины внутри слова
    assert "казино" in v


def test_example_rules_loaded():
    assert RULES.captcha and RULES.captcha_seconds == 120 and RULES.newbie_hours == 24
    assert "voice" not in RULES.allowed_attachments and RULES.notify_chat == 0
