from os import getenv
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class Config:
    def __init__(self):
        self.BASE_URL: str = getenv('BASE_URL')
        self.URL_WS: str = getenv('URL_WS')
        self.SECRET_KEY: str = getenv('SECRET_KEY')
        self.API_KEY: str = getenv('API_KEY')
        self.TOKEN: str = getenv('TOKEN')
        self.DB_URL: str = getenv('DB_URL')
        self.ADMIN: str = getenv('ADMIN')
        self.SYMBOLS: tuple = ('BTC', 'BNB', 'SOL', 'ETH', 'XRP', 'ADA', 'LTC', 'LINK', 'TRX')
        self.HEADERS: dict = {'X-BX-APIKEY': self.API_KEY}

        self.GRID_STEP: float = 0.01  # в долях (1%)
        self.TARGET_PROFIT: float = 0.01  # в долях (1%)
        self.ACCOUNT_BALANCE: float = 2  # в долларах, ниже этого баланса не будет работать бот
        self.QUANTITY: float = 2  # в долларах
        self.TAKER: float = 0.002  # в долях (0.2%)
        self.MAKER: float = 0.002  # в долях (0.2%)

        self.FEE_RESERVE: float = 0.2  # в долях (20% от суммы), резерв для выплаты комиссии (~ 200 ордеров)
        self.TAKER_MAKER: float = self.TAKER + self.MAKER


config = Config()
