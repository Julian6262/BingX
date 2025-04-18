from asyncio import Lock, sleep
from decimal import Decimal
from gzip import decompress, BadGzipFile
from aiohttp import ClientSession, ClientConnectorError, WSServerHandshakeError
from websockets import ConnectionClosed
from logging import error
from time import time
from hmac import new as hmac_new
from hashlib import sha256
from json import loads, JSONDecodeError

from common.config import config


# -----------------------------------------------------------------------------
async def send_request(method: str, session: ClientSession, endpoint: str, params: dict):
    params['timestamp'] = int(time() * 1000)
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    sign = hmac_new(config.SECRET_KEY.encode(), params_str.encode(), sha256).hexdigest()
    url = f"{config.BASE_URL}{endpoint}?{params_str}&signature={sign}"

    try:
        async with session.request(method, url) as response:
            if response.status == 200:
                if response.content_type == 'application/json':
                    data = await response.json()
                elif response.content_type == 'text/plain':
                    data = loads(await response.text())
                else:
                    error(f"Неожиданный Content-Type: {response.content_type}")
                    return None

                print(data)
                return data

            else:
                error(f"Ошибка {response.status} для {params.get('symbol')}: {await response.text()}")
                return None

    except ClientConnectorError as e:
        error(f'Ошибка соединения с сетью (request): {e}')
        return None

    except JSONDecodeError as e:  # обработка ошибки декодирования json
        error(f"Ошибка декодирования JSON: {e}")
        return None


class AccountBalance:  # Класс для работы с данными счета
    def __init__(self):
        self.balance = {}
        self.listen_key = None
        self._lock = Lock()

    async def update_balance_batch(self, batch_data: list):
        async with self._lock:
            for data in batch_data:
                self.balance[data['a']] = float(data['wb'])

    async def get_balance(self, symbol: str):
        async with self._lock:
            return self.balance.get(symbol, 0.0)

    async def add_listen_key(self, listen_key: str):
        async with self._lock:
            self.listen_key = listen_key

    async def get_listen_key(self):
        async with self._lock:
            return self.listen_key


class WebSocketData:  # Класс для работы с ценами в реальном времени из websockets
    def __init__(self):
        self.price = {}
        self._lock = Lock()

    async def update_price(self, symbol: str, price: float):
        async with self._lock:
            self.price[symbol] = price

    async def get_price(self, symbol: str):
        async with self._lock:
            return self.price.get(symbol)


class OrderBook:  # Класс для работы с ордерами в реальном времени
    def __init__(self):
        self.symbols = []
        self.step_size = {}
        self.orders = {}  # Словарь для хранения ордеров по символам
        self._lock = Lock()

    async def add_symbols_and_orders_batch(self, batch_data: list):
        async with self._lock:
            for symbol, step_size, data in batch_data:
                self.symbols.append(symbol)
                self.step_size[symbol] = step_size
                self.orders[symbol] = data

    async def update_order(self, symbol: str, data: dict):
        async with self._lock:
            if data:
                self.orders[symbol].append(data)

    async def add_symbol(self, symbol: str, step_size: float):
        async with self._lock:
            self.symbols.append(symbol)
            self.step_size[symbol] = step_size

    async def delete_symbol(self, symbol: str):
        async with self._lock:
            if symbol in self.symbols:
                self.symbols.remove(symbol)
                del self.step_size[symbol]

    async def get_step_size(self, symbol: str):
        async with self._lock:
            return self.step_size.get(symbol)

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self.orders.get(symbol)

    async def get_last_order(self, symbol: str):
        async with self._lock:
            orders = self.orders.get(symbol)
            return orders[-1] if orders else None

    async def delete_last_order(self, symbol: str):
        async with self._lock:
            if orders := self.orders.get(symbol):
                orders.pop()

    async def get_summary_executed_qty(self, symbol: str):  # Метод для подсчета объема исполненных ордеров
        async with self._lock:
            orders = self.orders.get(symbol)
            return sum(order['executed_qty'] for order in orders) if orders else 0.0

    async def delete_all_orders(self, symbol: str):  # Метод для удаления всех ордеров при усреднении
        async with self._lock:
            if orders := self.orders.get(symbol):
                orders.clear()

    async def get_total_cost_with_fee(self, symbol: str):  # Метод для подсчета общей стоимости с комиссией
        async with self._lock:
            orders = self.orders.get(symbol)
            return sum(order['cost_with_fee'] for order in orders) if orders else 0.0


