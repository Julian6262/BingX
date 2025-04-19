from datetime import datetime
from aiohttp import ClientSession
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bingx_command import orders_book, get_symbol_info
from database.models import OrderInfo, Symbol


# Добавить новый ордер в БД
async def add_order(session: AsyncSession, symbol_name: str, data: dict):
    db_symbol = (await session.execute(select(Symbol).where(Symbol.name == symbol_name))).scalar_one()
    session.add(OrderInfo(**data, symbol=db_symbol))
    await session.commit()


# Удалить из БД последний ордер
async def del_last_order(session: AsyncSession, open_time: datetime):
    await session.execute(delete(OrderInfo).where(OrderInfo.open_time == open_time))
    await session.commit()


# Удалить из БД все ордера
async def del_all_orders(session: AsyncSession, symbol_name: str):
    await session.execute(delete(OrderInfo).where(OrderInfo.symbol.has(name=symbol_name)))
    await session.commit()


# Загружаем все ордера и symbols из БД в память
async def load_from_db(session: AsyncSession):
    query = select(Symbol).options(selectinload(Symbol.orders))
    symbols = (await session.execute(query)).scalars().all()

    data_batch = [(symbol.name, symbol.step_size, [order.__dict__ for order in symbol.orders]) for symbol in symbols]
    await orders_book.add_symbols_and_orders_batch(data_batch)


# Добавить символ из БД
async def add_symbol(symbol: str, session: AsyncSession, http_session: ClientSession):
    if (symbol_data := await get_symbol_info(symbol, http_session)) is None:
        return None

    step_size = symbol_data['data']['symbols'][0]['stepSize']
    session.add(Symbol(name=symbol, step_size=step_size))
    await session.commit()
    return step_size


# Удалить символ из БД
async def del_symbol(symbol: str, session: AsyncSession):
    await session.execute(delete(Symbol).where(Symbol.name == symbol))
    await session.commit()
