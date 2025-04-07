from asyncio import gather, run
from aiogram import Bot, Dispatcher

from app.bingx_command import price_updates_ws
from app.config import Config
from app.database.engine import drop_db, create_db
from app.handlers import router

symbols = ('BTC', 'BNB', 'SOL')


async def on_startup():
    run_param = False
    if run_param:
        await drop_db()
    await create_db()


async def on_shutdown():
    print('бот лег')


bot = Bot(token=Config.TOKEN)
dp = Dispatcher()
dp.include_router(router)

dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)


# dp.update.middleware(DataBaseSession(session_pool=session_maker))
# bot.my_admins_list = {int(i) for i in os.getenv('ADMIN').split(' ')}


async def main():
    tasks = [
        *[price_updates_ws(symbol) for symbol in symbols],

        bot.delete_webhook(drop_pending_updates=True),
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
    ]

    await gather(*tasks)


if __name__ == "__main__":
    run(main())
