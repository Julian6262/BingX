import gzip
import logging
from asyncio import Lock
from collections import defaultdict, deque

from aiohttp import ClientSession, ClientConnectorError

import time
import hmac
from hashlib import sha256
from json import loads, JSONDecodeError

from websockets import ConnectionClosed

from common.config import Config

HEADERS = {'X-BX-APIKEY': Config.API_KEY}


# -----------------------------------------------------------------------------
async def send_request(method: str, session: ClientSession, endpoint: str, params: dict):
    params['timestamp'] = int(time.time() * 1000)
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    sign = hmac.new(Config.SECRET_KEY.encode(), params_str.encode(), sha256).hexdigest()
    url = f"{Config.BASE_URL}{endpoint}?{params_str}&signature={sign}"

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
        self.orders = defaultdict(deque)  # Словарь для хранения ордеров по символам
        self._lock = Lock()

    async def update_orders(self, symbol, data: dict):
        async with self._lock:
            self.orders[symbol].append(
                {"executed_qty": data['executed_qty'], 'executed_qty_real': data['executed_qty_real'],
                 "cost": data['cost'], "commission": data['commission'],
                 "cost_with_commission": data['cost_with_commission'], "open_time": data['open_time']})

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self.orders.get(symbol, [])  # Возвращаем пустой список, если symbol нет

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

    async def get_total_cost(self, symbol: str):  # Метод для подсчета общей стоимости
        async with self._lock:
            orders = self.orders.get(symbol, ())
            return sum(order['price'] * order['executed_qty'] for order in orders)


ws_price = WebSocketData()
orders_book = OrderBook()


# -----------------------------------------------------------------------------


async def place_order(symbol: str, side: str, quantity: int = 0, executed_qty: float = 0):
    endpoint = '/openApi/spot/v1/trade/order'
    params = {
        "symbol": f'{symbol}-USDT',
        "type": "MARKET",
        "side": side,
        "quantity": executed_qty,
        "quoteOrderQty": quantity,
    }

    async with ClientSession(headers=HEADERS) as session:
        return await send_request("POST", session, endpoint, params)


async def price_updates_ws(session: ClientSession, symbol: str):
    channel = {"id": "1", "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}

    try:
        async with session.ws_connect(Config.URL_WS) as ws:
            await ws.send_json(channel)

            async for message in ws:
                try:
                    data = loads(gzip.decompress(message.data).decode())
                    if 'data' in data:
                        price = float(data["data"]["c"])
                        await ws_price.update_price(symbol, price)

                except (gzip.BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    logging.error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except ConnectionClosed as e:
        logging.error(f"Ошибка соединения WebSocket: {e}")
