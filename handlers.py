from asyncio import gather
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_api.bingx_command import price_upd_ws, get_symbol_info, account_manager, start_trading, place_buy_order, \
    so_manager, ws_price, task_manager, place_sell_order, profit_manager
from common.config import config
from database.orm_query import del_symbol, add_symbol
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом


@router.message(F.text.startswith('profit_'))  # Показать профит по каждому ордеру
async def get_profit_cmd(message: Message):
    if (symbol := message.text[7:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if not (profit_data := await profit_manager.get_data(symbol)):
        return await message.answer('Данные не готовы')

    price = profit_data['price']
    summary_executed = profit_data['summary_executed']

    await message.answer(
        f'summary_executed: {summary_executed}\n'
        f'\nprice * summary_executed: {price * summary_executed}\n'
        f'сумма с комиссией биржи (total_cost_with_fee): {profit_data['total_cost_with_fee']}\n'
        f'сумма с комиссией биржи + 1% (total_cost_with_fee_tp): {profit_data['total_cost_with_fee_tp']}\n'
        f'\nДоход с учетом комиссии биржи 0,3%: {profit_data['current_profit']}\n'
        f'Доход с учетом комиссии биржи 0,3% до достижения 1%: {profit_data['profit_to_target']}\n'
        f'\nprice: {price}\n'
        f'безубыток с комиссией биржи (be_level_with_fee): {profit_data['be_level_with_fee']}\n'
        f'безубыток с комиссией биржи + 1% (be_level_with_fee_tp): {profit_data['be_level_with_fee_tp']}\n'
        # f'До достижения безубыток с комиссией биржи: {be_level_with_fee - price}\n'
        # f'До достижения  безубыток с комиссией биржи + 1%: {be_level_with_fee_tp - price}\n'
    )

    orders = await so_manager.get_orders(symbol)

    for order in orders:
        order_profit = order['executed_qty'] * price - order['cost_with_fee']
        await message.answer(str(order_profit))


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if (price := await ws_price.get_price(symbol)) is None:  # Получить цену монеты
        return await message.answer('Цена не готова')

    response = await place_buy_order(symbol, price, session, http_session)
    await message.answer(response)


@router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if not (order_data := await so_manager.get_last_order(symbol)):
        return await message.answer('Нет открытых ордеров')

    response = await place_sell_order(symbol, order_data['executed_qty'], session, http_session,
                                      open_time=order_data['open_time'])

    price = await ws_price.get_price(symbol)
    order_profit = order_data['executed_qty'] * price - order_data['cost_with_fee']
    await message.answer(response + f'Доход: {order_profit}\n')


@router.message(F.text.startswith('d_all_'))
async def del_orders_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[6:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if (summary_executed := await so_manager.get_summary_executed_qty(symbol)) is None:
        return await message.answer('Нет открытых ордеров')

    price = await ws_price.get_price(symbol)
    total_cost_with_fee = await so_manager.get_total_cost_with_fee(symbol)
    current_profit = price * summary_executed - total_cost_with_fee

    response = await place_sell_order(symbol, summary_executed, session, http_session)
    await message.answer(response + f'Доход: {current_profit}\n')


@router.message(F.text.startswith('add_'))  # Добавить символ в БД
async def add_symbol_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[4:].upper()) not in config.SYMBOLS:
        return await message.answer('Не такой символ')

    if symbol in so_manager.symbols:
        return await message.answer('Данный символ уже существует')

    data, text = await get_symbol_info(symbol, http_session)
    if data is None:
        return await message.answer(f'Запрос о символе не получен {text}')

    step_size = data['data']['symbols'][0]['stepSize']
    await add_symbol(symbol, session, step_size)
    await gather(
        so_manager.add_symbol(symbol, step_size),
        price_upd_ws(symbol, http_session=http_session),
        start_trading(symbol, session=session, http_session=http_session)
    )
    await message.answer('Символ добавлен')


@router.message(F.text.startswith('del_'))  # Удалить символ из БД
async def del_symbol_cmd(message: Message, session: AsyncSession):
    if (symbol := message.text[4:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if await so_manager.get_orders(symbol):
        return await message.answer('По данному символу есть ордера')

    await gather(
        del_symbol(symbol, session),
        so_manager.delete_symbol(symbol),
        task_manager.del_tasks(symbol)
    )

    await message.answer('Символ удален')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    print(task_manager._tasks)
    print(so_manager._orders)
    print(account_manager._balance)
    for symbol in so_manager.symbols:
        print(symbol, await ws_price.get_price(symbol))
