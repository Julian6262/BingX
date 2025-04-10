from database.models import Base


async def init_db(engine, drop_all=False):
    async with engine.begin() as conn:
        if drop_all:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)  # Всегда создаем таблицы
