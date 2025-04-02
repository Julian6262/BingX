from asyncio import gather, run
from aiogram import Bot, Dispatcher

from app.bingx_command import price_updates_ws
from app.config import Config
from app.handlers import router

bot = Bot(token=Config.TOKEN)
dp = Dispatcher()
dp.include_router(router)

symbols = ('BTC', 'BNB', 'SOL')


async def main():
    tasks = [
        *[price_updates_ws(symbol) for symbol in symbols],

        bot.delete_webhook(drop_pending_updates=True),
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
    ]

    await gather(*tasks)


if __name__ == "__main__":
    run(main())
