from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, orders_book, account_info, get_account_balances
from common.config import config
from database.orm_query import add_order, get_last_order, del_last_order
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом

QUANTITY = 1  # Минимальная 2 USD
TAKER = 0.5
MAKER = 0.5


@router.message(F.text.startswith('1_'))  # Вводим например: 1_btc, 1_Bnb
async def get_price_cmd(message: Message):
    symbol = message.text[2:].upper()

    price = await ws_price.get_price(symbol)

    listen_key = await account_info.get_listen_key()
    print(listen_key)

    await message.answer(f'Символ {symbol}, цена {price}' if price else 'Цена не готова/не тот символ')


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    symbol = message.text[2:].upper()

    if symbol in config.SYMBOLS:
        response = await place_order(symbol, http_session, 'BUY',
                                     quantity=QUANTITY)  # Отправить ордер на покупку (цена в $)
        order_data = response.get("data")
        await message.answer(str(response))

        if order_data:  # Если в ответе есть 'data', То добавить в БД и в память
            cost = float(order_data['cummulativeQuoteQty'])
            executed_qty_real = cost / float(order_data['price'])
            commission = cost * (TAKER + MAKER) / 100  # 1% комиссия от суммы
            cost_with_commission = cost + commission

            data_for_db = {
                'executed_qty': float(order_data['executedQty']),
                'executed_qty_real': executed_qty_real,
                'cost': cost,
                'commission': commission,
                'cost_with_commission': cost_with_commission,
                'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
            }

            await add_order(session, symbol, data_for_db)
            await orders_book.update_orders(symbol, data_for_db)  # Добавить в память
            await message.answer('Ордер открыт')
        else:
            await message.answer('Ордер не открыт')
    else:
        await message.answer('Не тот символ')


@router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    symbol = message.text[2:].upper()

    if symbol in config.SYMBOLS:
        last_order_data = await get_last_order(session, symbol)

        if last_order_data:
            executed_qty, last_id = last_order_data['executed_qty'], last_order_data['id']

            # if account_money < executed_qty:
            #     executed_qty -= 0.00000001

            # --- Отправить ордер на продажу по цене покупки монеты, напр 0.000011 BTC
            response = await place_order(symbol, http_session, 'SELL', executed_qty=executed_qty)
            order_data = response.get("data")
            await message.answer(str(response))

            if order_data:
                await del_last_order(session, last_id)  # Удалить из базы
                await orders_book.delete_last_order(symbol)  # Удалить из памяти
                await message.answer('символ удален')
            else:

                await message.answer('Продажа не прошла')
        else:
            await message.answer('Символы кончились')
    else:
        await message.answer('Не тот символ')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    a = await get_account_balances(http_session)
    print(a)
    # btc_orders = await orders_book.get_orders("BTC")
    # print(btc_orders)
    # btc_orders = await orders_book.get_orders("BNB")
    # print(btc_orders)
    # btc_orders = await orders_book.get_orders("SOL")
    # print(btc_orders)
    # btc_orders = await orders_book.get_orders("ETH")
    # print(btc_orders)
