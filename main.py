import asyncio
from aiohttp import ClientSession
from websockets import ConnectionClosed
from websockets.asyncio.client import connect

from gzip import GzipFile
from io import BytesIO
from json import dumps, loads
from os import getenv
from dotenv import load_dotenv, find_dotenv

from func import send_request

load_dotenv(find_dotenv())

BASE_URL = getenv('BASE_URL')
URL_WS = getenv('URL_WS')
SECRET_KEY = getenv('SECRET_KEY')
HEADERS = {'X-BX-APIKEY': getenv('API_KEY')}


async def price_updates(symbol, interval_seconds):
    method = "GET"
    endpoint = '/openApi/spot/v1/ticker/price'
    params = {
        "symbol": symbol
    }

    async with ClientSession(headers=HEADERS) as session:
        while True:
            data = await send_request(method, session, endpoint, BASE_URL, SECRET_KEY, params)
            if data:
                price = float(data["data"][0]["trades"][0]["price"])
                print(f"{symbol}: {price}")
            await asyncio.sleep(interval_seconds)


async def get_symbol_info(symbol):
    method = "GET"
    endpoint = '/openApi/spot/v1/common/symbols'
    params = {
        "symbol": symbol
    }

    async with ClientSession(headers=HEADERS) as session:
        price = await send_request(method, session, endpoint, BASE_URL, SECRET_KEY, params)
        if price:
            print(f"{symbol}: {price}")


async def place_order(symbol, quantity):    #  проверить без сети
    method = "POST"
    endpoint = '/openApi/spot/v1/trade/order'
    params = {
        "symbol": symbol,
        "type": "MARKET",
        "side": "BUY",
        "quantity": quantity,
    }

    async with ClientSession(headers=HEADERS) as session:
        price = await send_request(method, session, endpoint, BASE_URL, SECRET_KEY, quantity, params)
        if price:
            print(f"{symbol}: {price}")


async def price_updates_ws(symbol):
    channel = {"id": "1", "reqType": "sub", "dataType": f"{symbol}@lastPrice"}

    async for websocket in connect(URL_WS):
        try:
            await websocket.send(dumps(channel))
            async for message in websocket:
                compressed_data = GzipFile(fileobj=BytesIO(message), mode='rb')
                decompressed_data = compressed_data.read()
                utf8_data = loads(decompressed_data.decode('utf-8'))
                if 'data' in utf8_data:
                    price = float(utf8_data["data"]["c"])
                    print(price)
        except ConnectionClosed:
            print('Ошибка соединения с сетью')
            continue


async def main():
    tasks = [
        # price_updates("BTC_USDT", 15),
        # price_updates("ETH_USDT", 10),
        # get_symbol_info("SOL-USDT"),
        price_updates_ws("BTC-USDT")
        # place_order('BTC-USDT', 0.000011)
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
