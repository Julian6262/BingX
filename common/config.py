from asyncio import Lock
from os import getenv
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class Config:
    def __init__(self):
        self.BASE_URL = getenv('BASE_URL')
        self.URL_WS = getenv('URL_WS')
        self.SECRET_KEY = getenv('SECRET_KEY')
        self.API_KEY = getenv('API_KEY')
        self.TOKEN = getenv('TOKEN')
        self.DB_URL = getenv('DB_URL')
        self.ADMIN = getenv('ADMIN')
        self.SYMBOLS = ('BTC', 'BNB', 'SOL', 'ETH', 'XRP', 'ADA', 'LTC', 'LINK', 'TRX')
        self.HEADERS = {'X-BX-APIKEY': self.API_KEY}

        self.GRID_STEP = 0.005  # в долях (0.5%)
        self.TARGET_PROFIT = 0.01  # в долях (1%)
        self.ACCOUNT_BALANCE = 1.1  # в долларах, ниже этого баланса не будет работать бот
        self.QUANTITY = 2  # в долларах
        self.TAKER, self.MAKER = 0.0015, 0.0015  # в долях (0.15%)

        self.FOR_FEE = 0.1  # в долях (10% от суммы), резерв для выплаты комиссии
        self.TAKER_MAKER = self.TAKER + self.MAKER


config = Config()
