from datetime import datetime
from functools import total_ordering
from logging import Logger
from dataclasses import dataclass

from common.logger import get_logger
from data.util import Result as UtilResult

logger: Logger = get_logger()


@dataclass
@total_ordering
class Result:
    timestamp: float
    tournament_id: str
    round: int
    board_id: int
    white_player: str
    black_player: str
    result: UtilResult

    @property
    def timestamp_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime('%H:%M')

    @property
    def result_str(self) -> str:
        return str(self.result) if self.result else ''

    def __lt__(self, other):
        # p1 < p2 calls p1.__lt__(p2)
        return self.timestamp < other.timestamp

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        return self.timestamp == other.timestamp

    def __repr__(self):
        return (f'{self.__class__.__name__}('
                f'{self.timestamp_str} {self.tournament_id}.{self.board_id} '
                f'{self.white_player} {self.result_str} {self.black_player})')
