from functools import total_ordering
from logging import Logger
from dataclasses import dataclass
import warnings

from common.logger import get_logger
from database.papi import RESULT_STRINGS, Result
from data.player import Player

logger: Logger = get_logger()


@dataclass
@total_ordering
class Board:
    board_id: int | None = None
    number: int | None = None
    white_player: Player | None = None
    black_player: Player | None = None
    result: Result | None = None

    @property
    def id(self) -> int | None:
        return self.board_id

    @id.setter
    def id(self, new_id):
        self.board_id = new_id

    def set_id(self, id: int):
        warnings.warn('Use direct assignment to id instead')
        self.board_id = id

    def set_number(self, number: int):
        warnings.warn('Use direct assignment to number instead')
        self.number = number

    def set_white_player(self, player: Player):
        warnings.warn('Use direct assignment to white_player instead')
        self.white_player = player

    def set_black_player(self, player: Player):
        warnings.warn('Use direct assignment to black_player instead')
        self.black_player = player

    @property
    def result_str(self) -> str:
        return str(self.result) if self.result else ''

    def set_result(self, result: Result):
        warnings.warn('Use direct assignment to result instead')
        self.result = result

    def __lt__(self, other):
        # p1 < p2 calls p1.__lt__(p2)
        if not isinstance(other, Board):
            return NotImplemented
        if self.black_player.id == 1:
            return True
        elif other.black_player.id == 1:
            return False
        self_player_1: Player
        self_player_2: Player
        if self.white_player < self.black_player:
            self_player_1 = self.black_player
            self_player_2 = self.white_player
        else:
            self_player_1 = self.white_player
            self_player_2 = self.black_player
        other_player_1: Player
        other_player_2: Player
        if other.white_player < other.black_player:
            other_player_1 = other.black_player
            other_player_2 = other.white_player
        else:
            other_player_1 = other.white_player
            other_player_2 = other.black_player
        if self_player_1.vpoints < other_player_1.vpoints:
            return True
        if self_player_1.vpoints > other_player_1.vpoints:
            return False
        if self_player_2.vpoints < other_player_2.vpoints:
            return True
        if self_player_2.vpoints > other_player_2.vpoints:
            return False
        if self_player_1 < other_player_1:
            return True
        if self_player_1 > other_player_1:
            return False
        return self_player_2 < other_player_2

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(other, Board):
            return NotImplemented
        if self.black_player == 1 or self.white_player.id == 1:
            return False
        self_player_1: Player
        self_player_2: Player
        if self.white_player < self.black_player:
            self_player_1 = self.black_player
            self_player_2 = self.white_player
        else:
            self_player_1 = self.white_player
            self_player_2 = self.black_player
        other_player_1: Player
        other_player_2: Player
        if other.white_player < other.black_player:
            other_player_1 = other.black_player
            other_player_2 = other.white_player
        else:
            other_player_1 = other.white_player
            other_player_2 = other.black_player
        return self_player_1 == other_player_1 and self_player_2 == other_player_2

    def __repr__(self):
        return f'{self.__class__.__name__}({self.number}. {self.white_player} {self.result_str} {self.black_player})'
