from time import time
from hmac import new as hmac_new
from hashlib import sha256
from json import loads, JSONDecodeError

from aiohttp import ClientSession, ClientConnectorError

from common.config import config


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
                    return None, f"Неожиданный Content-Type send_request: {response.content_type}"

                return data, "OK"

            else:
                return None, f"Ошибка {response.status} для {params.get('symbol')}: {await response.text()}"

    except ClientConnectorError as e:
        return None, f'Ошибка соединения с сетью (send_request): {e}'

    except JSONDecodeError as e:
        return None, f"Ошибка декодирования send_request JSON: {e}"

    except Exception as e:
        return None, f"Ошибка при выполнении запроса send_request: {e}"
