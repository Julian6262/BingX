from asyncio import sleep

import talib
from aiohttp import ClientSession

import numpy as np
import datetime

from bingx_api.bingx_command import get_candlestick_data, ws_price, so_manager


# async def update_candles_ws(close_prices: np.ndarray):
#     macd_data = talib.MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)
#
#     if macd_data:
#         _, _, hist = macd_data
#         return hist


async def start_indicator(symbol: str, http_session: ClientSession, interval):
    while not await ws_price.get_price(symbol):
        await sleep(0.5)  # Задержка перед попыткой получения цены

    data, text = await get_candlestick_data(symbol, http_session, interval)

    if not (data_ok := data.get("data")):
        print(data, text)
        return

    start_times, close_prices = zip(*[(int(item[0]), float(item[4])) for item in reversed(data_ok)])
    close_prices = np.array(close_prices, dtype=float)
    delta = datetime.timedelta(minutes=1)
    next_candle_time = datetime.datetime.fromtimestamp(start_times[-1] / 1000) + delta

    # print(f'Начальная свеча {last_candle_time}')
    # print(f'Следующая свеча {next_candle_time}\n')
    # print(f'Цены       {close_prices[-5:]}')

    while True:
        # print(f'\nЦены новые {close_prices[-5:]}')
        # print(f'{hist[-10:]}\n')

        time_now, price = await ws_price.get_price(symbol)
        time_now = datetime.datetime.fromtimestamp(time_now / 1000)

        if time_now >= next_candle_time:
            close_prices = np.append(close_prices[1:], price)
            next_candle_time += delta  # Обновляем время следующей свечи

            # print(f"\nNew candle closed at {time_now}, price: {price}\n")
        else:
            close_prices[-1] = price

        # hist = await update_candles_ws(close_prices)

        _, _, hist = talib.MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)

        if hist[-2] > 0 and hist[-1] > 0 and so_manager.buy_sell_trigger in ('sell', 'new'):
            print(f'Покупаем, {time_now}')
            print(f'{hist[-10:]}\n')
            so_manager.buy_sell_trigger = 'buy'

        elif hist[-2] < 0 and hist[-1] < 0 and so_manager.buy_sell_trigger in ('buy', 'new'):
            print(f'Продаем, {time_now}')
            print(f'{hist[-10:]}\n')
            so_manager.buy_sell_trigger = 'sell'

        await sleep(1)
