from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import OrderInfo, Symbol


# Добавить новый ордер в БД
async def add_order(session: AsyncSession, data: dict):
    symbol_name = data['symbol'].split('-')[0]
    order_id, price, executed_qty = data['orderId'], data['price'], data['executedQty']

    # Сначала добавим Symbol
    query = select(Symbol).where(Symbol.name == symbol_name)
    result = await session.execute(query)
    symbol = result.scalar_one_or_none()

    if symbol is None:  # Если символ не существует в БД, то создается, иначе берем symbol_id из БД
        parent = Symbol(name=symbol_name)
        session.add(parent)
        await session.flush()  # Создается ключ в Symbol без коммита
        symbol_id = parent.id
    else:
        symbol_id = symbol.id

    # Когда Symbol существует, можно добавить и OrderInfo
    child = OrderInfo(order_id=order_id, price=price, executed_qty=executed_qty, symbol_id=symbol_id)
    session.add(child)
    await session.commit()


# Последний ордер, сохраняем его значения
async def get_last_order(session: AsyncSession, symbol: str):
    query = select(func.max(OrderInfo.id)).where(OrderInfo.symbol.has(name=symbol.upper()))
    result = await session.execute(query)
    last_id = result.scalar_one_or_none()

    if last_id:
        last_item = await session.get(OrderInfo, last_id)  # Извлекаем объект по ID
        saved_values = last_item.__dict__.copy()  # Сохраняем значения. Важно использовать copy()
        del saved_values['_sa_instance_state']  # Удаляем служебный атрибут SQLAlchemy

        return saved_values
    else:
        return False


# Последний ордер, удалить из БД
async def del_last_order(session: AsyncSession, last_id):
    last_item = await session.get(OrderInfo, last_id)  # Извлекаем объект по ID
    await session.delete(last_item)
    await session.commit()
