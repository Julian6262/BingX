from asyncio import sleep
from collections import deque
from logging import getLogger
from aiohttp import ClientSession
from talib import MACD, RSI
from numpy import array as np_array

from bingx_api.bingx_command import get_candlestick_data, ws_price, so_manager, task_manager, config_manager, \
    account_manager
from common.config import config
from common.func import add_task

logger = getLogger('my_app')


async def _get_initial_close_prices(symbol: str, http_session: ClientSession, interval: str, limit: int = 300):
    data, text = await get_candlestick_data(symbol, http_session, interval, limit=limit)

    if not (data_ok := data.get("data")):
        logger.error(f'Ошибка получения данных candlestick {symbol}: {data}, {text}')
        return None

    open_times, close_price = zip(*[(item[0], item[4]) for item in reversed(data_ok)])

    timeframe_minutes = {'1m': 1, '4h': 240}

    delta = timeframe_minutes[interval] * 60 * 1000 - 1
    next_candle_time = open_times[-1] + delta
    return delta, next_candle_time, deque(close_price, maxlen=limit)


async def _process_indicators_logic(symbol: str, close_prices: deque, logic_name: str, main_lot_map: dict = None):
    close_prices = np_array(close_prices, dtype=float)

    match logic_name:
        case 'macd_1m':
            _, _, hist = MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)

            if hist[-2] > 0 and hist[-1] > 0 and await so_manager.get_b_s_trigger(symbol) in ('sell', 'new'):
                await so_manager.set_b_s_trigger(symbol, 'buy')

            elif hist[-2] < 0 and hist[-1] < 0 and await so_manager.get_b_s_trigger(symbol) in ('buy', 'new'):
                await so_manager.set_b_s_trigger(symbol, 'sell')

        case 'rsi_4h':
            rsi = RSI(close_prices, timeperiod=14)[-1]
            grid_size = await config_manager.get_data(symbol, 'grid_size')
            usdt_balance = await account_manager.get_balance('USDT')

            for (min_balance, max_balance), lot in main_lot_map.items():
                if min_balance < usdt_balance <= max_balance:
                    main_lot = lot
                    break

            rsi_lot_and_grid_map = {
                (-float('inf'), 20): (main_lot * 3, grid_size * 3.8),
                (20, 25): (main_lot * 2.5, grid_size * 3.35),
                (25, 30): (main_lot * 2, grid_size * 2.9),
                (30, 35): (main_lot * 1.75, grid_size * 2.45),
                (35, 40): (main_lot * 1.5, grid_size * 1.95),
                (40, 45): (main_lot * 1.25, grid_size * 1.65),
                (45, 50): (main_lot, grid_size * 1.55),
                (50, 55): (main_lot * 0.75, grid_size * 1.3),
                (55, 60): (main_lot * 0.55, grid_size * 1.25),
                (60, 65): (main_lot * 0.35, grid_size * 1.2),
                (65, 70): (main_lot * 0.2, grid_size * 1.1),
                (70, float('inf')): (main_lot * 0.15, grid_size)
            }

            for (rsi_min, rsi_max), (target_lot, target_grid_size) in rsi_lot_and_grid_map.items():
                if rsi_min <= rsi < rsi_max and (main_lot != target_lot or grid_size != target_grid_size):
                    await config_manager.set_data(symbol, 'lot', target_lot)
                    await config_manager.set_data(symbol, 'main_lot', main_lot)  # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                    await config_manager.set_data(symbol, 'target_grid_size', target_grid_size)
                    await config_manager.set_data(symbol, 'init_rsi', True)  # сначала индикатор, потом запуск торгов
                    break  # Выходим из цикла после обновления лота


@add_task(task_manager, so_manager, 'start_indicators')
async def start_indicators(symbol: str, http_session: ClientSession):
    while not await ws_price.get_price(symbol):
        await sleep(0.3)  # Задержка перед попыткой получения цены

    initial_1m_data = await _get_initial_close_prices(symbol, http_session, '1m')
    initial_4h_data = await _get_initial_close_prices(symbol, http_session, '4h')

    if not initial_1m_data or not initial_4h_data:
        return

    delta_1m, next_candle_time_1m, close_prices_deque_1m = initial_1m_data
    delta_4h, next_candle_time_4h, close_prices_deque_4h = initial_4h_data

    logger.info(f'Запуск start_indicators {symbol}')

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

        # !!!!!!!!!! запускается много раз, изменить логику !!!!!!!!!!!!!!!
        if await so_manager.get_b_s_trigger(symbol) in ('buy', 'new'):
            await _process_indicators_logic(symbol, close_prices_deque_4h, 'rsi_4h', config.MAIN_LOT_MAP)

        await sleep(1)
