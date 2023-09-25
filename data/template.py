from typing import Dict
from logging import Logger

from common.logger import get_logger

logger: Logger = get_logger()


class Template:
    def __init__(self, id: str):
        self.__id = id
        self.__data: Dict[str | None, Dict[str, str]] = {}

    @property
    def id(self) -> str:
        return self.__id

    @property
    def data(self) -> Dict[str, Dict[str, str]]:
        return self.__data

    def add_data(self, section: str | None, key: str, value: str):
        if section not in self.__data:
            self.__data[section] = {key: value, }
        else:
            self.__data[section][key] = value

