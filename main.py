from asyncio import gather, run

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommandScopeAllPrivateChats
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bingx_command import price_updates_ws
from common.bot_cmd_list import private
from common.config import config
from database.db_utils import init_db
from database.orm_query import load_orders_db
from handlers import router
from middlewares.db import DataBaseSession
from middlewares.http import HttpSession

bot = Bot(token=config.TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def main():
    engine = create_async_engine(config.DB_URL, echo=True)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    dp.update.middleware(DataBaseSession(session_pool=async_session_maker)),

    async with async_session_maker() as session:
        await init_db(engine)
        await load_orders_db(session)

    async with ClientSession(headers=config.HEADERS) as client_session:
        dp.update.middleware(HttpSession(session=client_session)),

        tasks = (
            # manage_listen_key(client_session),
            *(price_updates_ws(symbol, client_session) for symbol in config.SYMBOLS),

            # bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()),
            # bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats()),

            bot.delete_webhook(drop_pending_updates=True),
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        )

        await gather(*tasks)


if __name__ == "__main__":
    run(main())
