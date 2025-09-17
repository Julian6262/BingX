from asyncio import sleep, gather
from datetime import datetime
from decimal import Decimal
from gzip import decompress
from time import time
from hmac import new as hmac_new
from hashlib import sha256

from aiohttp import ClientSession, ClientConnectorError
from sqlalchemy.ext.asyncio import AsyncSession
from logging import getLogger
from json import loads, JSONDecodeError

from common.config import config
from common.func import get_decimal_places, add_task
from database.orm_query import add_order, update_profit, del_orders
from bingx_api.bingx_models import WebSocketPrice, SymbolOrderManager, AccountManager, TaskManager, ConfigManager

logger = getLogger('my_app')

ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()
task_manager = TaskManager()
config_manager = ConfigManager()


async def _send_request(method: str, session: ClientSession, endpoint: str, params: dict):
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


async def get_candlestick_data(symbol: str, session: ClientSession, interval: str, limit: int):
    endpoint = '/openApi/spot/v2/market/kline'
    params = {"symbol": f'{symbol}-USDT', "interval": interval, "limit": limit}

    return await _send_request("GET", session, endpoint, params)


async def place_order(symbol: str, session: ClientSession, side: str, executed_qty: float | Decimal):
    endpoint = '/openApi/spot/v1/trade/order'
    params = {"symbol": f'{symbol}-USDT', "type": "MARKET", "side": side, "quantity": executed_qty}

    return await _send_request("POST", session, endpoint, params)


async def get_symbol_info(symbol: str, session: ClientSession):
    endpoint = '/openApi/spot/v1/common/symbols'
    params = {"symbol": f'{symbol}-USDT'}

    return await _send_request("GET", session, endpoint, params)


async def manage_listen_key(http_session: ClientSession):
    endpoint = '/openApi/user/auth/userDataStream'

    listen_key, text = await _send_request("POST", http_session, endpoint, {})
    if listen_key is None:
        logger.error(f'Ошибка получения listen_key: {text}')
        return

    await account_manager.add_listen_key(listen_key['listenKey'])
    while True:
        await sleep(1200)
        await _send_request("PUT", http_session, endpoint, {"listenKey": listen_key['listenKey']})


async def _check_usdt_balance(lot: float):
    usdt_block = await account_manager.get_usdt_block()
    usdt_balance = await account_manager.get_balance('USDT')
    report = f'\nБаланс слишком маленький: {usdt_balance}\n'

    if usdt_balance > lot and usdt_block in ('block', 'continue_block'):
        logger.warning(f'\nБаланс пополнился: {usdt_balance}\n')
        await account_manager.set_usdt_block('unblock')
        return None

    elif usdt_block == 'block':
        await account_manager.set_usdt_block('continue_block')
        logger.warning(report)
        return report

    elif usdt_block == 'continue_block':
        return report


