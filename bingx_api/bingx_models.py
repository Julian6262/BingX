from asyncio import Lock, CancelledError
from collections import defaultdict
from datetime import datetime


class ProfitManager:  # Класс для работы с данными профита
    def __init__(self):
        self._data = {}
        self._lock = Lock()

    async def update_data(self, symbol: str, data: dict):
        async with self._lock:
            self._data[symbol] = data

    async def get_data(self, symbol: str):
        async with self._lock:
            return self._data[symbol]


class AccountManager:  # Класс для работы с данными счета
    def __init__(self):
        self._balance = {}
        self._listen_key = None
        self._lock = Lock()

    async def update_balance_batch(self, batch_data: list):
        async with self._lock:
            for data in batch_data:
                self._balance[data['a']] = float(data['wb'])

    async def get_balance(self, symbol: str):
        async with self._lock:
            return self._balance.get(symbol, 0.0)

    async def add_listen_key(self, listen_key: str):
        async with self._lock:
            self._listen_key = listen_key

    async def get_listen_key(self):
        async with self._lock:
            return self._listen_key


# class IndicatorManager:  # Класс для работы с индикаторами
#     def __init__(self):
#         self._start_candles = {}
#         self._lock = Lock()
#
#     async def add_start_candles(self, symbol: str, candlestick_data: ndarray):
#         async with self._lock:
#             self._start_candles[symbol] = candlestick_data
#
#     async def get_start_candles(self, symbol: str):
#         async with self._lock:
#             return self._start_candles.get(symbol)


class TaskManager:  # Класс для работы с задачами
    def __init__(self):
        self._tasks = defaultdict(list)
        self._lock = Lock()

    async def add_task(self, symbol: str, task):
        async with self._lock:
            self._tasks[symbol].append(task)

    async def del_tasks(self, symbol: str):
        async with self._lock:
            for task in self._tasks.pop(symbol, []):
                if task and not task.done():  # Проверяем, что задача существует и не завершена
                    task.cancel()
                    try:
                        await task  # Дожидаемся завершения задачи
                    except CancelledError:
                        pass  # Игнорируем CancelledError - это ожидаемое поведение


class WebSocketPrice:  # Класс для работы с ценами в реальном времени из websockets
    def __init__(self):
        self._data = {}
        self._lock = Lock()

    async def update_price(self, symbol: str, time: int, price: float):
        async with self._lock:
            self._data[symbol] = time, price

    async def get_price(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol)


class SymbolOrderManager:  # Класс для работы с ордерами в реальном времени
    def __init__(self):
        self.symbols = []
        self.pause_after_sell = False
        self.buy_sell_trigger = 'new'
        self._data = defaultdict(lambda: {'step_size': 0.0, 'state': 'stop', 'profit': 0.0, 'orders': []})
        self._lock = Lock()

    async def add_symbols_and_orders_batch(self, batch_data: list):
        async with self._lock:
            for symbol, orders in batch_data:
                self.symbols.append(symbol.name)
                self._data[symbol.name]['step_size'] = symbol.step_size
                self._data[symbol.name]['state'] = symbol.state
                self._data[symbol.name]['profit'] = symbol.profit
                self._data[symbol.name]['orders'] = orders

    async def update_state(self, symbol: str, state: str):
        async with self._lock:
            self._data[symbol]['state'] = state

    async def get_state(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('state')

    async def update_order(self, symbol: str, data: dict):
        async with self._lock:
            self._data[symbol]['orders'].append(data)

    async def add_symbol(self, symbol: str, step_size: float):
        async with self._lock:
            self.symbols.append(symbol)
            self._data[symbol] = {'step_size': step_size, 'state': 'stop', 'profit': 0.0, 'orders': []}

    async def delete_symbol(self, symbol: str):
        async with self._lock:
            if symbol in self.symbols:
                self.symbols.remove(symbol)
                del self._data[symbol]

    async def get_step_size(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('step_size')

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('orders')

    async def update_profit(self, symbol: str, profit: float):
        async with self._lock:
            self._data[symbol]['profit'] += profit

    async def get_profit(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('profit')

    async def get_summary_profit(self):
        async with self._lock:
            return sum(symbol_data['profit'] for _, symbol_data in self._data.items())

    async def get_last_order(self, symbol: str):
        async with self._lock:
            orders = self._data.get(symbol).get('orders')
            return orders[-1] if orders else None

    async def del_orders(self, symbol: str, open_time: datetime = None):  # Удаления одного / или всех ордеров в списке
        async with self._lock:
            if orders := self._data.get(symbol).get('orders'):
                orders.pop() if open_time else orders.clear()

    async def get_summary_executed_qty(self, symbol: str):  # Метод для подсчета объема исполненных ордеров
        async with self._lock:
            orders = self._data.get(symbol).get('orders')
            return sum(order['executed_qty'] for order in orders) if orders else 0.0

    async def get_total_cost_with_fee(self, symbol: str):  # Метод для подсчета общей стоимости с комиссией
        async with self._lock:
            orders = self._data.get(symbol).get('orders')
            return sum(order['cost_with_fee'] for order in orders) if orders else 0.0
