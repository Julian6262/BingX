from datetime import datetime
from logging import getLogger

from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import OrderInfo, Symbol, SymbolConfig

logger = getLogger('my_app')


# Добавить новый ордер в БД
async def add_order(session: AsyncSession, symbol_name: str, data: dict):
    try:
        db_symbol = (await session.execute(select(Symbol).where(Symbol.name == symbol_name))).scalar_one_or_none()
        new_order = OrderInfo(**data, symbol=db_symbol)
        session.add(new_order)
        await session.commit()
        return int(new_order.id)

    except Exception as e:
        logger.error(f'Error adding order to DB: {e}')


# Изменить состояние у монеты
async def update_state(session: AsyncSession, symbol_name: str, state: str):
    await session.execute(update(Symbol).where(Symbol.name == symbol_name).values(state=state))
    await session.commit()


# Удалить из БД последний ордер / или все ордера
async def del_orders(symbol_name: str, session: AsyncSession, orders_id: list = None):
    query = (OrderInfo.id.in_(orders_id)) if orders_id else OrderInfo.symbol.has(name=symbol_name)
    await session.execute(delete(OrderInfo).where(query))


# Обновить профит в БД по символу
async def update_profit(symbol: str, session: AsyncSession, profit_diff: float):
    await session.execute(update(Symbol).where(Symbol.name == symbol).values(profit=Symbol.profit + profit_diff))


# Загружаем все ордера и symbols из БД в память
async def load_from_db(session: AsyncSession, so_manager, config_manager):
    query = select(Symbol).options(selectinload(Symbol.orders))
    symbols = (await session.execute(query)).scalars().all()
    data_batch = [(symbol, [order.__dict__ for order in symbol.orders]) for symbol in symbols]
    await so_manager.add_symbols_and_orders(data_batch)

    symbols_config = (await session.execute(select(SymbolConfig))).scalars().all()
    data_batch = [symbol_config for symbol_config in symbols_config]
    await config_manager.load_config(data_batch)


# Добавить символ в БД
async def add_symbol(symbol: str, session: AsyncSession, step_size, state: str = 'stop'):
    session.add(Symbol(name=symbol, step_size=step_size, state=state, profit=0.0))
    await session.commit()


# Удалить символ из БД
async def del_symbol(symbol: str, session: AsyncSession):
    await session.execute(delete(Symbol).where(Symbol.name == symbol))
    await session.commit()
