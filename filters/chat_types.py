from aiogram.filters import Filter
from aiogram.types import Message


class IsAdmin(Filter):
    def __init__(self, admin_ids: str) -> None:
        self.admin_ids = set(map(int, admin_ids.split()))

    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in self.admin_ids
