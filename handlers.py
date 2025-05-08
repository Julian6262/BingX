from asyncio import gather
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_api.bingx_command import price_upd_ws, get_symbol_info, start_trading, place_buy_order, so_manager, ws_price, \
    task_manager, place_sell_order, profit_manager
from common.config import config
from database.orm_query import del_symbol, add_symbol, update_state
from filters.chat_types import IsAdmin
from indicators.indicator_models import start_indicator

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом


@router.message(F.text.startswith('track_') | F.text.startswith('pause_') | F.text.startswith('stop_'))
async def set_state_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    state_new, symbol = message.text.split('_')
    symbol = symbol.upper()

    if symbol not in so_manager.symbols:
        return await message.answer('Не такой символ')

    state_old = await so_manager.get_state(symbol)

    await gather(
        update_state(session, symbol, state_new),
        so_manager.update_state(symbol, state_new)
    )

    if state_old in ('track', 'pause') and state_new == 'stop':
        await task_manager.del_tasks(symbol)

    elif state_old == 'stop' and state_new in ('track', 'pause'):
        await gather(
            price_upd_ws(symbol, http_session=http_session),
            start_trading(symbol, session=session, http_session=http_session)
        )

    await message.answer(f"Статус монеты {symbol} изменен c {state_old} на {state_new}")


@router.message(F.text.startswith('profit_'))  # Показать профит по каждому ордеру
async def get_profit_cmd(message: Message):
    if (symbol := message.text[7:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if await so_manager.get_state(symbol) == 'stop':
        return await message.answer('Отслеживание монеты остановлено!')

    if not (profit_data := await profit_manager.get_data(symbol)):
        return await message.answer('Данные не готовы')

    price = profit_data['price']
    summary_executed = profit_data['summary_executed']

    await message.answer(
        f'\nprice: {price}\n'
        f'summary_executed: {summary_executed}\n'
        f'\nprice * summary_executed: {price * summary_executed}\n'
        f'сумма с комиссией биржи (total_cost_with_fee): {profit_data['total_cost_with_fee']}\n'
        f'сумма с комиссией биржи + 1% (total_cost_with_fee_tp): {profit_data['total_cost_with_fee_tp']}\n'
        f'\nДоход с учетом комиссии биржи: {profit_data['current_profit']}\n'
        f'Доход с учетом комиссии биржи до достижения 1%: {profit_data['profit_to_target']}\n'
        f'безубыток с комиссией биржи (be_level_with_fee): {profit_data['be_level_with_fee']}\n'
        f'безубыток с комиссией биржи + 1% (be_level_with_fee_tp): {profit_data['be_level_with_fee_tp']}\n'
        # f'До достижения безубыток с комиссией биржи: {be_level_with_fee - price}\n'
        # f'До достижения  безубыток с комиссией биржи + 1%: {be_level_with_fee_tp - price}\n'
    )

    orders = await so_manager.get_orders(symbol)
    order_profits = [order['executed_qty'] * price - order['cost_with_fee'] for order in orders]
    await message.answer("\n".join(map(str, order_profits)))


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    price_data = await ws_price.get_price(symbol)
    if price_data is None:
        return await message.answer('Цена не готова')

    response = await place_buy_order(symbol, price_data[1], session, http_session)
    await message.answer(response)


@router.message(F.text.startswith('s_all_'))  # Продажа всех ордеров
async def del_orders_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[6:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if (summary_executed := await so_manager.get_summary_executed_qty(symbol)) is None:
        return await message.answer('Нет открытых ордеров')

    profit_data = await profit_manager.get_data(symbol)
    report = await place_sell_order(symbol, summary_executed, session, http_session, data=profit_data)

    await message.answer(report)


@router.message(F.text.startswith('s_'))  # Продажа одного последнего ордера
async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if not (order_data := await so_manager.get_last_order(symbol)):
        return await message.answer('Нет открытых ордеров')

    profit_data = await profit_manager.get_data(symbol)
    profit_data['total_cost_with_fee'] = order_data['cost_with_fee']  # перезаписать стоимость по последнему ордеру

    report = await place_sell_order(symbol, order_data['executed_qty'], session, http_session, data=profit_data,
                                    open_time=order_data['open_time'])

    await message.answer(report)


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
    await gather(
        add_symbol(symbol, session, step_size),
        so_manager.add_symbol(symbol, step_size),
    )
    await message.answer('Символ добавлен в статусе "stop"')


@router.message(F.text.startswith('del_'))  # Удалить символ из БД
async def del_symbol_cmd(message: Message, session: AsyncSession):
    if (symbol := message.text[4:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if await so_manager.get_state(symbol) != 'stop':
        return await message.answer('Сначала переведите в статус "stop"')

    if await so_manager.get_orders(symbol):
        return await message.answer('По данному символу есть ордера')

    if await so_manager.get_profit(symbol):
        return await message.answer('По данному символу есть профит')

    await gather(
        del_symbol(symbol, session),
        so_manager.delete_symbol(symbol),
    )

    await message.answer('Символ удален')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    for tasks in task_manager._tasks.items():
        print(tasks)
    for tasks in so_manager._data.items():
        print(tasks)

    profit = await so_manager.get_profit('ADA')
    await message.answer(f'profit ADA {profit}')
    profit = await so_manager.get_profit('TRX')
    await message.answer(f'profit TRX {profit}')
    profit = await so_manager.get_profit('XRP')
    await message.answer(f'profit XRP {profit}')
    sum_profit = await so_manager.get_summary_profit()
    await message.answer(f'sum_profit {sum_profit}')
