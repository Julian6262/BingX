from asyncio import Lock

from aiohttp import ClientSession, ClientConnectorDNSError
from websockets import ConnectionClosed
from websockets.asyncio.client import connect

from gzip import GzipFile
from io import BytesIO
from json import dumps

import time
import hmac
from hashlib import sha256
from json import loads

from common.config import Config

HEADERS = {'X-BX-APIKEY': Config.API_KEY}


# -----------------------------------------------------------------------------
async def send_request(method, session, endpoint, params):
    params_str = await parse_param(params)
    sign = hmac.new(Config.SECRET_KEY.encode("utf-8"), params_str.encode("utf-8"), digestmod=sha256).hexdigest()
    url = f"{Config.BASE_URL}{endpoint}?{params_str}&signature={sign}"

    try:
        async with (session.get(url) if method == "GET" else session.post(url)) as response:
            if response.status == 200:
                data = await response.text()
                return loads(data)
            else:
                print(f"Ошибка : {response.status} для {params['symbol']}")
                return False

    except ClientConnectorDNSError:
        print('Ошибка соединения с сетью(request)')
        return False


async def parse_param(params):
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    if params_str != "":
        return params_str + "&timestamp=" + str(int(time.time() * 1000))
    else:
        return params_str + "timestamp=" + str(int(time.time() * 1000))


class WebSocketData:  # Класс для работы с текущими ценами из websockets
    def __init__(self):
        self.price = {}
        self._lock = Lock()

    async def update_price(self, symbol, price):
        async with self._lock:
            self.price[symbol] = price

    async def get_price(self, symbol):
        async with self._lock:
            return self.price.get(symbol.upper(), False)


ws_price = WebSocketData()


# class TotalCost:
#     def __init__(self):
#         self.price = {}
#         self._lock = Lock()
#
#     async def update_price(self, symbol, price):
#         async with self._lock:
#             self.price[symbol] = price
#
#     async def get_price(self, symbol):
#         async with self._lock:
#             return self.price.get(symbol, False)


# -----------------------------------------------------------------------------


async def place_order(symbol, side, quantity=0, executed_qty=0):
    method = "POST"
    endpoint = '/openApi/spot/v1/trade/order'
    params = {
        "symbol": f'{symbol.upper()}-USDT',
        "type": "MARKET",
        "side": side,
        "quantity": executed_qty,
        "quoteOrderQty": quantity,
    }

    async with ClientSession(headers=HEADERS) as session:
        return await send_request(method, session, endpoint, params)


async def price_updates_ws(symbol):
    channel = {"id": "1", "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}

    async for websocket in connect(Config.URL_WS):
        try:
            await websocket.send(dumps(channel))
            async for message in websocket:
                compressed_data = GzipFile(fileobj=BytesIO(message), mode='rb')
                decompressed_data = compressed_data.read()
                utf8_data = loads(decompressed_data.decode('utf-8'))
                if 'data' in utf8_data:
                    price = float(utf8_data["data"]["c"])
                    await ws_price.update_price(symbol, price)

        except ConnectionClosed:
            print('Ошибка соединения с сетью(WS)')
