from logging import Logger
from common.logger import get_logger
from data.screen import AScreen

logger: Logger = get_logger()


ROTATOR_DEFAULT_DELAY: int = 15


class Rotator:
    def __init__(self, id: str, delay: int, screens: list[AScreen]):
        self.__id: str = id
        self.__delay: int = delay
        self.__screens: list[AScreen] = screens

    @property
    def id(self) -> str:
        return self.__id

    @property
    def delay(self) -> int:
        return self.__delay

    @property
    def screens(self) -> list[AScreen]:
        return self.__screens
