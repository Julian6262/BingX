from asyncio import sleep, gather
from datetime import datetime
from decimal import Decimal
from gzip import decompress
from aiohttp import ClientSession, WSMsgType
from sqlalchemy.ext.asyncio import AsyncSession
from logging import getLogger
from json import loads

from bingx_api.api_client import send_request
from bingx_api.bingx_models import WebSocketPrice, SymbolOrderManager, AccountManager, TaskManager
from common.config import config
from common.func import get_decimal_places, add_task
from database.orm_query import add_order, del_all_orders

logger = getLogger('my_app')

ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()
task_manager = TaskManager()


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
        return f'Баланс слишком маленький: {acc_money_usdt}'

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

    logger.info(
        f'\n\nденьги: {acc_money}\n'
        f'summary_executed_qty: {sum_executed_qty}\n'
        f'acc_money - summary_executed_qty: {acc_money - sum_executed_qty}\n'
        f'Берем комиссию: {'НЕТ' if acc_money - sum_executed_qty > for_fee else 'ДА'}\n'
        f'for_fee 10%: {for_fee}\n'
        f'decimal_places: {decimal_places}\n'
        f'шаг {step_size}\n'
        f'execute_qty: {execute_qty}\n'
        f'execute_qty_c: {execute_qty_c}\n'
    )

    data, text = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)  # Ордер на покупку

    if not (order_data := data.get("data")):
        logger.info(order_data)
        return f'\n\nОрдер НЕ открыт {symbol}: {text}\n'

    # --- Если сумма USDT меньше execute_qty_c, используем уменьшенную сумму executedQty из ответа на запрос
    executed_qty_order = float(order_data['executedQty'])
    orig_qty_order = float(order_data['origQty'])

    # -step_size* для того, чтобы при продаже был резерв для комиссии
    execute_qty = execute_qty if executed_qty_order == orig_qty_order else (executed_qty_order - step_size)

    data_for_db = {
        'price': price,
        'executed_qty': execute_qty,
        'cost': (cost := price * execute_qty),  # Цена за одну монету
        'cost_with_fee': cost + cost * config.TAKER_MAKER,  # 0.3% комиссия(на бирже 0.1% + 0.1%)
        'open_time': datetime.fromtimestamp(order_data['transactTime'] / 1000)
    }

    await gather(
        add_order(session, symbol, data_for_db),  # Добавить ордер в базу
        so_manager.update_order(symbol, data_for_db),  # Добавить ордер в память
    )

    return f'\n\nОрдер открыт {symbol}\n'


async def place_sell_order(symbol: str, session: AsyncSession, http_session: ClientSession):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    summary_executed = await so_manager.get_summary_executed_qty(symbol)
    data, text = await place_order(symbol, http_session, 'SELL', executed_qty=summary_executed)

    if not data.get("data"):
        return f'\n\nПродажа не прошла: {text}\n'

    await gather(
        del_all_orders(session, symbol),  # Удалить все ордера из базы
        so_manager.delete_all_orders(symbol),  # Удалить все ордера из памяти
    )
    return (f'\n\nВсе Ордера закрыты {symbol} сумма: {summary_executed}\n'
            f'!!!! здесь разместить доход!!!!!')


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


@add_task(task_manager, 'be_level')
async def track_be_level(symbol, **kwargs):
    while not await ws_price.get_price(symbol):
        await sleep(0.5)  # Задержка перед попыткой получения цены

    await so_manager.set_sell_order_flag(symbol, False)

    while True:
        if summary_executed := await so_manager.get_summary_executed_qty(symbol):
            actual_price = await ws_price.get_price(symbol)
            total_cost_with_fee = await so_manager.get_total_cost_with_fee(symbol)
            be_level_with_fee = total_cost_with_fee / summary_executed
            total_cost_with_fee_tp = total_cost_with_fee + total_cost_with_fee * config.TARGET_PROFIT
            be_level_with_fee_tp = total_cost_with_fee_tp / summary_executed

            print(
                f"\n---symbol---{symbol}\n"
                f'actual_price: {actual_price}\n'
                f'сумма с комиссией биржи (total_cost_with_fee): {total_cost_with_fee}\n'
                f'сумма с комиссией биржи + 1% (total_cost_with_fee_tp): {total_cost_with_fee_tp}\n'
                f'доход: {actual_price * summary_executed - total_cost_with_fee}\n'
                f'summary_executed: {summary_executed}\n'
                f'безубыток с комиссией биржи (be_level_with_fee): {be_level_with_fee}\n'
                f'безубыток с комиссией биржи + 1% (be_level_with_fee_tp): {be_level_with_fee_tp}\n'
                f'actual_price * summary_executed: {actual_price * summary_executed}\n'
                f'actual_price * summary_executed - total_cost_with_fee_tp: {actual_price * summary_executed - total_cost_with_fee_tp}\n'
            )

            if actual_price * summary_executed > total_cost_with_fee_tp:
                await so_manager.set_sell_order_flag(symbol, True)
                await so_manager.delete_all_orders(symbol),  # Удалить все ордера из памяти

        else:
            print(f"Отсутствуют открытые ордера для {symbol}")

        await sleep(5)


@add_task(task_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session_maker = kwargs.get('async_session_maker')

    async def trading_logic():
        while not await ws_price.get_price(symbol):
            await sleep(0.5)  # Задержка перед попыткой получения цены

        print(f'!!!!!    Запуск торговли    !!!!! {symbol}')

        while True:
            price = await ws_price.get_price(symbol)
            buy_order_flag = True  # Флаг, указывающий, нужно ли размещать ордер

            # создаем ордер на покупку, если цена ниже 0,5% от цены последнего ордера
            if last_order := await so_manager.get_last_order(symbol):
                last_order_price = last_order['price']
                next_price = last_order_price - last_order_price * config.GRID_STEP
                print(f"След цена: {next_price}, Текущая цена: {price}")

                if price > next_price:
                    buy_order_flag = False  # Не размещаем ордер, если цена выше next_price

            if buy_order_flag:
                response = await place_buy_order(symbol, price, session, http_session)
                logger.info(response)

            # Создаем ордер на продажу, с суммарной стоимостью покупки монеты
            if await so_manager.get_sell_order_flag(symbol):
                if response := await place_sell_order(symbol, session, http_session):
                    logger.info(response)
                    await so_manager.set_sell_order_flag(symbol, False)  # Очищаем флаг

            await sleep(5)

    if session is None:  # Сессия не передана, создаем новую
        async with async_session_maker() as session:
            await trading_logic()
    else:  # Сессия передана, используем ее
        await trading_logic()
