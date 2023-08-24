from typing import Dict, Optional
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class Template:
    def __init__(self, id: str):
        self.__id = id
        self.__data: Dict[Optional[str], Dict[str, str]] = {}

    @property
    def id(self) -> str:
        return self.__id

    @property
    def data(self) -> Dict[str, Dict[str, str]]:
        return self.__data

    def add_data(self, section: Optional[str], key: str, value: str):
        if section not in self.__data:
            self.__data[section] = {key: value, }
        else:
            self.__data[section][key] = value

