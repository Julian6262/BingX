from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bingx_command import ws_price

router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message):
    # price = await ws_price.get_value()
    # await message.answer(str(price))
    await message.answer('hh')


@router.message(F.text == '1')
async def start_cmd1(message: Message):
    price = await ws_price.get_value()
    await message.answer(str(price))
    # await message.answer('hh')
