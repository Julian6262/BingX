from asyncio import Lock, sleep, CancelledError, gather
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from gzip import decompress, BadGzipFile
from aiohttp import ClientSession, ClientConnectorError, WSServerHandshakeError
from sqlalchemy.ext.asyncio import AsyncSession
from websockets import ConnectionClosed
from logging import error
from time import time
from hmac import new as hmac_new
from hashlib import sha256
from json import loads, JSONDecodeError

from common.config import config
from common.func import get_decimal_places, add_task
from database.orm_query import add_order, del_all_orders


# -----------------------------------------------------------------------------
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
                    error(f"Неожиданный Content-Type: {response.content_type}")
                    return None

                print('Json: ', data)
                return data

            else:
                error(f"Ошибка {response.status} для {params.get('symbol')}: {await response.text()}")
                return None

    except ClientConnectorError as e:
        error(f'Ошибка соединения с сетью (request): {e}')
        return None

    except JSONDecodeError as e:  # обработка ошибки декодирования json
        error(f"Ошибка декодирования JSON: {e}")
        return None


class AccountManager:  # Класс для работы с данными счета
    def __init__(self):
        self._balance = {}
        self._listen_key = None
        self._lock = Lock()

    async def update_balance_batch(self, batch_data: list):
        async with self._lock:
            for data in batch_data:
                self._balance[data['a']] = float(data['wb'])

    async def get_balance(self, symbol: str):
        async with self._lock:
            return self._balance.get(symbol, 0.0)

    async def add_listen_key(self, listen_key: str):
        async with self._lock:
            self._listen_key = listen_key

    async def get_listen_key(self):
        async with self._lock:
            return self._listen_key


class WebSocketPrice:  # Класс для работы с ценами в реальном времени из websockets
    def __init__(self):
        self._price = {}
        self._task_price_upd = {}
        self._lock = Lock()

    async def update_price(self, symbol: str, price: float):
        async with self._lock:
            self._price[symbol] = price

    async def get_price(self, symbol: str):
        async with self._lock:
            return self._price.get(symbol)

    async def add_task(self, symbol: str, task):
        async with self._lock:
            self._task_price_upd[symbol] = task

    async def del_task(self, symbol: str):  # Изменить, сделать как в SymbolOrderManager !!!!!!!!!
        async with self._lock:
            if task := self._task_price_upd.pop(symbol, None):
                task.cancel()
                try:
                    await task  # Дожидаемся завершения задачи
                except CancelledError:
                    pass  # Игнорируем CancelledError - это ожидаемое поведение
                print(f"Отмена задачи по ws_price для {symbol}")


class SymbolOrderManager:  # Класс для работы с ордерами в реальном времени
    def __init__(self):
        self.symbols = []
        self._sell_order_flag = {}
        self._step_size = {}
        self._orders = defaultdict(list)  # Словарь для хранения ордеров по символам
        self._tasks = defaultdict(list)
        self._lock = Lock()

    async def add_symbols_and_orders_batch(self, batch_data: list):
        async with self._lock:
            for symbol, step_size, data in batch_data:
                self.symbols.append(symbol)
                self._step_size[symbol] = step_size
                self._orders[symbol] = data

    async def set_sell_order_flag(self, symbol: str, flag: bool):
        async with self._lock:
            self._sell_order_flag[symbol] = flag

    async def get_sell_order_flag(self, symbol: str):
        async with self._lock:
            return self._sell_order_flag.get(symbol)

    async def update_order(self, symbol: str, data: dict):
        async with self._lock:
            self._orders[symbol].append(data)

    async def add_symbol(self, symbol: str, step_size: float):
        async with self._lock:
            self.symbols.append(symbol)
            self._step_size[symbol] = step_size

    async def delete_symbol(self, symbol: str):
        async with self._lock:
            if symbol in self.symbols:
                self.symbols.remove(symbol)
                del self._step_size[symbol]

    async def get_step_size(self, symbol: str):
        async with self._lock:
            return self._step_size.get(symbol)

    async def get_orders(self, symbol: str):
        async with self._lock:
            return self._orders.get(symbol)

    async def get_last_order(self, symbol: str):
        async with self._lock:
            orders = self._orders.get(symbol)
            return orders[-1] if orders else None

    async def delete_last_order(self, symbol: str):
        async with self._lock:
            if orders := self._orders.get(symbol):
                orders.pop()

    async def get_summary_executed_qty(self, symbol: str):  # Метод для подсчета объема исполненных ордеров
        async with self._lock:
            orders = self._orders.get(symbol)
            return sum(order['executed_qty'] for order in orders) if orders else 0.0

    async def delete_all_orders(self, symbol: str):  # Метод для удаления всех ордеров при усреднении
        async with self._lock:
            if orders := self._orders.get(symbol):
                orders.clear()

    async def get_total_cost_with_fee(self, symbol: str):  # Метод для подсчета общей стоимости с комиссией
        async with self._lock:
            orders = self._orders.get(symbol)
            return sum(order['cost_with_fee'] for order in orders) if orders else 0.0

    async def add_task(self, symbol: str, task):
        async with self._lock:
            self._tasks[symbol].append(task)

    async def del_tasks(self, symbol: str):
        async with self._lock:
            tasks = self._tasks.pop(symbol, [])

            for task in tasks:  # Итерируемся по списку задач
                if task and not task.done():  # Проверяем, что задача существует и не завершена
                    task.cancel()
                    try:
                        await task  # Дожидаемся завершения задачи
                    except CancelledError:
                        pass  # Игнорируем CancelledError - это ожидаемое поведение
                    print(f"Отмена задачи по track_be для {symbol}")


