from asyncio import gather
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, so_manager, price_upd_ws, track_be_level, get_symbol_info, \
    account_manager
from common.config import config
from database.orm_query import del_all_orders, del_symbol, add_symbol
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    # if (price := await ws_price.get_price(symbol)) is None:  # Получить цену монеты
    #     return await message.answer('Цена не готова')

    # if (acc_money_usdt := await account_manager.get_balance('USDT')) < 1.1:
    #     return await message.answer(f'Баланс слишком маленький: {acc_money_usdt}')

    # acc_money = await account_manager.get_balance(symbol)
    # step_size = await so_manager.get_step_size(symbol)
    # sum_executed_qty = await so_manager.get_summary_executed_qty(symbol)
    # execute_qty = QUANTITY / price
    # for_fee = execute_qty * 0.1  # Берем 10% от суммы с запасом на комиссию при покупке для продажи
    #
    # execute_qty_c = execute_qty if acc_money - sum_executed_qty > for_fee else execute_qty + max(for_fee, step_size)
    #
    # # Округляем до ближайшего кратного step_size
    # decimal_places = get_decimal_places(step_size)
    # execute_qty = round(execute_qty, decimal_places)
    # execute_qty_c = round(execute_qty_c, decimal_places)
    #
    # ans = 'НЕТ' if acc_money - sum_executed_qty > for_fee else 'ДА'
    # await message.answer(
    #     f'деньги: {acc_money}\n'
    #     f'summary_executed_qty: {sum_executed_qty}\n'
    #     f'acc_money - summary_executed_qty: {acc_money - sum_executed_qty}\n'
    #     f'Берем комсу: {ans}\n'
    #     f'комиссия: {for_fee}\n'
    #     f'decimal_places: {decimal_places}\n'
    #     f'шаг {step_size}\n'
    #     f'execute_qty: {execute_qty}\n'
    #     f'execute_qty_c: {execute_qty_c}'
    # )
    #
    # response = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)  # Ордер на покупку
    # await message.answer(str(response))
    #
    # if (order_data := response.get("data")) is None:
    #     return await message.answer('Ордер не открыт')
    #
    # # --- Если сумма USDT меньше execute_qty_c, используем уменьшенную сумму executedQty из ответа на запрос
    # executed_qty_order = float(order_data['executedQty'])
    # orig_qty_order = float(order_data['origQty'])
    #
    # # -step_size* для того, чтобы при продаже был резерв для комиссии
    # execute_qty = execute_qty if executed_qty_order == orig_qty_order else (executed_qty_order - step_size)
    #
    # data_for_db = {
    #     'price': price,
    #     'executed_qty': execute_qty,
    #     'cost': (cost := price * execute_qty),  # Цена за одну монету
    #     'cost_with_fee': cost + cost * TAKER_MAKER / 100,  # 0.6% комиссия(на бирже 0.1% + 0.1%)
    #     'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    # }
    #
    # await gather(
    #     add_order(session, symbol, data_for_db),  # Добавить ордер в базу
    #     so_manager.update_order(symbol, data_for_db),  # Добавить ордер в память
    # )
    # await message.answer('Ордер открыт')


# @router.message(F.text.startswith('s_'))  # Вводим например: s_btc, s_Bnb
# async def sell_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
#     if (symbol := message.text[2:].upper()) not in so_manager.symbols:
#         return await message.answer('Не такой символ')
#
#     if (last_order_data := await so_manager.get_last_order(symbol)) is None:
#         return await message.answer('Нет открытых ордеров')
#
#     executed_qty, open_time = last_order_data['executed_qty'], last_order_data['open_time']
#
#     # Ордер на продажу по цене покупки монеты, напр 0.000011 BTC
#     response = await place_order(symbol, http_session, 'SELL', executed_qty=executed_qty)
#     await message.answer(str(response))
#
#     if response.get("data") is None:
#         return await message.answer('Продажа не прошла')
#
#     await gather(
#         del_last_order(session, open_time),  # Удалить из базы
#         so_manager.delete_last_order(symbol),  # Удалить из памяти
#     )
#     await message.answer('Ордер закрыт')


@router.message(F.text.startswith('d_all_'))  # Вводим например: s_btc, s_Bnb
async def del_orders_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[6:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if (summary_executed := await so_manager.get_summary_executed_qty(symbol)) is None:
        return await message.answer('Нет открытых ордеров')

    response = await place_order(symbol, http_session, 'SELL', executed_qty=summary_executed)
    await message.answer(str(response))

    if response.get("data") is None:
        return await message.answer('Продажа не прошла')

    await gather(
        del_all_orders(session, symbol),
        so_manager.delete_all_orders(symbol),
        so_manager.delete_all_orders(symbol),
    )
    await message.answer('Ордер закрыт')


@router.message(F.text.startswith('add_'))  # Добавить символ в БД
async def add_symbol_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[4:].upper()) not in config.SYMBOLS:
        return await message.answer('Не такой символ')

    if symbol in so_manager.symbols:
        return await message.answer('Данный символ уже существует')

    if (symbol_data := await get_symbol_info(symbol, http_session)) is None:
        return await message.answer('Запрос о символе не получен')

    if step_size := await add_symbol(symbol, session, symbol_data):
        await gather(
            so_manager.add_symbol(symbol, step_size),
            price_upd_ws(symbol, http_session),
            track_be_level(symbol)
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
        ws_price.del_task(symbol),
        so_manager.del_task(symbol)
    )

    await message.answer('Символ удален')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    print(ws_price._task_price_upd)
    print(so_manager._task_track_be)
    print("флаг TRX", await so_manager.get_sell_order_flag('TRX'))
    print('баланс USDT', await account_manager.get_balance('USDT'))
    print('баланс TRX', await account_manager.get_balance('TRX'))
    print('баланс ADA', await account_manager.get_balance('ADA'))
    for symbol in so_manager.symbols:
        print(symbol, await ws_price.get_price(symbol))
