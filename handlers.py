from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bingx_command import ws_price, place_order
from common.config import Config
from database.orm_query import add_order, get_last_order, del_last_order
from filters.chat_types import IsAdmin

router = Router()
router.message.filter(IsAdmin(Config.ADMIN))  # Фильтр по ID, кто может пользоваться ботом

quantity = 1


@router.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(str(message.from_user.id))


@router.message(F.text.startswith('1_'))  # Вводим например: 1 btc, 1 Bnb
async def get_price(message: Message):
    data = message.text.split('_')
    if len(data) == 2:
        symbol = data[1]
        price = await ws_price.get_price(symbol)

        if price:
            await message.answer(f'Символ {symbol}, цена {price}')
        else:
            await message.answer('Цена не готова/не тот символ')


@router.message(F.text.startswith('b_'))  # Вводим например: b btc, b Bnb
async def buy_order(message: Message, session: AsyncSession):
    data = message.text.split('_')
    if len(data) == 2:
        symbol = data[1]
        price = await ws_price.get_price(symbol)

        if price:
            # --- Отправить ордер на покупку по цене в $
            response = await place_order(symbol, 'BUY', quantity=quantity)
            order_data = response.get("data", False)  # Если в ответе есть 'data', То добавить в БД
            await message.answer(str(response))
            # ------------------------------

            order_data = {
                'data': {'symbol': f"{symbol.upper()}-USDT", 'orderId': '1907544211566002176', 'price': price,
                         'executedQty': 1 / price}
            }

            if order_data:
                await add_order(session, order_data['data'])
                await message.answer('символ добавлен')
            else:
                await message.answer('Покупка не прошла')
        else:
            await message.answer('Цена не готова/не тот символ')


@router.message(F.text.startswith('s_'))  # Вводим например: s btc, s Bnb
async def sell_order(message: Message, session: AsyncSession):
    data = message.text.split('_')
    if len(data) == 2:
        symbol = data[1]
        price = await ws_price.get_price(symbol)

        if price:
            last_order_data = await get_last_order(session, symbol)

            if last_order_data:
                executed_qty, last_id = last_order_data['executed_qty'], last_order_data['id']

                # --- Отправить ордер на продажу по цене покупки монеты, напр 0.000011 BTC
                # response = await place_order(symbol, 'SELL', executed_qty=executed_qty)
                # order_data = response.get("data", False)
                order_data = True
                # await message.answer(str(response))
                # ------------------------------

                if order_data:
                    await del_last_order(session, last_id)
                    await message.answer('символ удален')
                else:
                    await message.answer('Продажа не прошла')
            else:
                await message.answer('Символы кончились')
        else:
            await message.answer('Цена не готова/не тот символ')
