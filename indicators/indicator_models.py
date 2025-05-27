from asyncio import sleep
from collections import deque
from datetime import datetime
from logging import getLogger
from time import time

from aiohttp import ClientSession
import talib
import numpy as np

from bingx_api.bingx_command import get_candlestick_data, ws_price, so_manager, task_manager, config_manager
from common.func import add_task

logger = getLogger('my_app')


async def _get_initial_close_prices(symbol: str, http_session: ClientSession, interval: str, limit: int = 300):
    data, text = await get_candlestick_data(symbol, http_session, interval, limit=limit)

    if not (data_ok := data.get("data")):
        logger.error(f'Ошибка получения данных candlestick {symbol}: {data}, {text}')
        return None

    start_times, close_prices = zip(*[(item[0], item[4]) for item in reversed(data_ok)])

    timeframe_minutes = {'1m': 1, '4h': 240}

    delta = timeframe_minutes[interval] * 60 * 1000 - 1
    next_candle_time = start_times[-1] + delta

    return delta, next_candle_time, deque(close_prices, maxlen=limit)


async def _process_indicators_logic(symbol: str, close_prices_deque: deque, logic_name: str, rsi_lot_map: dict = None):
    close_prices = np.array(close_prices_deque, dtype=float)

    match logic_name:
        case 'macd_1m':
            _, _, hist = talib.MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)

            if hist[-2] > 0 and await so_manager.get_b_s_trigger(symbol) in ('sell', 'new'):
                print(f'\nПокупаем {symbol}, {datetime.fromtimestamp(int(time()))}')
                await so_manager.set_b_s_trigger(symbol, 'buy')

            elif hist[-2] < 0 and await so_manager.get_b_s_trigger(symbol) in ('buy', 'new'):
                print(f'\nПродаем {symbol}, {datetime.fromtimestamp(int(time()))}')
                await so_manager.set_b_s_trigger(symbol, 'sell')

        case 'rsi_4h':
            rsi = talib.RSI(close_prices, timeperiod=14)[-1]
            lot = await so_manager.get_lot(symbol)

            for (rsi_min, rsi_max), target_lot in rsi_lot_map.items():
                if rsi_min <= rsi < rsi_max and lot != target_lot:
                    await so_manager.set_lot(symbol, target_lot)
                    print(f'rsi {rsi}, lot {symbol} = {target_lot}\n')
                    break  # Выходим из цикла после обновления лота


@add_task(task_manager, so_manager, 'start_indicators')
async def start_indicators(symbol: str, http_session: ClientSession):
    while not await ws_price.get_price(symbol):
        await sleep(0.5)  # Задержка перед попыткой получения цены

    initial_1m_data = await _get_initial_close_prices(symbol, http_session, '1m')
    initial_4h_data = await _get_initial_close_prices(symbol, http_session, '4h')

    if not initial_1m_data or not initial_4h_data:
        return

    delta_1m, next_candle_time_1m, close_prices_deque_1m = initial_1m_data
    delta_4h, next_candle_time_4h, close_prices_deque_4h = initial_4h_data

    logger.info(f'Запуск start_indicators {symbol}')

    symbol_lot = await config_manager.get_config(symbol, 'lot')
    rsi_lot_map = {
        (-float('inf'), 20): symbol_lot * 3,
        (20, 25): symbol_lot * 2.5,
        (25, 30): symbol_lot * 2,
        (30, 40): symbol_lot * 1.5,
        (40, 50): symbol_lot,
        (50, 60): symbol_lot * 0.75,
        (60, 65): symbol_lot * 0.5,
        (65, 70): symbol_lot * 0.35,
        (70, float('inf')): 2,
    }

    await _process_indicators_logic(symbol, close_prices_deque_1m, 'macd_1m')
    await _process_indicators_logic(symbol, close_prices_deque_4h, 'rsi_4h', rsi_lot_map)

    while True:
        time_now, price = await ws_price.get_price(symbol)

        if time_now >= next_candle_time_1m:
            close_prices_deque_1m[-1] = price
            close_prices_deque_1m.append(price)
            next_candle_time_1m += delta_1m  # Обновляем время следующей свечи
            await _process_indicators_logic(symbol, close_prices_deque_1m, 'macd_1m')

        close_prices_deque_4h[-1] = price
        if time_now >= next_candle_time_4h:
            close_prices_deque_4h.append(price)
            next_candle_time_4h += delta_4h
        if await so_manager.get_b_s_trigger(symbol) == 'buy':  # вызываем индикатор rsi_4h только если покупаем
            await _process_indicators_logic(symbol, close_prices_deque_4h, 'rsi_4h', rsi_lot_map)

        await sleep(1)
