from asyncio import sleep, gather
from datetime import datetime
from decimal import Decimal
from gzip import decompress
from aiohttp import ClientSession, WSMsgType
from sqlalchemy.ext.asyncio import AsyncSession
from logging import getLogger
from json import loads

from bingx_api.api_client import send_request
from bingx_api.bingx_models import WebSocketPrice, SymbolOrderManager, AccountManager, TaskManager, ProfitManager
from common.config import config
from common.func import get_decimal_places, add_task
from database.orm_query import add_order, del_all_orders, del_last_order

logger = getLogger('my_app')

ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()
task_manager = TaskManager()
profit_manager = ProfitManager()


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

    data_for_db = {
        'price': price,
        'executed_qty': execute_qty,
        'cost': (cost := price * execute_qty),  # Цена за одну монету
        'cost_with_fee': cost + cost * config.TAKER_MAKER,  # 0.4% комиссия(на бирже 0.1% + 0.1%)
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await gather(
        add_order(session, symbol, data_for_db),  # Добавить ордер в базу
        so_manager.update_order(symbol, data_for_db),  # Добавить ордер в память
    )

    return f'\n\nОрдер открыт {symbol}\n{text}\n'


async def place_sell_order(symbol: str, summary_executed: float, session: AsyncSession, http_session: ClientSession,
                           open_time: datetime | None = None):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    data, text = await place_order(symbol, http_session, 'SELL', executed_qty=summary_executed)
    if not data.get("data"):
        return f'\n\nПродажа не прошла: {text}\n'

    if open_time:
        tasks = [del_last_order(session, open_time), so_manager.delete_last_order(symbol)]
    else:
        tasks = [del_all_orders(session, symbol), so_manager.delete_all_orders(symbol)]

    await gather(*tasks)
    return f'\n\nОрдера закрыты {symbol} сумма: {summary_executed}\n{text}\n'


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


@add_task(task_manager, 'price_upd')
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
                                await ws_price.update_price(symbol, float(data["data"]["c"]))

                        except Exception as e:
                            logger.error(f"Непредвиденная ошибка price_upd_ws: {e}, сообщение: {message.data}")

                    else:  # Обработка всех остальных типов сообщений
                        logger.error(f"Неизвестный тип сообщения WebSocket: {message.type}, данные: {message.data}")
                        break

        except Exception as e:
            logger.error(f"Критическая ошибка price_upd_ws: {symbol}, {e}")

        logger.error(f"price_upd_ws для {symbol} завершился. Переподключение через 5 секунд.")
        await sleep(5)  # Пауза перед повторным подключением


@add_task(task_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session_maker = kwargs.get('async_session_maker')

    async def trading_logic():
        while not await ws_price.get_price(symbol):
            await sleep(0.5)  # Задержка перед попыткой получения цены

        logger.info(f'Запуск торговли {symbol}')

        while True:
            price = await ws_price.get_price(symbol)

            if summary_executed := await so_manager.get_summary_executed_qty(symbol):
                data = {
                    'price': price,
                    'summary_executed': summary_executed,
                    'total_cost_with_fee': (total_cost_with_fee := await so_manager.get_total_cost_with_fee(symbol)),
                    'be_level_with_fee': total_cost_with_fee / summary_executed,
                    'profit_target': (profit_target := total_cost_with_fee * config.TARGET_PROFIT),
                    'total_cost_with_fee_tp': (total_cost_with_fee_tp := total_cost_with_fee + profit_target),
                    'be_level_with_fee_tp': total_cost_with_fee_tp / summary_executed,
                    'current_profit': (current_profit := price * summary_executed - total_cost_with_fee),
                    'profit_to_target': (profit_to_target := price * summary_executed - total_cost_with_fee_tp)
                }

                await profit_manager.update_data(symbol, data)

                if profit_to_target > 0:
                    # Создаем ордер на продажу, с суммарной стоимостью покупки монеты
                    response = await place_sell_order(symbol, summary_executed, session, http_session)
                    logger.info(response + f'\nДоход: {current_profit}\n')
                    await sleep(5)  # Пауза после продажи всех ордеров, перед покупкой нового

            # Ордер на покупку, если цена ниже 0,5% от цены последнего ордера (если ордеров нет, то открываем новый)
            if last_order := await so_manager.get_last_order(symbol):
                last_order_price = last_order['price']
                next_price = last_order_price - last_order_price * config.GRID_STEP
                # print(f"След цена: {next_price}, Текущая цена: {price}")

                if price < next_price:
                    if response := await place_buy_order(symbol, price, session, http_session):
                        logger.info(response)

            else:  # Если нет последнего ордера, то покупаем сразу
                response = await place_buy_order(symbol, price, session, http_session)
                logger.info(response)

            await sleep(0.1)

    if session is None:  # Сессия не передана, создаем новый async_session_maker
        async with async_session_maker() as session:
            await trading_logic()
    else:  # Сессия передана, используем ее (используется в хэндлерах)
        await trading_logic()
