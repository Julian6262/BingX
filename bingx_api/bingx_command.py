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
from bingx_api.bingx_models import WebSocketPrice, SymbolOrderManager, AccountManager, TaskManager, ProfitManager, \
    ConfigManager

logger = getLogger('my_app')

ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()
task_manager = TaskManager()
profit_manager = ProfitManager()
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

    if usdt_block == 'block':
        await account_manager.set_usdt_block('continue_block')
        logger.warning(report)
        return report

    elif usdt_block == 'continue_block':
        return report

    return None


async def place_buy_order(symbol: str, price: float, session: AsyncSession, http_session: ClientSession):
    if not (lot := await so_manager.get_lot(symbol)):
        report = f'\nНе удалось получить лот для {symbol}\n'
        logger.warning(report)
        return report

    if report := await _check_usdt_balance(lot):
        return report

    acc_money = await account_manager.get_balance(symbol)
    step_size = await so_manager.get_step_size(symbol)
    execute_qty = lot / price
    fee_reserve = execute_qty * config.FEE_RESERVE  # Берем 20% от суммы с запасом на комиссию при продаже (~200 ордеров)

    if acc_money > fee_reserve:
        execute_qty_c = execute_qty
        take_fee = "НЕТ"
    else:
        execute_qty_c = execute_qty + fee_reserve
        take_fee = "ДА"

    # Округляем до ближайшего кратного step_size
    decimal_places = get_decimal_places(step_size)
    execute_qty, execute_qty_c = round(execute_qty, decimal_places), round(execute_qty_c, decimal_places)

    data, text = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)
    if not (order_data := data.get("data")):
        if data["code"] == 100202:  # Если ответ от биржи 100202, то нехватает средств, блокируем покупки
            await account_manager.set_usdt_block('block')

        report = f'\n\nОрдер НЕ открыт {symbol}: {text} {data}\n'
        logger.error(report)
        return report

    data_for_db = {
        'price': price,
        'executed_qty': float(order_data['executedQty']) if take_fee == "НЕТ" else execute_qty,
        'cost': (cost := float(order_data['cummulativeQuoteQty']) if take_fee == "НЕТ" else price * execute_qty),
        'cost_with_fee': cost * (1 + config.TAKER_MAKER),  # 0.4% комиссия(на бирже 0.1% + 0.1%)
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await gather(
        add_order(session, symbol, data_for_db),  # Добавить ордер в базу
        so_manager.update_order(symbol, data_for_db),  # Добавить ордер в память
    )

    report = (f'\n\nденьги: {acc_money}\n'
              f'Берем комиссию?: {take_fee}\n'
              f'fee_reserve 20%: {fee_reserve}\n'
              f'decimal_places: {decimal_places}\n'
              f'origQty==executedQty {order_data['executedQty'] == order_data['origQty']}\n'
              f'шаг {step_size}\n'
              f'execute_qty: {execute_qty}\n'
              f'execute_qty_c: {execute_qty_c}\n'
              f'\nОрдер открыт {symbol}\n{text}\n{str(data)}\n')

    logger.info(report)
    return report


async def place_sell_order(symbol: str, summary_executed: float, total_cost_with_fee: float, session: AsyncSession,
                           http_session: ClientSession, open_times: list[datetime] = None):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    order_data, text = await place_order(symbol, http_session, 'SELL', summary_executed)
    if not (order_data_ok := order_data.get("data")):
        report = f'\n\nПродажа не прошла: {text}\n{str(order_data)}\n\n'
        logger.error(report)
        return report

    _, price = await  ws_price.get_price(symbol)
    real_profit = float(order_data_ok["cummulativeQuoteQty"]) - total_cost_with_fee

    await so_manager.set_pause(symbol, True)
    await update_profit(symbol, session, real_profit)
    await so_manager.update_profit(symbol, real_profit)

    await del_orders(symbol, session, open_times)
    await so_manager.del_orders(symbol, open_times)

    await session.commit()

    report = (f'\n\nРасчет моей программы:\n'
              f'price: {price}\n'
              f'summary_executed: {summary_executed}\n'
              f'Сумма в бирже price * summary_executed: {price * summary_executed}\n'
              f'Сумма с комиссией total_cost_with_fee: {total_cost_with_fee}\n'
              f'Доход: {price * summary_executed - total_cost_with_fee}\n'
              f'Доход cummulativeQuoteQty: {real_profit}\n'
              f'\nОрдера закрыты {symbol}\n{text}\n{str(order_data_ok)}\n')

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
                logger.info(f"WebSocket connected account_upd_ws")
                await ws.send_json(channel)

                async for message in ws:
                    try:
                        if 'e' in (data := loads(decompress(message.data).decode())):
                            await account_manager.update_balance_batch(data['a']['B'])
                            logger.info(f"Account_upd_ws: {data['a']}")

                    except Exception as e:
                        logger.error(f"Непредвиденная ошибка account_upd_ws: {e}, сообщение: {message.data}")

        except Exception as e:
            logger.error(f"Критическая ошибка account_upd_ws: {e}")

        logger.error(f"account_upd_ws завершился. Переподключение через 5 секунд.")
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
                logger.info(f"WebSocket connected price_upd_ws for {symbol}")
                await ws.send_json(channel)

                async for message in ws:
                    try:
                        if 'data' in (data := loads(decompress(message.data).decode())):
                            await ws_price.update_price(symbol, int(time() * 1000), float(data["data"]["c"]))

                    except Exception as e:
                        logger.error(f"Непредвиденная ошибка price_upd_ws: {e}, сообщение: {message.data}")

        except Exception as e:
            logger.error(f"Критическая ошибка price_upd_ws: {symbol}, {e}")

        logger.error(f"price_upd_ws для {symbol} завершился. Переподключение через 5 секунд.")
        await sleep(5)  # Пауза перед повторным подключением


@add_task(task_manager, so_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session = kwargs.get('async_session')
    target_profit = config.TARGET_PROFIT
    partly_target_profit = 0.004  # 0.4%

    async def _trading_logic():
        while not await ws_price.get_price(symbol):
            await sleep(0.3)  # Задержка перед попыткой получения цены

        logger.info(f'Запуск торговли {symbol}')

        while True:
            _, price = await ws_price.get_price(symbol)
            state = await so_manager.get_state(symbol)

            if summary_executed := await so_manager.get_summary(symbol, 'executed_qty'):
                total_cost_with_fee = await so_manager.get_summary(symbol, 'cost_with_fee')
                total_cost_with_fee_tp = total_cost_with_fee * (1 + target_profit)
                current_profit = price * summary_executed - total_cost_with_fee
                profit_to_target = price * summary_executed - total_cost_with_fee_tp

                profit_data = {
                    'price': price,
                    'summary_executed': summary_executed,
                    'total_cost_with_fee': total_cost_with_fee,
                    'be_level_with_fee': total_cost_with_fee / summary_executed,
                    'total_cost_with_fee_tp': total_cost_with_fee_tp,
                    'be_level_with_fee_tp': total_cost_with_fee_tp / summary_executed,
                    'current_profit': current_profit,
                    'profit_to_target': profit_to_target
                }

                await profit_manager.update_data(symbol, profit_data)

                # Создаем ордер на продажу по всем ордерам, если доход > 1%
                if profit_to_target > 0:
                    print(f'\n-----------Полная продажа------------\n')
                    await place_sell_order(symbol, summary_executed, total_cost_with_fee, session, http_session)

                # Создаем ордер на продажу частично, сумма ордеров > 0.4%
                elif await so_manager.get_b_s_trigger(symbol) == 'sell':
                    partly_profit = 0.0
                    partly_cost_with_fee_tp = 0.0
                    partly_cost_with_fee = 0.0
                    partly_summary_executed = 0.0
                    open_times = []

                    for order in reversed(await so_manager.get_orders(symbol)):
                        partly_profit += order['executed_qty'] * price
                        partly_cost_with_fee_tp += order['cost_with_fee'] * (1 + partly_target_profit)

                        if partly_profit > partly_cost_with_fee_tp:
                            partly_summary_executed += order['executed_qty']
                            partly_cost_with_fee += order['cost_with_fee']
                            open_times.append(order['open_time'])
                        else:
                            # break
                            partly_profit -= order['executed_qty'] * price
                            partly_cost_with_fee_tp -= order['cost_with_fee'] * (1 + partly_target_profit)

                    if partly_summary_executed:
                        print(f'\n----------Частичная продажа-------------')
                        print(f'price {price}')
                        print(f'partly_summary_executed {partly_summary_executed}')
                        print(f'partly_cost_with_fee {partly_cost_with_fee}')
                        print(f'Доход {partly_summary_executed * price - partly_cost_with_fee}')
                        print(f'open_times {open_times}')
                        print(f'-----------------------\n')

                        await place_sell_order(symbol, partly_summary_executed, partly_cost_with_fee, session,
                                               http_session, open_times=open_times)

            # Ордер на покупку, если цена ниже (1%) от цены последнего ордера (если ордеров нет, то открываем новый)
            if state == 'track' and await so_manager.get_b_s_trigger(symbol) == 'buy':
                if await so_manager.get_pause(symbol):
                    await sleep(5)  # Задержка перед покупкой
                    await so_manager.set_pause(symbol, False)

                if last_order := await so_manager.get_last_order(symbol):
                    next_price = last_order['price'] * (1 - await config_manager.get_config(symbol, 'grid_size'))

                    if price < next_price:
                        await place_buy_order(symbol, price, session, http_session)

                else:  # Если нет последнего ордера, то покупаем сразу
                    await place_buy_order(symbol, price, session, http_session)

            await sleep(0.05)

    if session is None:  # Сессия не передана, создаем новый async_session_maker
        async with async_session() as session:
            await _trading_logic()
    else:  # Сессия передана, используем ее (используется в хэндлерах)
        await _trading_logic()
