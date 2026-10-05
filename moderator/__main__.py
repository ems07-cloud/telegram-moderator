"""Запуск: BOT_TOKEN=... RULES_PATH=rules.toml python -m moderator"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import config
from .bot import Moderator, build_router
from .journal import Journal


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")
    rules = config.load_rules(config.RULES_PATH)
    mod = Moderator(rules, Journal(config.DB_PATH))
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(mod))
    # нужны и события о новых участниках — указываем типы апдейтов явно
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])


if __name__ == "__main__":
    asyncio.run(main())
