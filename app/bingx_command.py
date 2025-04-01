from asyncio import Lock

from aiohttp import ClientSession, ClientConnectorDNSError
from websockets import ConnectionClosed
from websockets.asyncio.client import connect

from gzip import GzipFile
from io import BytesIO
from json import dumps, loads

import time
import hmac
from hashlib import sha256
from json import loads

from app.config import Config

headers = {'X-BX-APIKEY': Config.API_KEY}


# -----------------------------------------------------------------------------
async def send_request(method, session, endpoint, params, quantity=None):
    params_str = await parse_param(params)
    sign = hmac.new(Config.SECRET_KEY.encode("utf-8"), params_str.encode("utf-8"), digestmod=sha256).hexdigest()
    url = f"{Config.BASE_URL}{endpoint}?{params_str}&signature={sign}"

    try:
        async with (session.get(url) if method == "GET" else session.post(url)) as response:
            if response.status == 200:
                data = await response.text()
                json_data = loads(data)
                return json_data
            else:
                print(f"Ошибка : {response.status} для {params['symbol']}")
                return None
    except ClientConnectorDNSError:
        print('Ошибка соединения с сетью')


async def parse_param(params):
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    if params_str != "":
        return params_str + "&timestamp=" + str(int(time.time() * 1000))
    else:
        return params_str + "timestamp=" + str(int(time.time() * 1000))


class WebSocketData:
    def __init__(self):
        self.last_value = None
        self._lock = Lock()

    async def update_value(self, value):
        async with self._lock:
            self.last_value = value

    async def get_value(self):
        async with self._lock:
            return self.last_value


ws_price = WebSocketData()


# -----------------------------------------------------------------------------


async def place_order(symbol, quantity):
    method = "POST"
    endpoint = '/openApi/spot/v1/trade/order'
    params = {
        "symbol": symbol,
        "type": "MARKET",
        "side": "BUY",
        # "quantity": quantity,
        "quoteOrderQty": quantity
    }

    async with ClientSession(headers=headers) as session:
        response = await send_request(method, session, endpoint, params, quantity)
        if response:
            print(f"{symbol}: {response}")


async def price_updates_ws(symbol):
    channel = {"id": "1", "reqType": "sub", "dataType": f"{symbol}@lastPrice"}

    async for websocket in connect(Config.URL_WS):
        try:
            await websocket.send(dumps(channel))
            async for message in websocket:
                compressed_data = GzipFile(fileobj=BytesIO(message), mode='rb')
                decompressed_data = compressed_data.read()
                utf8_data = loads(decompressed_data.decode('utf-8'))
                if 'data' in utf8_data:
                    price = float(utf8_data["data"]["c"])
                    await ws_price.update_value(price)

                    print(price)

        except ConnectionClosed:
            print('Ошибка соединения с сетью')
