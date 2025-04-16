import logging

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


# Последний ордер, возвращаем его значения
async def get_last_order(session: AsyncSession, symbol: str):
    query = select(OrderInfo).join(Symbol).where(Symbol.name == symbol).order_by(OrderInfo.id.desc()).limit(1)
    last_order = await session.scalar(query)
    return last_order.__dict__ if last_order else None


# Последний ордер, удалить из БД
async def del_last_order(session: AsyncSession, last_id: int):
    await session.execute(delete(OrderInfo).where(OrderInfo.id == last_id))
    await session.commit()


# Загружаем все ордера и symbols из БД в память
async def load_from_db(session: AsyncSession):
    symbols = (await session.execute(select(Symbol))).scalars().all()
    symbol_batch = [(symbol.name, symbol.step_size, None) for symbol in symbols]

    query = select(OrderInfo).options(selectinload(OrderInfo.symbol))
    orders = (await session.execute(query)).scalars().all()
    order_batch = [(order.symbol.name, None, order.__dict__) for order in orders]

    await orders_book.update_orders_batch(symbol_batch + order_batch)


# Сохраняем символы из настроек в БД
async def save_simbols_to_db(symbols: list, session: AsyncSession, http_session: ClientSession):
    existing_symbols = {symbol.name: symbol for symbol in await session.scalars(select(Symbol))}

    for symbol_name in symbols:
        symbol_info = await get_symbol_info(symbol_name, http_session)

        if symbol_info is None or not symbol_info.get('data', {}).get('symbols'):
            logging.error(f"Ошибка получения информации о символе {symbol_name}: {symbol_info}")
            continue  # Пропускаем этот символ, если произошла ошибка

        step_size = symbol_info['data']['symbols'][0]['stepSize']

        if symbol_name in existing_symbols:
            existing_symbols[symbol_name].step_size = step_size  # Символ существует, обновляем только step_size
        else:
            session.add(Symbol(name=symbol_name, step_size=step_size))  # Символ не существует, добавляем

    await session.commit()
