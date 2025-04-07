from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bingx_command import ws_price, place_order

router = Router()

symbol = 'BTC'
quantity = 2


@router.message(CommandStart())
async def start_cmd(message: Message):
    # price = await ws_price.get_value()
    # await message.answer(str(price))
    await message.answer('hh')


@router.message(F.text == '1')
async def get_price(message: Message):
    # symbol = 'BNB'
    price = await ws_price.get_price(symbol)
    if price:
        await message.answer(f'Символ {symbol}, цена {price}')
    else:
        await message.answer('Цена не готова')


@router.message(F.text == 's')
async def sell_order(message: Message):
    # quantity = 1
    # symbol = 'BNB'
    side = 'SELL'

    price = await ws_price.get_price(symbol)
    if price:
        response = await place_order(symbol, quantity, side)
        await message.answer(str(response))
    else:
        await message.answer('Цена не готова')


@router.message(F.text == 'b')
async def buy_order(message: Message):
    # quantity = 1
    # symbol = 'BNB'
    side = 'BUY'

    price = await ws_price.get_price(symbol)
    if price:
        response = await place_order(symbol, quantity, side)
        await message.answer(str(response))
    else:
        await message.answer('Цена не готова')
