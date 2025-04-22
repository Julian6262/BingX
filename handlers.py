from asyncio import gather
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import ClientSession
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order, so_manager, price_upd_ws, track_be_level, get_symbol_info, \
    account_manager, start_trading, place_buy_order
from common.config import config
from database.orm_query import del_all_orders, del_symbol, add_symbol
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом


@router.message(F.text.startswith('b_'))  # Вводим например: b_btc, b_Bnb
async def buy_order_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    if (symbol := message.text[2:].upper()) not in so_manager.symbols:
        return await message.answer('Не такой символ')

    if (price := await ws_price.get_price(symbol)) is None:  # Получить цену монеты
        return await message.answer('Цена не готова')

    response = await place_buy_order(symbol, price, session, http_session)
    await message.answer(response)


@router.message(F.text.startswith('d_all_'))
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
    )
    await message.answer('Ордеры закрыт')


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
            price_upd_ws(symbol, http_session=http_session),
            track_be_level(symbol),
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
        ws_price.del_tasks(symbol),
        so_manager.del_tasks(symbol)
    )

    await message.answer('Символ удален')


# ----------------- T E S T ---------------------------------------
@router.message(CommandStart())
async def start_cmd(message: Message, session: AsyncSession, http_session: ClientSession):
    print(ws_price._tasks)
    print(so_manager._tasks)
    print(so_manager._orders)
    print(account_manager._balance)
    for symbol in so_manager.symbols:
        print(symbol, await ws_price.get_price(symbol))
