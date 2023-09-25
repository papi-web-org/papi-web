import math
from typing import Any
from logging import Logger

from common.logger import get_logger
from data.board import Board
from data.player import Player
from data.tournament import Tournament

logger: Logger = get_logger()


class ScreenSet:
    def __init__(self, tournament: Tournament, columns: int, first: int | None = None, last: int | None = None,
                 part: int | None = None, parts: int | None = None, name: str | None = None):
        self.__tournament: Tournament = tournament
        self.__columns = columns
        self.__first: int | None = first
        self.__last: int | None = last
        self.__part: int | None = part
        self.__parts: int | None = parts
        self.__name: str | None = name
        self.__first_item: Any | None = None
        self.__last_item: Any | None = None
        self.__items_lists: list[list[Any]] | None = None

    @property
    def tournament(self) -> Tournament:
        return self.__tournament

    @property
    def first(self) -> int | None:
        return self.__first

    @property
    def last(self) -> int | None:
        return self.__last

    @property
    def part(self) -> int | None:
        return self.__part

    @property
    def parts(self) -> int | None:
        return self.__parts

    @property
    def name(self) -> str:
        return self.__name

    @property
    def name_for_boards(self) -> str:
        if self.tournament.current_round:
            self.__extract_boards()
        else:
            self.__extract_players_by_rating()
        return self.__name

    @property
    def name_for_players(self) -> str:
        self.__extract_players_by_name()
        return self.__name

    def __extract_data(self, items: list[Any], force_even: bool = False):
        if not items:
            self.__items_lists = [[], ] * self.__columns
            return
        # at first select the desired items
        selected_first_index: int = 0
        selected_last_index: int = 0
        if self.first is None and self.last is None and self.part is None:
            selected_first_index = 0
            selected_last_index = len(items)
        elif self.first is not None and self.last is not None:
            selected_first_index = self.first - 1
            selected_last_index = self.last
        elif self.first is not None:
            selected_first_index = self.first - 1
            selected_last_index = len(items)
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
            if self.__name is None:
                if self.first or self.last or self.part:
                    self.__name = '%t [%f à %l]'
                else:
                    self.__name = '%t'
            self.__name = self.__name.replace('%t', str(self.tournament.name))
            if self.first_board:
                self.__name = self.__name.replace('%f', str(self.first_board.id))
            if self.last_board:
                self.__name = self.__name.replace('%l', str(self.last_board.id))

    @property
    def boards_lists(self) -> list[list[Board]]:
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
            if self.__name is None:
                if self.first or self.last or self.part:
                    self.__name = '%t %f à %l'
                else:
                    self.__name = '%t'
            self.__name = self.__name.replace('%t', str(self.tournament.name))
            if self.first_player_by_name:
                self.__name = self.__name.replace('%f', self.first_player_by_name.last_name)
            if self.last_player_by_name:
                self.__name = self.__name.replace('%l', self.last_player_by_name.last_name)

    @property
    def players_by_name_lists(self) -> list[list[Player]]:
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
            if self.__name is None:
                if self.first or self.last or self.part:
                    self.__name = '%t %f à %l'
                else:
                    self.__name = '%t'
            self.__name = self.__name.replace('%t', str(self.tournament.name))
            if self.first_player_by_rating:
                self.__name = self.__name.replace('%f', str(self.first_player_by_rating.rating))
            if self.last_player_by_rating:
                self.__name = self.__name.replace('%l', str(self.last_player_by_rating.rating))

    @property
    def players_by_rating_tuple_lists(self) -> list[tuple[list[Player], list[Player]]]:
        self.__extract_players_by_rating()
        players_by_rating_lists: list[list[Player]] = self.__items_lists
        players_by_rating_tuple_lists: list[tuple[list[Player], list[Player]]] = []
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
            return f'{self.tournament.id} (tout)'
        if self.first is not None and self.last is not None:
            return f'{self.tournament.id} (de n°{self.first} à n°{self.last})'
        if self.first is not None:
            return f'{self.tournament.id} (à partir de n°{self.first})'
        if self.last is not None:
            return f'{self.tournament.id} (jusqu\'à n°{self.last})'
        if self.part is not None:
            return f'{self.tournament.id} ({self.part}/{self.parts})'
