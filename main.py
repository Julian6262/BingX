import asyncio
from aiohttp import ClientSession
from websockets.asyncio.client import connect

from gzip import GzipFile
from io import BytesIO
from json import dumps, loads
from os import getenv
from dotenv import load_dotenv, find_dotenv

from func import make_url

load_dotenv(find_dotenv())

BASE_URL = getenv('BASE_URL')
URL_WS = getenv('URL_WS')
SECRET_KEY = getenv('SECRET_KEY')
API_KEY = getenv('API_KEY')

headers = {'X-BX-APIKEY': API_KEY}


async def get_price(session, symbol):  # получить цену спота через http
    endpoint = '/openApi/spot/v1/ticker/price'
    params = {
        "symbol": symbol
    }
    url = await make_url(BASE_URL, endpoint, SECRET_KEY, params)

    async with session.get(url) as response:
        if response.status == 200:
            data = await response.json()
            return float(data["data"][0]["trades"][0]["price"])
        else:
            print(f"Error: {response.status} for {symbol}")
            return None


async def price_updates(symbol, interval_seconds):
    async with ClientSession(headers=headers) as session:
        while True:
            price = await get_price(session, symbol)
            if price:
                print(f"{symbol}: {price}")
            await asyncio.sleep(interval_seconds)


async def ticket(symbol):
    channel = {"id": "1", "reqType": "sub", "dataType": f"{symbol}@lastPrice"}

    async with connect(URL_WS) as websocket:
        await websocket.send(dumps(channel))
        async for message in websocket:
            compressed_data = GzipFile(fileobj=BytesIO(message), mode='rb')
            decompressed_data = compressed_data.read()
            utf8_data = loads(decompressed_data.decode('utf-8'))
            if 'data' in utf8_data:
                price = float(utf8_data["data"]["c"])
                print(price)


async def main():
    tasks = [
        # price_updates("BTC_USDT", 15),
        # price_updates("ETH_USDT", 10),
        ticket("BTC-USDT")
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
