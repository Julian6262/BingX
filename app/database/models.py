from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created: Mapped[DateTime] = mapped_column(DateTime, default=func.now())
    updated: Mapped[DateTime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

# class Symbol(Base):
#     __tablename__ = 'symbols'
#
#     name: Mapped[str] = mapped_column(String(150), nullable=False)
#     description: Mapped[str] = mapped_column(Text)
#     price: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
#     image: Mapped[str] = mapped_column(String(150))
#     category_id: Mapped[int] = mapped_column(ForeignKey('category.id', ondelete='CASCADE'), nullable=False)
#
#     category: Mapped['Category'] = relationship(backref='product')

