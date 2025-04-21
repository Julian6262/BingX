from asyncio import Lock
from os import getenv
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class Config:
    def __init__(self):
        self._lock = Lock()

        self.BASE_URL = getenv('BASE_URL')
        self.URL_WS = getenv('URL_WS')
        self.SECRET_KEY = getenv('SECRET_KEY')
        self.API_KEY = getenv('API_KEY')
        self.TOKEN = getenv('TOKEN')
        self.DB_URL = getenv('DB_URL')
        self.ADMIN = getenv('ADMIN')
        self.SYMBOLS = ('BTC', 'BNB', 'SOL', 'ETH', 'XRP', 'ADA', 'LTC', 'LINK', 'TRX')
        self.HEADERS = {'X-BX-APIKEY': self.API_KEY}
        self.QUANTITY = 2  # в долларах
        self.TAKER, self.MAKER = 0.3, 0.3  # в процентах
        self.TAKER_MAKER = (self.TAKER + self.MAKER) / 100


config = Config()
