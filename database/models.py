from sqlalchemy import DateTime, func, String, ForeignKey, BigInteger, Numeric
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

    order_id: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    executed_qty: Mapped[float] = mapped_column(Numeric(10, 8))
    symbol_id: Mapped[int] = mapped_column(ForeignKey('symbol.id'), index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    symbol: Mapped["Symbol"] = relationship(back_populates="orders")
