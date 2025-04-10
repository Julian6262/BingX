from asyncio import gather, run
from aiogram import Bot, Dispatcher
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bingx_command import price_updates_ws
from common.config import Config
from database.db_utils import init_db
from database.orm_query import load_orders_db
from handlers import router
from middlewares.db import DataBaseSession

bot = Bot(token=Config.TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def main():
    engine = create_async_engine(Config.DB_URL, echo=True)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session_maker() as session:
        await init_db(engine)
        await load_orders_db(session)
        dp.update.middleware(DataBaseSession(session_pool=async_session_maker))

        async with ClientSession() as client_session:  # ClientSession для WebSocket
            tasks = (
                *(price_updates_ws(client_session, symbol) for symbol in Config.SYMBOLS),

                # await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()),
                # await bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats()),

                bot.delete_webhook(drop_pending_updates=True),
                dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            )

            await gather(*tasks)


if __name__ == "__main__":
    run(main())
