from logging import Logger
from common.logger import get_logger
from dataclasses import dataclass

logger: Logger = get_logger()


@dataclass(frozen=True)
class Pairing:
    __color: str | None = None
    __opponent_id: int | None = None
    __result: int | None = None

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
        return f'{self.__class__.__name__}({self.color} {self.opponent_id} {self.result})'
