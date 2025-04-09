from asyncio import gather, run
from aiogram import Bot, Dispatcher

from bingx_command import price_updates_ws
from common.config import Config
from database.engine import drop_db, create_db, session_maker
from handlers import router
from middlewares.db import DataBaseSession


async def on_startup():
    # run_param = False
    run_param = True
    await (create_db() if run_param else drop_db())
    # await bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats()),
    # await bot.set_my_commands(commands=private, scope=BotCommandScopeAllPrivateChats()),


async def on_shutdown():
    print('бот лег')


bot = Bot(token=Config.TOKEN)
dp = Dispatcher()
dp.include_router(router)

dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)
dp.update.middleware(DataBaseSession(session_pool=session_maker))  # Проброс сессии sqlalchemy в хэндлеры


async def main():
    tasks = [
        *[price_updates_ws(symbol) for symbol in Config.SYMBOLS],

        bot.delete_webhook(drop_pending_updates=True),
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
    ]

    await gather(*tasks)


if __name__ == "__main__":
    run(main())
