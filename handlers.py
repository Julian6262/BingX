from asyncio import gather
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, orders_book, account_balance
from common.config import config
from database.orm_query import add_order, del_last_order
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом

QUANTITY = 2
TAKER = 0.5
MAKER = 0.5

TAKER_MAKER = TAKER + MAKER


@router.message(F.text.startswith('1_'))  # Вводим например: 1_btc, 1_Bnb
async def get_price_cmd(message: Message):
    symbol = message.text[2:].upper()
    price = await ws_price.get_price(symbol)
    await message.answer(f'Символ {symbol}, цена {price}' if price else 'Цена не готова/не тот символ')


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in config.SYMBOLS:
        return await message.answer('Не такой символ')

    if (price := await ws_price.get_price(symbol)) is None:  # Получить цену монеты
        return await message.answer('Цена не готова')

    if (acc_money_usdt := await account_balance.get_balance('USDT')) < 1:
        return await message.answer(f'Баланс слишком маленький: {acc_money_usdt}')

    acc_money = await account_balance.get_balance(symbol)
    step_size = await orders_book.get_step_size(symbol)
    execute_qty = QUANTITY / price
    for_commission = execute_qty * 0.1  # Берем 10% от суммы с запасом на комиссию при покупке

    # Округляем до ближайшего кратного step_size
    for_commission = Decimal(for_commission).quantize(Decimal(step_size), rounding=ROUND_UP)
    execute_qty = Decimal(execute_qty).quantize(Decimal(step_size), rounding=ROUND_DOWN)

    sum_executed_qty = await orders_book.get_summary_executed_qty(symbol)
    execute_qty_c = float(
        execute_qty if acc_money - sum_executed_qty > for_commission else execute_qty + max(for_commission, step_size)
    )

    return await message.answer(
        f'деньги: {acc_money}\n'
        f'summary_executed_qty: {sum_executed_qty}\n'
        f'acc_money - summary_executed_qty: {acc_money - sum_executed_qty}\n'
        f'комиссия: {for_commission}\n'
        f'шаг {step_size}\n'
        f'execute_qty: {float(execute_qty)}\n'
        f'execute_qty_c: {execute_qty_c}\n'
    )

    response = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)  # Ордер на покупку
    await message.answer(str(response))

    if (order_data := response.get("data")) is None:
        return await message.answer('Ордер не открыт')

    # --- Если сумма USDT меньше execute_qty_c, используем уменьшенную сумму executedQty из ответа на запрос
    executed_qty_order = float(order_data['executedQty'])
    orig_qty_order = float(order_data['origQty'])
    # *executed_qty_order-step_size* для того, чтобы при продаже был резерв для комиссии
    execute_qty = float(execute_qty) if executed_qty_order == orig_qty_order else (executed_qty_order - step_size)

    data_for_db = {
        'price': price,
        'executed_qty': execute_qty,
        'cost': (cost := price * execute_qty),  # Цена за одну монету
        'commission': (commission := cost * TAKER_MAKER / 100),  # 1% комиссия(на бирже 0.1% + 0.1%)
        'cost_with_commission': cost + commission,
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await gather(
        add_order(session, symbol, data_for_db),  # Добавить ордер в базу
        orders_book.update_order(symbol, data_for_db),  # Добавить ордер в память
    )
    await message.answer('Ордер открыт')


@router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in config.SYMBOLS:
        return await message.answer('Не такой символ')

    if (last_order_data := await orders_book.get_last_order(symbol)) is None:
        return await message.answer('Символы кончились')

    executed_qty, open_time = last_order_data['executed_qty'], last_order_data['open_time']

    # Ордер на продажу по цене покупки монеты, напр 0.000011 BTC
    response = await place_order(symbol, http_session, 'SELL', executed_qty=executed_qty)
    await message.answer(str(response))

    if response.get("data") is None:
        return await message.answer('Продажа не прошла')

    await gather(
        del_last_order(session, open_time),  # Удалить из базы
        orders_book.delete_last_order(symbol),  # Удалить из памяти
    )
    await message.answer('символ удален')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    a = await account_balance.get_balance("USDT")
    print(a)
    a = await account_balance.get_balance("BTC")
    print(a)
    btc_orders = await orders_book.get_orders("BTC")
    print(btc_orders)
    btc_orders = await orders_book.get_orders("ADA")
    print(btc_orders)
    summary = await orders_book.get_summary_executed_qty("BTC")
    print(summary)
