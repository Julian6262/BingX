from asyncio import gather

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bingx_command import orders_book
from database.models import OrderInfo, Symbol


# Добавить новый ордер в БД
async def add_order(session: AsyncSession, data: dict):
    symbol_name = data['symbol'].split('-')[0]
    order_id, price, executed_qty = data['orderId'], data['price'], data['executedQty']

    query = select(Symbol).where(Symbol.name == symbol_name).with_for_update()
    symbol = (await session.execute(query)).scalar_one_or_none()

    if symbol is None:
        symbol = Symbol(name=symbol_name)
        session.add(symbol)

    order_info = OrderInfo(order_id=order_id, price=price, executed_qty=executed_qty, symbol=symbol)
    session.add(order_info)
    await session.commit()


# Последний ордер, сохраняем его значения
async def get_last_order(session: AsyncSession, symbol: str):
    query = select(func.max(OrderInfo.id)).join(Symbol).where(Symbol.name == symbol)
    last_order_id = (await session.execute(query)).scalar_one_or_none()

    if last_order_id:
        return (await session.get(OrderInfo, last_order_id)).__dict__.copy()
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
    await gather(*(orders_book.update_orders(order.symbol.name, order.price, order.executed_qty) for order in orders))
