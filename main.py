from asyncio import gather, run
from aiogram import Bot, Dispatcher
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bingx_command import price_updates_ws, manage_listen_key, account_updates_ws
from common.config import config
from database.db_utils import init_db
from database.orm_query import load_from_db, save_simbols_to_db
from handlers import router
from middlewares.db import DataBaseSession
from middlewares.http import HttpSession

from aiogram.types import BotCommandScopeAllPrivateChats
from common.bot_cmd_list import private

bot = Bot(token=config.TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def main():
    engine = create_async_engine(config.DB_URL, echo=True)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    dp.update.middleware(DataBaseSession(session_pool=async_session_maker)),

    async with ClientSession(headers=config.HEADERS) as client_session:
        dp.update.middleware(HttpSession(session=client_session)),

        async with async_session_maker() as session:
            await init_db(engine)
            await save_simbols_to_db(config.SYMBOLS, session, client_session)
            await load_from_db(session)

        tasks = (
            manage_listen_key(client_session),
            account_updates_ws(client_session),
            *(price_updates_ws(i, symbol, client_session) for i, symbol in enumerate(config.SYMBOLS)),

            # bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()),
            # bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats()),

            bot.delete_webhook(drop_pending_updates=True),
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        )

        await gather(*tasks)


if __name__ == "__main__":
    run(main())
