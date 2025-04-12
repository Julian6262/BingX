from asyncio import gather

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bingx_command import orders_book
from database.models import OrderInfo, Symbol


# Добавить новый ордер в БД
async def add_order(session: AsyncSession, symbol_name, data: dict):
    query = select(Symbol).where(Symbol.name == symbol_name).with_for_update()
    symbol = (await session.execute(query)).scalar_one_or_none()

    if symbol is None:
        symbol = Symbol(name=symbol_name)
    session.add(symbol)

    order_info = OrderInfo(executed_qty=data['executed_qty'], executed_qty_real=data['executed_qty_real'],
                           cost=data['cost'], commission=data['commission'],
                           cost_with_commission=data['cost_with_commission'],
                           open_time=data['open_time'], symbol=symbol)
    session.add(order_info)
    await session.commit()


# Последний ордер, возвращаем его значения
async def get_last_order(session: AsyncSession, symbol: str):
    query = select(func.max(OrderInfo.id)).join(Symbol).where(Symbol.name == symbol)
    last_order_id = (await session.execute(query)).scalar_one_or_none()

    if last_order_id:
        return (await session.get(OrderInfo, last_order_id)).__dict__
    return None


# Последний ордер, удалить из БД
async def del_last_order(session: AsyncSession, last_id: int):
    query = delete(OrderInfo).where(OrderInfo.id == last_id)
    await session.execute(query)
    await session.commit()


# Загружаем все ордера из БД в память
async def load_orders_db(session: AsyncSession):
    query = select(OrderInfo).options(selectinload(OrderInfo.symbol))
    orders = (await session.execute(query)).scalars().all()

    # параллельное выполнение update_orders
    await gather(*(orders_book.update_orders(order.symbol.name, order.__dict__) for order in orders))
