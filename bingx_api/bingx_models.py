from asyncio import Lock, CancelledError
from collections import defaultdict


class ConfigManager:
    def __init__(self):
        self.symbols = []
        self._data = defaultdict(dict)
        self._lock = Lock()

    async def load_config(self, batch_data: dict):
        async with self._lock:
            for data in batch_data:
                self.symbols.append(data.symbol_name)
                self._data[data.symbol_name]['grid_size'] = data.grid_size
                # self._data[data.symbol_name]['lot'] = data.lot

    async def set_data(self, symbol: str, key: str, value: float | bool):
        async with self._lock:
            self._data[symbol][key] = value

    async def get_data(self, symbol: str, key: str):
        async with self._lock:
            return self._data.get(symbol).get(key)


class AccountManager:  # Класс для работы с данными счета
    def __init__(self):
        self._balance = {}
        self._usdt_block = 'unblock'
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

    async def set_usdt_block(self, state: str):
        async with self._lock:
            self._usdt_block = state

    async def get_usdt_block(self):
        async with self._lock:
            return self._usdt_block


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
        self._data = defaultdict(self._create_default_symbol_data)
        self._lock = Lock()

    @staticmethod
    def _create_default_symbol_data(step_size: float = 0.0):
        return {'step_size': step_size,
                'state': 'stop',
                'b_s_trigger': 'new',
                'profit': 0.0,
                'orders': []}

    async def add_symbols_and_orders(self, batch_data: list):
        async with self._lock:
            for symbol, orders in batch_data:
                self.symbols.append(symbol.name)
                self._data[symbol.name].update({
                    'step_size': symbol.step_size,
                    'state': symbol.state,
                    'profit': symbol.profit,
                    'orders': orders
                })

    async def set_b_s_trigger(self, symbol: str, trigger: str):
        async with self._lock:
            self._data[symbol]['b_s_trigger'] = trigger

    async def get_b_s_trigger(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('b_s_trigger')

    async def set_state(self, symbol: str, state: str):
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
            self._data[symbol] = self._create_default_symbol_data(step_size=step_size)

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

    async def del_orders(self, symbol: str, orders_id: list = None):
        async with self._lock:
            if orders_id:
                if orders := self._data.get(symbol).get('orders'):
                    orders[:] = [order for order in orders if order['id'] not in orders_id]

            else:
                self._data.get(symbol).get('orders', []).clear()

    async def get_summary(self, symbol: str, key: str):
        async with self._lock:
            orders = self._data.get(symbol).get('orders')
            return sum(order[key] for order in orders) if orders else 0.0
