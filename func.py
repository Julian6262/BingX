import time
import hmac
from hashlib import sha256
from json import loads

from aiohttp import ClientConnectorDNSError


async def send_request(method, session, endpoint, base_url, secret_key, params, quantity=None):
    url = await make_url(base_url, endpoint, secret_key, params)

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


async def make_url(base_url, endpoint, secret_key, params):
    params_str = await parse_param(params)
    signature = hmac.new(secret_key.encode("utf-8"), params_str.encode("utf-8"), digestmod=sha256).hexdigest()
    url = f"{base_url}{endpoint}?{params_str}&signature={signature}"
    return url


async def parse_param(params):
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    if params_str != "":
        return params_str + "&timestamp=" + str(int(time.time() * 1000))
    else:
        return params_str + "timestamp=" + str(int(time.time() * 1000))
