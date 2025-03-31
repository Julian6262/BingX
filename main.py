from asyncio import gather, run
from aiogram import Bot, Dispatcher

from app.bingx_command import price_updates, get_symbol_info, price_updates_ws, place_order
from app.config import TOKEN
from app.handlers import router

bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_routers(router)


async def main():
    tasks = [
        bot.delete_webhook(drop_pending_updates=True),
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),

        price_updates("ETH_USDT", 10),
        get_symbol_info("LINK-USDT"),
        price_updates_ws("BNB-USDT"),
        # place_order(config, 'BNB-USDT', 1)
    ]

    await gather(*tasks)


if __name__ == "__main__":
    run(main())
