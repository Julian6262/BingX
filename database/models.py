from sqlalchemy import DateTime, String, ForeignKey, Numeric, Float
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from typing import List


class Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class Symbol(Base):
    __tablename__ = 'symbol'

    name: Mapped[str] = mapped_column(String(10), unique=True)

    orders: Mapped[List["OrderInfo"]] = relationship(back_populates="symbol")


class OrderInfo(Base):
    __tablename__ = 'order_info'

    executed_qty: Mapped[float] = mapped_column(Float)
    executed_qty_real: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float)
    cost_with_commission: Mapped[float] = mapped_column(Float)
    symbol_id: Mapped[int] = mapped_column(ForeignKey('symbol.id'), index=True)
    open_time: Mapped[DateTime] = mapped_column(DateTime)

    symbol: Mapped["Symbol"] = relationship(back_populates="orders")
