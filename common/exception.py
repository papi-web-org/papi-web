from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class PapiException(Exception):
    def __init__(self, string: str):
        super().__init__(string)
