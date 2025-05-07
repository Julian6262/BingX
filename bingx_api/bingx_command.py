from asyncio import sleep, gather
from datetime import datetime
from decimal import Decimal
from gzip import decompress
from time import time

from aiohttp import ClientSession, WSMsgType
from sqlalchemy.ext.asyncio import AsyncSession
from logging import getLogger
from json import loads

from bingx_api.api_client import send_request
from bingx_api.bingx_models import WebSocketPrice, SymbolOrderManager, AccountManager, TaskManager, ProfitManager
from common.config import config
from common.func import get_decimal_places, add_task
from database.orm_query import add_order, update_profit, del_orders

logger = getLogger('my_app')

ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()
task_manager = TaskManager()
profit_manager = ProfitManager()


async def get_candlestick_data(symbol: str, session: ClientSession, interval: str):
    endpoint = '/openApi/spot/v2/market/kline'
    params = {"symbol": f'{symbol}-USDT', "interval": interval, "limit": 200}

    return await send_request("GET", session, endpoint, params)


async def place_order(symbol: str, session: ClientSession, side: str, executed_qty: float | Decimal):
    endpoint = '/openApi/spot/v1/trade/order'
    params = {"symbol": f'{symbol}-USDT', "type": "MARKET", "side": side, "quantity": executed_qty}

    return await send_request("POST", session, endpoint, params)


async def get_symbol_info(symbol: str, session: ClientSession):
    endpoint = '/openApi/spot/v1/common/symbols'
    params = {"symbol": f'{symbol}-USDT'}

    return await send_request("GET", session, endpoint, params)


async def manage_listen_key(http_session: ClientSession):
    endpoint = '/openApi/user/auth/userDataStream'

    listen_key, text = await send_request("POST", http_session, endpoint, {})
    if listen_key is None:
        logger.error(f'Ошибка получения listen_key: {text}')
        return

    await account_manager.add_listen_key(listen_key['listenKey'])
    while True:
        await sleep(1200)
        await send_request("PUT", http_session, endpoint, {"listenKey": listen_key['listenKey']})


