from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, orders_book, account_balance
from common.config import config
from database.orm_query import add_order, get_last_order, del_last_order
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом

QUANTITY = 2
TAKER = 0.5
MAKER = 0.5


@router.message(F.text.startswith('1_'))  # Вводим например: 1_btc, 1_Bnb
async def get_price_cmd(message: Message):
    symbol = message.text[2:].upper()
    price = await ws_price.get_price(symbol)
    await message.answer(f'Символ {symbol}, цена {price}' if price else 'Цена не готова/не тот символ')


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    symbol = message.text[2:].upper()

    if symbol not in config.SYMBOLS:
        await message.answer('Не такой символ')
        return

    price = await ws_price.get_price(symbol)  # Получить цену монеты

    if price is None:
        await message.answer('Цена не готова')
        return

    account_money = await account_balance.get_balance(symbol)
    step_size = await orders_book.get_step_size(symbol)
    executed_qty = QUANTITY / price
    for_commission = executed_qty * 0.1

    if account_money > for_commission:
        executed_qty_c = executed_qty
    else:
        executed_qty_c = executed_qty + max(for_commission, step_size)

    # Округляем количество монет вниз до ближайшего кратного step_size
    # executed_qty_c1 = float(Decimal(str(executed_qty_c)).quantize(Decimal(str(step_size)), rounding=ROUND_UP))

    await message.answer(f'{account_money}, {for_commission}, {step_size}, {executed_qty}, {executed_qty_c}')

    return

    response = await place_order(symbol, http_session, 'BUY', executed_qty=executed_qty_c)  # Ордер на покупку
    order_data = response.get("data")

    if order_data is None:
        await message.answer('Ордер не открыт')
        await message.answer(str(response))
        return

    price = float(order_data['price'])
    cost = float(order_data['cummulativeQuoteQty'])
    commission = cost * (TAKER + MAKER) / 100  # 1% комиссия от суммы
    cost_with_commission = cost + commission

    data_for_db = {
        'price': price,
        'executed_qty': executed_qty,
        'cost': cost,
        'commission': commission,
        'cost_with_commission': cost_with_commission,
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await add_order(session, symbol, data_for_db)
    await orders_book.update_orders(symbol, data_for_db)  # Добавить в память
    await message.answer('Ордер открыт')


@router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    symbol = message.text[2:].upper()

    if not (symbol in config.SYMBOLS):
        await message.answer('Не такой символ')
        return

    last_order_data = await get_last_order(session, symbol)

    if last_order_data:
        executed_qty, last_id = last_order_data['executed_qty'], last_order_data['id']
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


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    a = await account_balance.get_balance("BTC")
    print(a)
    a = await account_balance.get_balance("BNB")
    print(a)
    btc_orders = await orders_book.get_orders("BTC")
    print(btc_orders)
    btc_orders = await orders_book.get_orders("BNB")
    print(btc_orders)
