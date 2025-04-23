from asyncio import Lock, CancelledError
from collections import defaultdict


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
        self._price = {}
        self._lock = Lock()

    async def update_price(self, symbol: str, price: float):
        async with self._lock:
            self._price[symbol] = price

    async def get_price(self, symbol: str):
        async with self._lock:
            return self._price.get(symbol)


class SymbolOrderManager:  # Класс для работы с ордерами в реальном времени
    def __init__(self):
        self.symbols = []
        self._sell_order_flag = {}
        self._step_size = {}
        self._orders = defaultdict(list)  # Словарь для хранения ордеров по символам
        self._lock = Lock()

    async def add_symbols_and_orders_batch(self, batch_data: list):
        async with self._lock:
            for symbol, step_size, data in batch_data:
                self.symbols.append(symbol)
                self._step_size[symbol] = step_size
                self._orders[symbol] = data

    async def set_sell_order_flag(self, symbol: str, flag: bool):
        async with self._lock:
            self._sell_order_flag[symbol] = flag

    async def get_sell_order_flag(self, symbol: str):
        async with self._lock:
            return self._sell_order_flag.get(symbol)

    async def update_order(self, symbol: str, data: dict):
        async with self._lock:
            self._orders[symbol].append(data)

    async def add_symbol(self, symbol: str, step_size: float):
        async with self._lock:
            self.symbols.append(symbol)
            self._step_size[symbol] = step_size

    async def delete_symbol(self, symbol: str):
        async with self._lock:
            if symbol in self.symbols:
                self.symbols.remove(symbol)
                del self._step_size[symbol]

    async def get_step_size(self, symbol: str):
        async with self._lock:
            return self._step_size.get(symbol)

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self._orders.get(symbol)

    async def get_last_order(self, symbol: str):
        async with self._lock:
            orders = self._orders.get(symbol)
            return orders[-1] if orders else None

    async def delete_last_order(self, symbol: str):
        async with self._lock:
            if orders := self._orders.get(symbol):
                orders.pop()

    async def get_summary_executed_qty(self, symbol: str):  # Метод для подсчета объема исполненных ордеров
        async with self._lock:
            orders = self._orders.get(symbol)
            return sum(order['executed_qty'] for order in orders) if orders else 0.0

    async def delete_all_orders(self, symbol: str):  # Метод для удаления всех ордеров при усреднении
        async with self._lock:
            if orders := self._orders.get(symbol):
                orders.clear()

    async def get_total_cost_with_fee(self, symbol: str):  # Метод для подсчета общей стоимости с комиссией
        async with self._lock:
            orders = self._orders.get(symbol)
            return sum(order['cost_with_fee'] for order in orders) if orders else 0.0
