import time
import hmac
from hashlib import sha256


async def parse_param(params):
    params_str = "&".join([f"{x}={params[x]}" for x in sorted(params)])
    if params_str != "":
        return params_str + "&timestamp=" + str(int(time.time() * 1000))
    else:
        return params_str + "timestamp=" + str(int(time.time() * 1000))


async def make_url(base_url, endpoint, secret_key, params):
    params_str = await parse_param(params)
    signature = hmac.new(secret_key.encode("utf-8"), params_str.encode("utf-8"), digestmod=sha256).hexdigest()
    url = f"{base_url}{endpoint}?{params_str}&signature={signature}"

    return url
