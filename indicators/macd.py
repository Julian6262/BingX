# import talib
# import numpy as np
#
#
# def calculate_macd(close_prices):
#     if len(close_prices) < 26:  # Проверяем, достаточно ли данных для MACD
#         return None
#
#     macd, signal, hist = talib.MACD(close_prices, fastperiod=12, slowperiod=26, signalperiod=9)
#     return macd, signal, hist
#
#
# # Пример использования:
# close_prices = np.random.rand(100) * 100 + 500  # Пример случайных цен
#
# macd_data = calculate_macd(close_prices)
#
# if macd_data:
#     macd, signal, hist = macd_data
#     print("MACD:", macd)
#     print("Signal:", signal)
#     print("Histogram:", hist)
#
#     # Дальнейшая обработка данных MACD (например, поиск пересечений)
#     # ...
#
# else:
#     print("Недостаточно данных для расчета MACD.")
