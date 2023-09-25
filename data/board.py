from functools import total_ordering
from logging import Logger

from common.logger import get_logger
from database.papi import RESULT_STRINGS
from data.player import Player

logger: Logger = get_logger()


@total_ordering
class Board:
    def __init__(self, white_player: Player | None = None, black_player: Player | None = None):
        self.__id: int | None = None
        self.__number: int | None = None
        self.__white_player: Player | None = white_player
        self.__black_player: Player | None = black_player
        self.__result: int | None = None

    @property
    def id(self) -> int:
        return self.__id

    def set_id(self, id: int):
        self.__id = id

    @property
    def number(self) -> int:
        return self.__number

    def set_number(self, number: int):
        self.__number = number

    @property
    def white_player(self) -> Player:
        return self.__white_player

    def set_white_player(self, player: Player):
        self.__white_player = player

    @property
    def black_player(self) -> Player:
        return self.__black_player

    def set_black_player(self, player: Player):
        self.__black_player = player

    @property
    def result(self) -> int:
        return self.__result

    @property
    def result_str(self) -> str:
        return RESULT_STRINGS[self.result] if self.result else ''

    def set_result(self, result: int):
        self.__result = result

    def __lt__(self, other):
        # p1 < p2 calls p1.__lt__(p2)
        if self.black_player.id == 1:
            return True
        if other.black_player.id == 1:
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
        return f'{type(self).__name__}({self.number}. {self.white_player} {self.result_str} {self.black_player})'
