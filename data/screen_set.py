import math
from typing import Optional, List, Any, Tuple

from data.board import Board
from data.player import Player
from data.tournament import Tournament
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()


class ScreenSet:
    def __init__(self, tournament: Tournament, columns: int, first: Optional[int] = None, last: Optional[int] = None,
                 part: Optional[int] = None, parts: Optional[int] = None, name: Optional[str] = None):
        self.__tournament: Tournament = tournament
        self.__columns = columns
        self.__first: Optional[int] = first
        self.__last: Optional[int] = last
        self.__part: Optional[int] = part
        self.__parts: Optional[int] = parts
        self.__name: Optional[str] = name
        self.__first_tem: Optional[Any] = None
        self.__last_item: Optional[Any] = None
        self.__items_lists: Optional[List[List[Any]]] = None
        if self.__name is None:
            self.__name = '%t'
        self.__name = self.__name.replace('%t', tournament.name)

    @property
    def tournament(self) -> Tournament:
        return self.__tournament

    @property
    def first(self) -> Optional[int]:
        return self.__first

    @property
    def last(self) -> Optional[int]:
        return self.__last

    @property
    def part(self) -> Optional[int]:
        return self.__part

    @property
    def parts(self) -> Optional[int]:
        return self.__parts

    @property
    def name(self) -> str:
        return self.__name

    def __extract_data(self, items: List[Any], force_even: bool = False):
        if self.__items_lists is not None:
            return
        # at first select the desired items
        selected_first_index: int = 0
        selected_last_index: int = 0
        if self.first is None and self.last is None and self.part is None:
            selected_first_index = 0
            selected_last_index = len(items) - 1
        elif self.first is not None and self.last is not None:
            selected_first_index = self.first - 1
            selected_last_index = self.last
        elif self.first is not None:
            selected_first_index = self.first - 1
            selected_last_index = len(items) - 1
        elif self.last is not None:
            selected_first_index = 0
            selected_last_index = self.last
        else:  # self.part is not None
            items_number = len(items)
            q, r = divmod(items_number, self.parts * self.__columns)
            if r > 0:
                q += 1
            if force_even and q % 2 == 1:
                q += 1
            first_index: int = 0
            last_index: int
            for part in range(1, self.parts + 1):
                last_index = min(first_index + q * self.__columns, items_number)
                if part == self.part:
                    selected_first_index = first_index
                    selected_last_index = last_index
                    break
                first_index = last_index
        selected_items = items[selected_first_index:selected_last_index]
        self.__first_item = items[selected_first_index]
        self.__last_item = items[selected_last_index - 1]
        # now split in columns
        items_number = len(selected_items)
        q, r = divmod(items_number, self.__columns)
        first_index: int = 0
        last_index: int
        self.__items_lists = []
        for column in range(1, self.__columns + 1):
            last_index = first_index + q
            more: int = min(r, 1)
            last_index += more
            r -= more
            self.__items_lists.append(selected_items[first_index:last_index])
            first_index = last_index

    def __extract_boards(self):
        if self.__items_lists is None:
            self.__extract_data(self.tournament.boards, force_even=False)
            self.__name = self.__name.replace('%f', str(self.first_board.id))
            self.__name = self.__name.replace('%l', str(self.last_board.id))

    @property
    def boards_lists(self) -> List[List[Board]]:
        self.__extract_boards()
        return self.__items_lists

    @property
    def first_board(self) -> Board:
        self.__extract_boards()
        return self.__first_item

    @property
    def last_board(self) -> Board:
        self.__extract_boards()
        return self.__last_item

    def __extract_players_by_name(self):
        if self.__items_lists is None:
            self.__extract_data(self.tournament.players_by_name, force_even=False)
            self.__name = self.__name.replace('%f', self.first_player_by_name.last_name)
            self.__name = self.__name.replace('%l', self.last_player_by_name.last_name)

    @property
    def players_by_name_lists(self) -> List[List[Player]]:
        self.__extract_players_by_name()
        return self.__items_lists

    @property
    def first_player_by_name(self) -> Player:
        self.__extract_players_by_name()
        return self.__first_item

    @property
    def last_player_by_name(self) -> Player:
        self.__extract_players_by_name()
        return self.__last_item

    def __extract_players_by_rating(self):
        if self.__items_lists is None:
            self.__extract_data(self.tournament.players_by_rating, force_even=True)
            self.__name = self.__name.replace('%f', str(self.first_player_by_rating.rating))
            self.__name = self.__name.replace('%l', str(self.last_player_by_rating.rating))

    @property
    def players_by_rating_tuple_lists(self) -> List[Tuple[List[Player], List[Player]]]:
        self.__extract_players_by_rating()
        players_by_rating_lists: List[List[Player]] = self.__items_lists
        players_by_rating_tuple_lists: List[Tuple[List[Player], List[Player]]] = []
        for players_by_rating in players_by_rating_lists:
            players_by_rating_tuple_lists.append(
                (
                    players_by_rating[:math.ceil(len(players_by_rating) / 2)],
                    players_by_rating[math.ceil(len(players_by_rating) / 2):],
                ))
        return players_by_rating_tuple_lists

    @property
    def first_player_by_rating(self) -> Player:
        self.__extract_players_by_rating()
        return self.__first_item

    @property
    def last_player_by_rating(self) -> Player:
        self.__extract_players_by_rating()
        return self.__last_item

    def __str__(self):
        if self.first is None and self.last is None and self.part is None:
            return '{} (tout)'.format(self.tournament.id)
        if self.first is not None and self.last is not None:
            return '{} (de n°{} à n°{})'.format(self.tournament.id, self.first, self.last)
        if self.first is not None:
            return '{} (à partir de n°{})'.format(self.tournament.id, self.first)
        if self.last is not None:
            return '{} (jusqu\'à n°{})'.format(self.tournament.id, self.last)
        if self.part is not None:
            return '{} ({}/{})'.format(self.tournament.id, self.part, self.parts)