ws_price = WebSocketData()
orders_book = OrderBook()
account_balance = AccountBalance()


# -----------------------------------------------------------------------------

async def place_order(symbol: str, session: ClientSession, side: str, executed_qty: float | Decimal):
    endpoint = '/openApi/spot/v1/trade/order'
    params = {"symbol": f'{symbol}-USDT', "type": "MARKET", "side": side, "quantity": executed_qty}

    return await send_request("POST", session, endpoint, params)


async def get_symbol_info(symbol: str, session: ClientSession):
    endpoint = '/openApi/spot/v1/common/symbols'
    params = {"symbol": f'{symbol}-USDT'}

    return await send_request("GET", session, endpoint, params)


async def manage_listen_key(session: ClientSession):
    endpoint = '/openApi/user/auth/userDataStream'

    if listen_key := await send_request("POST", session, endpoint, {}):
        await account_balance.add_listen_key(listen_key['listenKey'])

        while True:
            await sleep(1200)
            await send_request("PUT", session, endpoint, {"listenKey": listen_key['listenKey']})

    else:
        error('Ошибка получения listen_key')


async def track_be_level(symbol: str):
    while not await ws_price.get_price(symbol):
        await sleep(1 / 2)  # Задержка перед попыткой получения цены

    while True:
        actual_price = await ws_price.get_price(symbol)
        total_cost_with_fee = await orders_book.get_total_cost_with_fee(symbol)
        summary_executed = await orders_book.get_summary_executed_qty(symbol)
        be_level_with_fee = total_cost_with_fee / summary_executed

        print(
            f'total_cost_with_fee: {total_cost_with_fee}\n'
            f'summary_executed: {summary_executed}\n'
            f"Текущая цена {symbol}: {actual_price}\n"
            f'be_level_with_fee: {be_level_with_fee}\n'
            f'actual_price * summary_executed: {actual_price * summary_executed}\n'
            f'actual_price * summary_executed - total_cost_with_fee: {actual_price * summary_executed - total_cost_with_fee}\n'
        )

        await sleep(60)


async def price_updates_ws(seconds: int, symbol: str, session: ClientSession):
    channel = {"id": '1', "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}
    await sleep(seconds / 2)  # Задержка перед запуском функции, иначе ошибка API

    try:
        async with session.ws_connect(config.URL_WS) as ws:
            print(f'b_{symbol}')
            await ws.send_json(channel)

            async for message in ws:
                try:
                    if 'data' in (data := loads(decompress(message.data).decode())):
                        await ws_price.update_price(symbol, float(data["data"]["c"]))

                except (BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except (ConnectionClosed, WSServerHandshakeError) as e:
        error(f"Ошибка соединения WebSocket: {symbol}, {e}")


async def account_updates_ws(session: ClientSession):
    while not (listen_key := await account_balance.get_listen_key()):
        await sleep(1 / 2)  # Задержка перед попыткой получения ключа

    channel = {"id": "1", "reqType": "sub", "dataType": "ACCOUNT_UPDATE"}
    url = f"{config.URL_WS}?listenKey={listen_key}"

    try:
        async with session.ws_connect(url) as ws:
            await ws.send_json(channel)

            async for message in ws:
                try:
                    if 'e' in (data := loads(decompress(message.data).decode())):
                        print(data['a']['B'])
                        await account_balance.update_balance_batch(data['a']['B'])

                except (BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except (ConnectionClosed, WSServerHandshakeError) as e:
        error(f"Ошибка соединения WebSocket:, {e}")