ws_price = WebSocketPrice()
so_manager = SymbolOrderManager()
account_manager = AccountManager()


# -----------------------------------------------------------------------------

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

    if (listen_key := await send_request("POST", http_session, endpoint, {})) is None:
        error('Ошибка получения listen_key')
        return

    await account_manager.add_listen_key(listen_key['listenKey'])
    while True:
        await sleep(1200)
        await send_request("PUT", http_session, endpoint, {"listenKey": listen_key['listenKey']})


async def account_upd_ws(http_session: ClientSession):
    while not (listen_key := await account_manager.get_listen_key()):
        await sleep(0.5)  # Задержка перед попыткой получения ключа

    channel = {"id": "1", "reqType": "sub", "dataType": "ACCOUNT_UPDATE"}
    url = f"{config.URL_WS}?listenKey={listen_key}"
    print(f'Запущено отслеживание баланса')

    try:
        async with http_session.ws_connect(url) as ws:
            await ws.send_json(channel)

            async for message in ws:
                try:
                    if 'e' in (data := loads(decompress(message.data).decode())):
                        await account_manager.update_balance_batch(data['a']['B'])
                        print(data['a']['B'])

                except (BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except (ConnectionClosed, WSServerHandshakeError) as e:
        error(f"Ошибка соединения WebSocket:, {e}")


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

    ans = 'НЕТ' if acc_money - sum_executed_qty > for_fee else 'ДА'
    print(
        f'\nденьги: {acc_money}\n'
        f'summary_executed_qty: {sum_executed_qty}\n'
        f'acc_money - summary_executed_qty: {acc_money - sum_executed_qty}\n'
        f'Берем комсу: {ans}\n'
        f'комиссия: {for_fee}\n'
        f'decimal_places: {decimal_places}\n'
        f'шаг {step_size}\n'
        f'execute_qty: {execute_qty}\n'
        f'execute_qty_c: {execute_qty_c}\n'
    )

    response = await place_order(symbol, http_session, 'BUY', executed_qty=execute_qty_c)  # Ордер на покупку

    if not (order_data := response.get("data")):
        print(order_data)
        return 'Ордер не открыт'

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

    return 'Ордер открыт'


async def place_sell_order(symbol: str, session: AsyncSession, http_session: ClientSession):
    # Ордер на продажу по суммарной стоимости покупки монеты, напр 0.00011 BTC
    summary_executed = await so_manager.get_summary_executed_qty(symbol)
    response = await place_order(symbol, http_session, 'SELL', executed_qty=summary_executed)

    if not response.get("data"):
        return 'Продажа не прошла'

    await gather(
        del_all_orders(session, symbol),  # Удалить все ордера из базы
        so_manager.delete_all_orders(symbol),  # Удалить все ордера из памяти
    )
    return 'Все Ордера закрыты'


@add_task(ws_price, 'price_upd')
async def price_upd_ws(symbol, **kwargs):
    http_session = kwargs['http_session']
    seconds = kwargs['seconds']

    channel = {"id": '1', "reqType": "sub", "dataType": f"{symbol}-USDT@lastPrice"}
    await sleep(seconds)  # Задержка перед запуском функции, иначе ошибка API

    try:
        async with http_session.ws_connect(config.URL_WS) as ws:
            await ws.send_json(channel)

            async for message in ws:
                try:
                    if 'data' in (data := loads(decompress(message.data).decode())):
                        await ws_price.update_price(symbol, float(data["data"]["c"]))

                except (BadGzipFile, JSONDecodeError, KeyError, TypeError) as e:
                    error(f"Ошибка обработки сообщения WebSocket: {e}, сообщение: {message.data}")

    except (ConnectionClosed, WSServerHandshakeError) as e:
        error(f"Ошибка соединения WebSocket: {symbol}, {e}")


@add_task(so_manager, 'be_level')
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
                f'сумма с комис биржи (total_cost_with_fee): {total_cost_with_fee}\n'
                f'сумма с комис биржи + 1% (total_cost_with_fee_tp): {total_cost_with_fee_tp}\n'
                f'summary_executed: {summary_executed}\n'
                f'безубыток с комис биржи (be_level_with_fee): {be_level_with_fee}\n'
                f'безубыток с комис биржи + 1% (be_level_with_fee_tp): {be_level_with_fee_tp}\n'
                f'actual_price * summary_executed: {actual_price * summary_executed}\n'
                f'actual_price * summary_executed - total_cost_with_2fee: {actual_price * summary_executed - total_cost_with_fee_tp}\n'
            )

            if actual_price * summary_executed > total_cost_with_fee_tp:
                await so_manager.set_sell_order_flag(symbol, True)

        else:
            print(f"Отсутствуют открытые ордера для {symbol}")

        await sleep(5)


@add_task(so_manager, 'start_trading')
async def start_trading(symbol, **kwargs):
    session = kwargs.get('session')
    http_session = kwargs.get('http_session')
    async_session_maker = kwargs.get('async_session_maker')

    async def trading_logic(symbol, session, http_session):
        while not await ws_price.get_price(symbol):
            await sleep(0.5)  # Задержка перед попыткой получения цены

        print(f'Запуск торговли {symbol}')

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
                print(response)

            # Создаем ордер на продажу, с суммарной стоимостью покупки монеты
            if await so_manager.get_sell_order_flag(symbol):
                if response := await place_sell_order(symbol, session, http_session):
                    print(response)
                    await so_manager.set_sell_order_flag(symbol, False)  # Очищаем флаг

            await sleep(5)

    if session is None:  # Сессия не передана, создаем новую
        async with async_session_maker() as session:
            await trading_logic(symbol, session, http_session)
    else:  # Сессия передана, используем ее
        await trading_logic(symbol, session, http_session)
