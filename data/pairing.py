from logging import Logger
from common.logger import get_logger

logger: Logger = get_logger()


class Pairing:
    def __init__(self, color: str, opponent_id: int, result: int):
        self.__color: str | None = color
        self.__opponent_id: int | None = opponent_id
        self.__result: int | None = result

    @property
    def color(self) -> str | None:
        return self.__color

    @property
    def opponent_id(self) -> int | None:
        return self.__opponent_id

    @property
    def result(self) -> int | None:
        return self.__result

    def __repr__(self):
        return f'{type(self).__name__}({self.color} {self.opponent_id} {self.result})'
