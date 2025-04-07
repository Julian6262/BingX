from os import getenv
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


class Config:
    BASE_URL = getenv('BASE_URL')
    URL_WS = getenv('URL_WS')
    SECRET_KEY = getenv('SECRET_KEY')
    API_KEY = getenv('API_KEY')
    TOKEN = getenv('TOKEN')
    DB_URL=getenv('DB_URL')