async def place_buy_order(symbol: str, price: float, session: AsyncSession, http_session: ClientSession):
    if not (lot := await config_manager.get_data(symbol, 'lot')):
        report = f'\nНе удалось получить лот для {symbol}\n'
        logger.warning(report)
        return report

    if report := await _check_usdt_balance(lot):
        return report

    # Округляем стоимость покупки до ближайшего кратного step_size
    execute_qty = round(lot / price, get_decimal_places(await so_manager.get_step_size(symbol)))

    data, text = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty)

    if not (order_data := data.get("data")):
        if data["code"] == 100202:  # Если ответ от биржи 100202, то нехватает средств, блокируем покупки
            await account_manager.set_usdt_block('block')

        report = f'\n\nОрдер НЕ открыт {symbol}: {text} {data}\n'
        logger.error(report)
        return report

    data_for_db = {
        'price': float(order_data['price']),
        'executed_qty': float(order_data['executedQty']),
        'cost': (cost := float(order_data['cummulativeQuoteQty'])),
        'cost_with_fee': cost * (1 + config.TAKER_MAKER),  # 0.4% комиссия(на бирже 0.1% + 0.1%)
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    report = f"""\n
              RSI_lot: {await config_manager.get_data(symbol, 'lot')}
              main_lot: {await config_manager.get_data(symbol, 'main_lot')}
              balance: {await account_manager.get_balance('USDT')}
              cummulativeQuoteQty: {order_data['cummulativeQuoteQty']}
              execute_qty: {order_data['executedQty']}
              Ордер открыт {symbol}  {str(data)}\n
"""

    order_id = await add_order(session, symbol, data_for_db)  # Добавить ордер в базу
    data_for_db['id'] = order_id  # Добавить id ордера в память
    await so_manager.update_order(symbol, data_for_db)  # Добавить ордер в память

    logger.info(report)
    return report


async def place_sell_order(symbol: str, summary_executed: float, total_cost_with_fee: float, session: AsyncSession,
                           http_session: ClientSession, orders_id: list = None):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    order_data, text = await place_order(symbol, http_session, 'SELL', summary_executed)
    if not (order_data_ok := order_data.get("data")):
        report = f'\n\nПродажа не прошла {symbol} summary_executed {summary_executed}: {text}\n{str(order_data)}\n\n'
        logger.error(report)
        return report

    _, price = await  ws_price.get_price(symbol)
    real_profit = float(order_data_ok["cummulativeQuoteQty"]) - total_cost_with_fee

    await gather(
        so_manager.update_profit(symbol, real_profit),
        so_manager.del_orders(symbol, orders_id),
    )

    await update_profit(symbol, session, real_profit)
    await del_orders(symbol, session, orders_id)
    await session.commit()

    report = (f'\n\nРасчет моей программы:\n'
              f'orders_id: {orders_id}\n'
              f'summary_executed: {summary_executed}\n'
              f'Сумма в бирже price * summary_executed: {price * summary_executed}\n'
              f'Сумма с комиссией total_cost_with_fee: {total_cost_with_fee}\n'
              f'Доход cummulativeQuoteQty: {real_profit}\n'
              f'\nОрдера закрыты {symbol}\n{str(order_data_ok)}\n')

    logger.info(report)
    return report


async def account_upd_ws(http_session: ClientSession):
    while not (listen_key := await account_manager.get_listen_key()):
        await sleep(0.3)  # Задержка перед попыткой получения ключа

    channel = {"id": "1", "reqType": "sub", "dataType": "ACCOUNT_UPDATE"}
    url = f"{config.URL_WS}?listenKey={listen_key}"

    while True:  # Цикл для повторного подключения
        try:
            async with http_session.ws_connect(url) as ws:
                print(f"WebSocket connected account_upd_ws")
                await ws.send_json(channel)

                async for message in ws:
                    try:
                        if 'e' in (data := loads(decompress(message.data).decode())):
                            await account_manager.update_balance_batch(data['a']['B'])
                            logger.info(f"Account_upd_ws: {data['a']}")

                    except Exception as e:
                        logger.error(f"Непредвиденная ошибка account_upd_ws: {e}, сообщение: {message.data}")

        except Exception as e:
            print(f"Критическая ошибка account_upd_ws: {e}")

        # logger.error(f"account_upd_ws завершился. Переподключение через 5 секунд.")
        await sleep(5)


@add_task(task_manager, so_manager, 'price_upd')
async def price_upd_ws(symbol, **kwargs):
    seconds = kwargs.get('seconds', 0)
    http_session = kwargs.get('http_session')

    channel = {"id": '1', "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}
    await sleep(seconds)  # Задержка перед запуском функции, иначе ошибка API

    while True:
        try:
            async with http_session.ws_connect(config.URL_WS) as ws:
                print(f"WebSocket connected price_upd_ws for {symbol}")
                await ws.send_json(channel)

                async for message in ws:
                    try:
                        if 'data' in (data := loads(decompress(message.data).decode())):
                            await ws_price.update_price(symbol, int(time() * 1000), float(data["data"]["c"]))

                    except Exception as e:
                        logger.error(f"Непредвиденная ошибка price_upd_ws: {e}, сообщение: {message.data}")

        except Exception as e:
            print(f"Критическая ошибка price_upd_ws: {symbol}, {e}")

        # logger.error(f"price_upd_ws для {symbol} завершился. Переподключение через 5 секунд.")
        await sleep(5)  # Пауза перед повторным подключением


@add_task(task_manager, so_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session = kwargs.get('async_session')
    partly_target_profit = 0.006  # 0.6%

    async def trading_logic():
        while not await config_manager.get_data(symbol, 'init_rsi'):
            await sleep(0.3)  # Задержка перед попыткой данных rsi

        logger.info(f'Запуск торговли Full {symbol}')

        while True:
            _, price = await ws_price.get_price(symbol)

            # Создаем ордер на продажу частично, сумма ордеров > partly_target_profit
            if last_order := await so_manager.get_last_order(symbol):
                if await so_manager.get_b_s_trigger(symbol) == 'sell' and price > last_order['price']:
                    partly_profit = 0.0
                    partly_cost_with_fee = 0.0
                    partly_summary_executed = 0.0
                    orders_id = []

                    for order in reversed(await so_manager.get_orders(symbol)):
                        partly_profit += order['executed_qty'] * price
                        partly_cost_with_fee += order['cost_with_fee']

                        if partly_profit >= partly_cost_with_fee * (1 + partly_target_profit):
                            partly_summary_executed += order['executed_qty']
                            orders_id.append(order['id'])
                        else:
                            partly_profit -= order['executed_qty'] * price
                            partly_cost_with_fee -= order['cost_with_fee']

                    if partly_summary_executed:
                        step_size = await so_manager.get_step_size(symbol)
                        partly_summary_executed = round(partly_summary_executed, get_decimal_places(step_size))

                        await place_sell_order(symbol, partly_summary_executed, partly_cost_with_fee, session,
                                               http_session, orders_id=orders_id)

            # Ордер на покупку, если цена ниже (1%) от цены последнего ордера (если ордеров нет, то открываем новый)
            if await so_manager.get_state(symbol) == 'track' and await so_manager.get_b_s_trigger(symbol) == 'buy':
                if last_order:
                    next_price = last_order['price'] * (1 - await config_manager.get_data(symbol, 'target_grid_size'))

                    if price < next_price:
                        await place_buy_order(symbol, price, session, http_session)

                else:  # Если нет последнего ордера, то покупаем сразу
                    await place_buy_order(symbol, price, session, http_session)

            await sleep(1)

    if session is None:  # Сессия не передана, создаем новый async_session_maker
        async with async_session() as session:
            await trading_logic()
    else:  # Сессия передана, используем ее (используется в хэндлерах)
        await trading_logic()
