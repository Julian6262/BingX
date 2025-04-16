import gzip
import logging
from asyncio import Lock, sleep
from collections import defaultdict

from aiohttp import ClientSession, ClientConnectorError, WSServerHandshakeError

import time
import hmac
from hashlib import sha256
from json import loads, JSONDecodeError

from websockets import ConnectionClosed

from common.config import config


# -----------------------------------------------------------------------------
async def send_request(method: str, session: ClientSession, endpoint: str, params: dict):
    params['timestamp'] = int(time.time() * 1000)
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    sign = hmac.new(config.SECRET_KEY.encode(), params_str.encode(), sha256).hexdigest()
    url = f"{config.BASE_URL}{endpoint}?{params_str}&signature={sign}"

    try:
        async with session.request(method, url) as response:
            if response.status == 200:
                return loads(await response.text())
            else:
                logging.error(f"Ошибка {response.status} для {params.get('symbol')}: {await response.text()}")
                return None

    except ClientConnectorError as e:
        logging.error(f'Ошибка соединения с сетью (request): {e}')
        return None
    except JSONDecodeError as e:  # обработка ошибки декодирования json
        logging.error(f"Ошибка декодирования JSON: {e}")
        return None


class AccountBalance:  # Класс для работы с данными счета
    def __init__(self):
        self.balance = {}
        self._lock = Lock()

    async def update_balance_batch(self, batch_data: list):
        async with self._lock:
            for data in batch_data:
                self.balance[data['asset']] = float(data['free'])

    async def get_balance(self, symbol: str):
        async with self._lock:
            return self.balance.get(symbol)


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
        self.step_size = {}
        self.orders = defaultdict(list)  # Словарь для хранения ордеров по символам
        self._lock = Lock()

    async def update_orders_batch(self, batch_data: list):
        async with self._lock:
            for symbol, step_size, data in batch_data:
                if step_size:
                    self.step_size[symbol] = step_size
                if data:
                    self.orders[symbol].append(data)

    async def update_order(self, symbol: str, data: dict):
        async with self._lock:
            if data:
                self.orders[symbol].append(data)

    async def get_step_size(self, symbol: str):
        async with self._lock:
            return self.step_size.get(symbol)

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self.step_size.get(symbol), self.orders.get(symbol)

    async def get_last_order(self, symbol: str):
        async with self._lock:
            orders = self.orders.get(symbol)
            return orders[-1] if orders else None

    async def delete_last_order(self, symbol: str):
        async with self._lock:
            orders = self.orders.get(symbol)
            if orders:
                orders.pop()

    # async def delete_all_orders(self, symbol: str):  # Метод для удаления всех ордеров при усреднении
    #     async with self._lock:
    #         orders = self.orders.get(symbol)

    # async def get_total_cost(self, symbol: str):  # Метод для подсчета общей стоимости
    #     async with self._lock:
    #         orders = self.orders.get(symbol, ())
    #         return sum(order['price'] * order['executed_qty'] for order in orders)


ws_price = WebSocketData()
orders_book = OrderBook()
account_balance = AccountBalance()


# -----------------------------------------------------------------------------


async def place_order(symbol: str, session: ClientSession, side: str, executed_qty: float):
    endpoint = '/openApi/spot/v1/trade/order'
    params = {
        "symbol": f'{symbol}-USDT',
        "type": "MARKET",
        "side": side,
        "quantity": executed_qty,
    }

    return await send_request("POST", session, endpoint, params)


async def get_symbol_info(symbol: str, session: ClientSession):
    endpoint = '/openApi/spot/v1/common/symbols'
    params = {"symbol": f'{symbol}-USDT'}

    return await send_request("GET", session, endpoint, params)


async def price_updates_ws(seconds: int, symbol: str, session: ClientSession):
    channel = {"id": '1', "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}
    await sleep(seconds / 2)  # Задержка перед отправкой запроса

    try:
        async with session.ws_connect(config.URL_WS) as ws:
            print(f'b_{symbol}')
            await ws.send_json(channel)

            async for message in ws:
                try:
                    if 'data' in (data := loads(gzip.decompress(message.data).decode())):
                        await ws_price.update_price(symbol, float(data["data"]["c"]))

                except (gzip.BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    logging.error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except (ConnectionClosed, WSServerHandshakeError) as e:
        logging.error(f"Ошибка соединения WebSocket: {symbol}, {e}")


async def load_account_balances(session: ClientSession):
    endpoint = '/openApi/spot/v1/account/balance'
    params = {}

    if 'data' in (data := await send_request("GET", session, endpoint, params)):
        await account_balance.update_balance_batch(data["data"]["balances"])
    else:
        logging.error(f"Ошибка загрузки баланса: {data}")
