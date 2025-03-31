from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer('Privet')


@router.message()
async def start_cmd1(message: Message):
    await message.answer('Privet 123123')



