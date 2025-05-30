from asyncio import Lock, CancelledError
from collections import defaultdict
from datetime import datetime


class ConfigManager:
    def __init__(self):
        self.symbols = []
        self._data = defaultdict(dict)
        self._lock = Lock()

    async def update_config(self, batch_data: dict):
        async with self._lock:
            for data in batch_data:
                self.symbols.append(data.symbol_name)
                self._data[data.symbol_name]['grid_size'] = data.grid_size
                self._data[data.symbol_name]['lot'] = data.lot

    async def get_config(self, symbol: str, field: str):
        async with self._lock:
            return self._data.get(symbol).get(field)


class ProfitManager:  # Класс для работы с данными профита
    def __init__(self):
        self._data = {}
        self._lock = Lock()

    async def update_data(self, symbol: str, data: dict):
        async with self._lock:
            self._data[symbol] = data

    async def get_data(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol)


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
                'pause_after_sell': False,
                'b_s_trigger': 'new',
                # 'ts': False,
                # 'cross_target_ts_price': False,
                # 'sell_state': False,
                # 'target_ts_price': 0.0,
                # 'stop_ts_price': 0.0,
                'profit': 0.0,
                'lot': 0.0,
                'orders': []}

    async def add_symbols_and_orders(self, batch_data: list):
        async with self._lock:
            for symbol, orders in batch_data:
                self.symbols.append(symbol.name)
                self._data[symbol.name]['step_size'] = symbol.step_size
                self._data[symbol.name]['state'] = symbol.state
                self._data[symbol.name]['profit'] = symbol.profit
                self._data[symbol.name]['orders'] = orders

    async def set_b_s_trigger(self, symbol: str, trigger: str):
        async with self._lock:
            self._data[symbol]['b_s_trigger'] = trigger

    async def get_b_s_trigger(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('b_s_trigger')

    async def set_pause(self, symbol: str, state: bool):
        async with self._lock:
            self._data[symbol]['pause_after_sell'] = state

    async def get_pause(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('pause_after_sell')

    # async def set_ts_state(self, symbol: str, state: bool):
    #     async with self._lock:
    #         self._data[symbol]['ts'] = state
    #
    # async def get_ts_state(self, symbol: str):
    #     async with self._lock:
    #         return self._data.get(symbol).get('ts')

    # async def set_sell_state(self, symbol: str, state: bool):
    #     async with self._lock:
    #         self._data[symbol]['sell_state'] = state
    #
    # async def get_sell_state(self, symbol: str):
    #     async with self._lock:
    #         return self._data.get(symbol).get('sell_state')

    # async def set_target_ts_price(self, symbol: str, target_price: float):
    #     async with self._lock:
    #         self._data[symbol]['target_ts_price'] = target_price

    # async def get_target_ts_price(self, symbol: str):
    #     async with self._lock:
    #         return self._data.get(symbol).get('target_ts_price')
    #
    # async def set_stop_ts_price(self, symbol: str, stop_price: float):
    #     async with self._lock:
    #         self._data[symbol]['stop_ts_price'] = stop_price
    #
    # async def get_stop_ts_price(self, symbol: str):
    #     async with self._lock:
    #         return self._data.get(symbol).get('stop_ts_price')

    # async def set_cross_target_ts(self, symbol: str, cross_target_ts: bool):
    #     async with self._lock:
    #         self._data[symbol]['cross_target_ts_price'] = cross_target_ts
    #
    # async def get_cross_target_ts(self, symbol: str):
    #     async with self._lock:
    #         return self._data.get(symbol).get('cross_target_ts_price')

    async def set_lot(self, symbol: str, lot: float):
        async with self._lock:
            self._data[symbol]['lot'] = lot

    async def get_lot(self, symbol: str):
        async with self._lock:
            return self._data.get(symbol).get('lot')

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

    async def del_orders(self, symbol: str, open_times: list[datetime] = None):
        async with self._lock:
            if open_times:
                if orders := self._data.get(symbol).get('orders'):
                    self._data[symbol]['orders'] = orders[:-len(open_times)]
            else:
                self._data.get(symbol).get('orders', []).clear()

    async def get_summary(self, symbol: str, key: str):
        async with self._lock:
            orders = self._data.get(symbol).get('orders')
            return sum(order[key] for order in orders) if orders else 0.0
