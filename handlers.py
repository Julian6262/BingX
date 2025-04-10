from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, orders_book
from common.config import Config
from database.orm_query import add_order, get_last_order, del_last_order
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(Config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом

QUANTITY = 1


@router.message(F.text.startswith('1_'))  # Вводим например: 1_btc, 1_Bnb
async def get_price_cmd(message: Message):
    symbol = message.text[2:].upper()
    price = await ws_price.get_price(symbol)
    await message.answer(f'Символ {symbol}, цена {price}' if price else 'Цена не готова/не тот символ')


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession):
    symbol = message.text[2:].upper()
    price = await ws_price.get_price(symbol)  # Дополнительно проверяет на правильный символ

    if price:
        # --- Отправить ордер на покупку по цене в $
        response = await place_order(symbol, 'BUY', quantity=QUANTITY)
        order_data = response.get("data")  # Если в ответе есть 'data', То добавить в БД
        await message.answer(str(response))
        # ------------------------------

        order_data = {
            'data': {'symbol': f"{symbol}-USDT", 'orderId': '1907544211566002176', 'price': price,
                     'executedQty': 1 / price}
        }

        if order_data:
            await add_order(session, order_data['data'])
            await orders_book.update_orders(symbol, order_data['data']['price'],
                                            order_data['data']['executedQty'])  # Добавить в память
            await message.answer('символ добавлен')
        else:
            await message.answer('Покупка не прошла')
    else:
        await message.answer('Цена не готова/не тот символ')


@router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
async def sell_order_cmd(message: Message, session: AsyncSession):
    symbol = message.text[2:].upper()
    price = await ws_price.get_price(symbol)  # Дополнительно проверяет на правильный символ

    if price:
        last_order_data = await get_last_order(session, symbol)

        if last_order_data:
            executed_qty, last_id = last_order_data['executed_qty'], last_order_data['id']

            # --- Отправить ордер на продажу по цене покупки монеты, напр 0.000011 BTC
            # response = await place_order(symbol, 'SELL', executed_qty=executed_qty)
            # order_data = response.get("data")
            order_data = True
            # await message.answer(str(response))
            # ------------------------------

            if order_data:
                await del_last_order(session, last_id)  # Удалить из базы
                await orders_book.delete_last_order(symbol)  # Удалить из памяти
                await message.answer('символ удален')
            else:
                await message.answer('Продажа не прошла')
        else:
            await message.answer('Символы кончились')
    else:
        await message.answer('Цена не готова/не тот символ')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession):
    btc_orders = await orders_book.get_orders("BTC")
    print(btc_orders)
    btc_orders = await orders_book.get_orders("BNB")
    print(btc_orders)
    btc_orders = await orders_book.get_orders("SOL")
    print(btc_orders)
    #
    # last_btc_order = await orders_book.get_last_order("BTC")
    #
    # total_btc_cost = await orders_book.get_total_cost("BTC")  # 34
    #
    # deleted_order = await orders_book.delete_last_order("BTC")
    # btc_orders_after_delete = await orders_book.get_orders("BTC")
    #
    # print(btc_orders)
    # print(last_btc_order)
    # print(total_btc_cost)
    # print(deleted_order)
    # print(btc_orders_after_delete)
