"""Журнал действий модератора (а не всей переписки, как в оригинале): кто, когда, за что."""
from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    at REAL NOT NULL, chat_id INTEGER, user_id INTEGER, action TEXT, rule TEXT, detail TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS members (chat_id INTEGER, user_id INTEGER, joined_at REAL, PRIMARY KEY (chat_id, user_id));
"""


class Journal:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def log(self, chat_id: int, user_id: int, action: str, rule: str, detail: str = "", text: str = "",
            at: float | None = None) -> None:
        self.db.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (at or time.time(), chat_id, user_id, action, rule, detail, (text or "")[:200]))
        self.db.commit()

    def joined(self, chat_id: int, user_id: int, at: float | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO members VALUES (?, ?, ?)", (chat_id, user_id, at or time.time()))
        self.db.commit()

    def joined_at(self, chat_id: int, user_id: int) -> float | None:
        row = self.db.execute("SELECT joined_at FROM members WHERE chat_id = ? AND user_id = ?",
                              (chat_id, user_id)).fetchone()
        return row[0] if row else None

    def stats(self, chat_id: int, hours: int = 24, now: float | None = None) -> dict[str, int]:
        since = (now or time.time()) - hours * 3600
        rows = self.db.execute("SELECT rule, COUNT(*) FROM actions WHERE chat_id = ? AND at >= ? GROUP BY rule "
                               "ORDER BY COUNT(*) DESC", (chat_id, since))
        return dict(rows.fetchall())
