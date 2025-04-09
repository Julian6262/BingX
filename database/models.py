from sqlalchemy import DateTime, func, String, ForeignKey, Integer, Float
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from typing import List


class Base(AsyncAttrs, DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class Symbol(Base):
    __tablename__ = 'symbol'

    name: Mapped[str] = mapped_column(String(10), unique=True)

    orders: Mapped[List["OrderInfo"]] = relationship("OrderInfo", back_populates="symbol")


class OrderInfo(Base):
    __tablename__ = 'order_info'

    order_id: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float(asdecimal=True))
    executed_qty: Mapped[float] = mapped_column(Float(asdecimal=True))
    symbol_id: Mapped[int] = mapped_column(ForeignKey('symbol.id'), index=True)
    created: Mapped[DateTime] = mapped_column(DateTime, default=func.now())
    updated: Mapped[DateTime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    symbol: Mapped["Symbol"] = relationship("Symbol", back_populates="orders")
