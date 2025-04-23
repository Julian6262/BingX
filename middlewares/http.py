from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiohttp import ClientSession


class HttpSession(BaseMiddleware):  # Используем одну сессию, переданную из main
    def __init__(self, session: ClientSession):
        self.session = session

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        data['http_session'] = self.session  # одна сессия для всего бота
        return await handler(event, data)
