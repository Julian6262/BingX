from asyncio import gather, run
from logging import DEBUG, FileHandler, INFO, ERROR, getLogger, Formatter

from aiogram import Bot, Dispatcher
from aiohttp import ClientSession, TCPConnector, ClientTimeout
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from common.config import config
from database.db_utils import init_db
from database.orm_query import load_from_db
from handlers import router
from indicators.indicator_models import start_indicators
from bingx_api.bingx_command import price_upd_ws, manage_listen_key, account_upd_ws, so_manager, start_trading, \
    config_manager

from middlewares.db import DataBaseSession
from middlewares.http import HttpSession

# Создаем логгер
logger = getLogger('my_app')
logger.setLevel(DEBUG)  # Устанавливаем минимальный уровень логирования

debug_handler = FileHandler('logs/debug.log', encoding="utf-8")
info_handler = FileHandler('logs/info.log', encoding="utf-8")
error_handler = FileHandler('logs/error.log', encoding="utf-8")
formatter = Formatter('%(asctime)s - %(levelname)s - %(message)s')

debug_handler.setLevel(DEBUG)
info_handler.setLevel(INFO)
error_handler.setLevel(ERROR)

debug_handler.setFormatter(formatter)
info_handler.setFormatter(formatter)
error_handler.setFormatter(formatter)

# Добавляем хендлеры к логгеру
logger.addHandler(debug_handler)
logger.addHandler(info_handler)
logger.addHandler(error_handler)

bot = Bot(token=config.TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def main():
    engine = create_async_engine(config.DB_URL, echo=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    connector = TCPConnector(limit=200, keepalive_timeout=30)
    timeout = ClientTimeout(total=60, connect=10, sock_read=30)

    dp.update.middleware(DataBaseSession(session_pool=async_session)),

    async with ClientSession(headers=config.HEADERS, connector=connector, timeout=timeout) as http_session:
        dp.update.middleware(HttpSession(session=http_session)),

        async with async_session() as session:
            await init_db(engine)
            await load_from_db(session, so_manager, config_manager)

        symbols = so_manager.symbols
        tasks = (
            manage_listen_key(http_session),
            account_upd_ws(http_session),
            *(start_indicators(symbol, http_session=http_session) for symbol in symbols),
            *(price_upd_ws(symbol, http_session=http_session, seconds=i) for i, symbol in enumerate(symbols)),
            *(start_trading(symbol, http_session=http_session, async_session=async_session) for symbol in symbols),

            # bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()),
            # bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats()),

            bot.delete_webhook(drop_pending_updates=True),
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        )

        await gather(*tasks)


if __name__ == "__main__":
    run(main())
