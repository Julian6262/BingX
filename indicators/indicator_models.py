from asyncio import sleep
from collections import deque
from datetime import datetime
from logging import getLogger
from aiohttp import ClientSession
import talib
import numpy as np

from bingx_api.bingx_command import get_candlestick_data, ws_price, so_manager, task_manager
from common.func import add_task

logger = getLogger('my_app')


@add_task(task_manager, so_manager, 'start_indicator')
async def start_indicator(symbol: str, http_session: ClientSession, interval, limit=300):
    while not await ws_price.get_price(symbol):
        await sleep(0.5)  # Задержка перед попыткой получения цены

    data, text = await get_candlestick_data(symbol, http_session, interval, limit=limit)

    if not (data_ok := data.get("data")):
        logger.error(f'Ошибка получения данных candlestick: {data}, {text}')
        return

    logger.info(f'Запуск start_indicator {symbol}')

    start_times, close_prices = zip(*[(item[0], item[4]) for item in reversed(data_ok)])
    close_prices_deque = deque(close_prices, maxlen=limit)
    delta = 1 * 60 * 1000 - 1  # 1 минута
    next_candle_time = start_times[-1] + delta

    while True:
        time_now, price = await ws_price.get_price(symbol)

        if time_now >= next_candle_time:
            close_prices_deque[-1] = price
            close_prices_deque.append(price)
            next_candle_time += delta  # Обновляем время следующей свечи

            close_prices = np.array(close_prices_deque, dtype=float)
            _, _, hist = talib.MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)

            if hist[-2] > 0 and await so_manager.get_b_s_trigger(symbol) in ('sell', 'new'):
                await so_manager.set_b_s_trigger(symbol, 'buy')
                # -----------------------------------------------
                if symbol == 'ADA':
                    print(f'\nПокупаем {symbol}, {datetime.fromtimestamp(time_now / 1000)}\n')
                    # print(f'{hist[-7:]}\n')

            elif hist[-2] < 0 and await so_manager.get_b_s_trigger(symbol) in ('buy', 'new'):
                await so_manager.set_b_s_trigger(symbol, 'sell')
                # -----------------------------------------------
                if symbol == 'ADA':
                    print(f'\nПродаем {symbol}, {datetime.fromtimestamp(time_now / 1000)}\n')
                    # print(f'{hist[-7:]}\n')

        await sleep(0.05)
