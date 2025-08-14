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
        self.HEADERS: dict = {'X-BX-APIKEY': self.API_KEY}

        self.TAKER: float = 0.002  # в долях (0.2%)
        self.MAKER: float = 0.002  # в долях (0.2%)

        self.TAKER_MAKER: float = self.TAKER + self.MAKER

        self.MAIN_LOT_MAP = {
            (0, 400): 10,
            (400, 900): 20,
            (900, 1400): 30,
            (1400, 2000): 40,
            (2000, 2600): 50,
            (2600, 3200): 60,
            (3200, 3900): 70,
            (3900, 4600): 80,
            (4600, 5300): 90,
        }


config = Config()