async def place_buy_order(symbol: str, price: float, session: AsyncSession, http_session: ClientSession):
    if (acc_money_usdt := await account_manager.get_balance('USDT')) < config.ACCOUNT_BALANCE:
        # return f'Баланс слишком маленький: {acc_money_usdt}'
        return None

    acc_money = await account_manager.get_balance(symbol)
    step_size = await so_manager.get_step_size(symbol)
    sum_executed_qty = await so_manager.get_summary_executed_qty(symbol)
    execute_qty = config.QUANTITY / price
    for_fee = execute_qty * config.FOR_FEE  # Берем 10% от суммы с запасом на комиссию при покупке

    execute_qty_c = execute_qty if acc_money - sum_executed_qty > for_fee else execute_qty + max(for_fee, step_size)

    # Округляем до ближайшего кратного step_size
    decimal_places = get_decimal_places(step_size)
    execute_qty = round(execute_qty, decimal_places)
    execute_qty_c = round(execute_qty_c, decimal_places)

    data, text = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)  # Ордер на покупку
    if not (order_data := data.get("data")):
        return f'\n\nОрдер НЕ открыт {symbol}: {text}\n'

    # Если сумма USDT меньше execute_qty_c, используем уменьшенную сумму executedQty из ответа на запрос
    # -step_size* для того, чтобы при продаже был резерв для комиссии
    executed_qty_order = float(order_data['executedQty'])
    orig_qty_order = float(order_data['origQty'])
    execute_qty = execute_qty if executed_qty_order == orig_qty_order else (executed_qty_order - step_size)

    data_for_db = {
        'price': price,
        'executed_qty': execute_qty,
        'cost': (cost := float(order_data['cummulativeQuoteQty'])),  # Цена за одну монету
        'cost_with_fee': cost * (1 + config.TAKER_MAKER),  # 0.4% комиссия(на бирже 0.1% + 0.1%)
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await gather(
        add_order(session, symbol, data_for_db),  # Добавить ордер в базу
        so_manager.update_order(symbol, data_for_db),  # Добавить ордер в память
    )

    logger.info(
        f'\n\nденьги: {acc_money}\n'
        f'summary_executed_qty: {sum_executed_qty}\n'
        f'acc_money - summary_executed_qty: {acc_money - sum_executed_qty}\n'
        f'Берем комиссию: {'НЕТ' if acc_money - sum_executed_qty > for_fee else 'ДА'}\n'
        f'for_fee 10%: {for_fee}\n'
        f'decimal_places: {decimal_places}\n'
        f'шаг {step_size}\n'
        f'execute_qty (учитывает step_size): {execute_qty}\n'
        f'execute_qty_c: {execute_qty_c}\n'
    )

    return f'\n\nОрдер открыт {symbol}\n{text}\n{str(data)}\n'


async def place_sell_order(symbol: str, summary_executed: float, session: AsyncSession, http_session: ClientSession,
                           data: dict, open_time: datetime = None):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    order_data, text = await place_order(symbol, http_session, 'SELL', executed_qty=summary_executed)
    if not (order_data_ok := order_data.get("data")):
        report = f'\n\nПродажа не прошла: {text}\n{str(order_data)}\n\n'
        logger.error(report)
        return report

    so_manager.pause_after_sell = True
    real_profit = float(order_data_ok["cummulativeQuoteQty"]) - data['total_cost_with_fee']

    await update_profit(symbol, session, real_profit)
    await so_manager.update_profit(symbol, real_profit)

    await del_orders(symbol, session, open_time)
    await so_manager.del_orders(symbol, open_time)

    await session.commit()

    report = (f'\nРасчет моей программы:\n'
              f'price: {data['price']}\n'
              f'summary_executed: {summary_executed}\n'
              f'Сумма в бирже price * summary_executed: {data['price'] * summary_executed}\n'
              f'Сумма с комиссией total_cost_with_fee: {data['total_cost_with_fee']}\n'
              f'Доход: {data['price'] * summary_executed - data['total_cost_with_fee']}\n\n'
              f'Доход cummulativeQuoteQty: {real_profit}\n'
              f'\n\nОрдера закрыты {symbol}\n{text}\n{str(order_data_ok)}\n\n')

    logger.info(report)
    return report


# @add_task(task_manager, so_manager, 'kline_upd_ws')
# async def kline_upd_ws(symbol, **kwargs):
#     seconds = kwargs.get('seconds', 0)
#     http_session = kwargs.get('http_session')
#
#     channel = {"id": '1', "reqType": "sub", "dataType": f"{symbol}-USDT@kline_3min"}
#     await sleep(seconds)  # Задержка перед запуском функции, иначе ошибка API
#
#     while True:  # Цикл для повторного подключения
#         try:
#             async with http_session.ws_connect(config.URL_WS) as ws:
#                 logger.info(f"WebSocket connected kline_upd_ws for {symbol}")
#                 await ws.send_json(channel)
#
#                 async for message in ws:
#                     if ws.closed:
#                         logger.warning(f"Соединение WebSocket закрыто {symbol}")
#                         break
#
#                     if message.type in (WSMsgType.TEXT, WSMsgType.BINARY):  # Проверка типа сообщения.
#                         try:
#                             if 'data' in (data := loads(decompress(message.data).decode())):
#                                 # await ws_price.update_price(symbol, float(data["data"]["c"]))
#                                 print('kline_upd_ws', data["data"])
#
#                         except Exception as e:
#                             logger.error(f"Непредвиденная ошибка kline_upd_ws: {e}, сообщение: {message.data}")
#
#                     else:  # Обработка всех остальных типов сообщений
#                         logger.error(f"Неизвестный тип сообщения WebSocket: {message.type}, данные: {message.data}")
#                         break
#
#         except Exception as e:
#             logger.error(f"Критическая ошибка kline_upd_ws: {symbol}, {e}")
#
#         logger.error(f"kline_upd_ws для {symbol} завершился. Переподключение через 5 секунд.")
#         await sleep(5)  # Пауза перед повторным подключением


async def account_upd_ws(http_session: ClientSession):
    while not (listen_key := await account_manager.get_listen_key()):
        await sleep(0.5)  # Задержка перед попыткой получения ключа

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
                        logger.error(f"Другая Ошибка account_upd_ws: {e}, сообщение: {message.data}")

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

    while True:  # Цикл для повторного подключения
        try:
            async with http_session.ws_connect(config.URL_WS) as ws:
                logger.info(f"WebSocket connected price_upd_ws for {symbol}")
                await ws.send_json(channel)

                async for message in ws:
                    if ws.closed:
                        logger.warning(f"Соединение WebSocket закрыто {symbol}")
                        break

                    if message.type in (WSMsgType.TEXT, WSMsgType.BINARY):  # Проверка типа сообщения.
                        try:
                            if 'data' in (data := loads(decompress(message.data).decode())):
                                await ws_price.update_price(symbol, int(time() * 1000), float(data["data"]["c"]))

                        except Exception as e:
                            logger.error(f"Непредвиденная ошибка price_upd_ws: {e}, сообщение: {message.data}")

                    else:  # Обработка всех остальных типов сообщений
                        logger.error(f"Неизвестный тип сообщения WebSocket: {message.type}, данные: {message.data}")
                        break

        except Exception as e:
            logger.error(f"Критическая ошибка price_upd_ws: {symbol}, {e}")

        logger.error(f"price_upd_ws для {symbol} завершился. Переподключение через 5 секунд.")
        await sleep(5)  # Пауза перед повторным подключением


@add_task(task_manager, so_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session_maker = kwargs.get('async_session_maker')
    target_profit = config.TARGET_PROFIT

    async def trading_logic():
        while not await ws_price.get_price(symbol):
            await sleep(0.5)  # Задержка перед попыткой получения цены

        logger.info(f'Запуск торговли {symbol}')

        while True:
            _, price = await ws_price.get_price(symbol)
            state = await so_manager.get_state(symbol)

            if summary_executed := await so_manager.get_summary_executed_qty(symbol):
                total_cost_with_fee = await so_manager.get_total_cost_with_fee(symbol)
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

                if profit_to_target > 0:
                    # Создаем ордер на продажу, с суммарной стоимостью покупки монеты
                    await place_sell_order(symbol, summary_executed, session, http_session, profit_data)

            # Ордер на покупку, если цена ниже (1%) от цены последнего ордера (если ордеров нет, то открываем новый)
            if state == 'track':
                if so_manager.pause_after_sell:
                    await sleep(5)  # Задержка перед покупкой
                    so_manager.pause_after_sell = False

                if last_order := await so_manager.get_last_order(symbol):
                    next_price = last_order['price'] * (1 - config.GRID_STEP)

                    if price < next_price:
                        if response := await place_buy_order(symbol, price, session, http_session):
                            logger.info(response)

                else:  # Если нет последнего ордера, то покупаем сразу
                    if response := await place_buy_order(symbol, price, session, http_session):
                        logger.info(response)

            await sleep(0.05)

    if session is None:  # Сессия не передана, создаем новый async_session_maker
        async with async_session_maker() as session:
            await trading_logic()
    else:  # Сессия передана, используем ее (используется в хэндлерах)
        await trading_logic()
