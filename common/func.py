from decimal import Decimal
from asyncio import create_task
from functools import wraps

from aiohttp import ClientSession


def get_decimal_places(step_size):
    d = Decimal(str(step_size))
    if d == d.to_integral_value():  # Проверяем, является ли число целым
        return 0
    else:
        return abs(d.as_tuple().exponent)


def add_task(outer_func, text: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(symbol, *args, **kwargs):
            task = create_task(func(symbol, *args, **kwargs))
            await outer_func.add_task(symbol, task)
            print(f'Запущено отслеживание {text} {symbol}')
            return task

        return wrapper

    return decorator
