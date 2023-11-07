from logging import Logger
from common.logger import get_logger
from dataclasses import dataclass
from data.util import Result

logger: Logger = get_logger()


@dataclass(frozen=True)
class Pairing:
    """A pairing (from the point of view of the `Player` class)"""
    color: str | None = None
    opponent_id: int | None = None
    result: Result | None = None

    def __repr__(self):
        return f'{self.__class__.__name__}({self.color} {self.opponent_id} {self.result})'

    def __iter__(self):
        yield from (self.color, self.opponent_id, self.result)