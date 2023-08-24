from typing import Optional
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class Pairing:
    def __init__(self, color: str, opponent_id: int, result: int):
        self.__color: Optional[str] = color
        self.__opponent_id: Optional[int] = opponent_id
        self.__result: Optional[int] = result

    @property
    def color(self) -> Optional[str]:
        return self.__color

    @property
    def opponent_id(self) -> Optional[int]:
        return self.__opponent_id

    @property
    def result(self) -> Optional[int]:
        return self.__result

    def __repr__(self):
        return '{}({} {} {})'.format(type(self).__name__, self.color, self.opponent_id, self.result)
