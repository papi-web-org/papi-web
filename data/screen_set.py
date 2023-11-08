import math
from typing import Any
from logging import Logger
from dataclasses import dataclass, field

from common.config_reader import ConfigReader
from common.logger import get_logger
from data.board import Board
from data.player import Player
from data.tournament import Tournament
from data.util import ScreenType

logger: Logger = get_logger()


@dataclass
class ScreenSet:
    tournament: Tournament
    columns: int
    first: int | None = field(default=None, kw_only=True)
    last: int | None = field(default=None, kw_only=True)
    part: int | None = field(default=None, kw_only=True)
    parts: int | None = field(default=None, kw_only=True)
    name: str | None = field(default=None, kw_only=True)
    first_item: Any | None = field(default=None, init=False)
    last_item: Any | None = field(default=None, init=False)
    items_lists: list[list[Any]] | None = field(default=None, init=False)

    @property
    def name_for_boards(self) -> str | None:
        if self.tournament.current_round:
            self._extract_boards()
        else:
            self._extract_players_by_rating()
        return self.name

    @property
    def name_for_players(self) -> str | None:
        self._extract_players_by_name()
        return self.name

    def _extract_data(self, items: list[Any], force_even: bool = False):
        if not items:
            self.items_lists = [[], ] * self.columns
            return
        # at first select the desired items
        selected_first_index: int = 0
        selected_last_index: int = 0
        first_index: int
        last_index: int
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
            q, r = divmod(items_number, self.parts * self.columns)
            if r > 0:
                q += 1
            if force_even and q % 2 == 1:
                q += 1
            first_index = 0
            for part in range(1, self.parts + 1):
                last_index = min(first_index + q * self.columns, items_number)
                if part == self.part:
                    selected_first_index = first_index
                    selected_last_index = last_index
                    break
                first_index = last_index
        selected_items = items[selected_first_index:selected_last_index]
        self.first_item = items[selected_first_index]
        self.last_item = items[selected_last_index - 1]
        # now split in columns
        items_number = len(selected_items)
        q, r = divmod(items_number, self.columns)
        first_index = 0
        self.items_lists = []
        for column in range(1, self.columns + 1):
            last_index = first_index + q
            more: int = min(r, 1)
            last_index += more
            r -= more
            self.items_lists.append(selected_items[first_index:last_index])
            first_index = last_index

    def _extract_boards(self):
        if self.items_lists is None:
            self._extract_data(self.tournament.boards, force_even=False)
            if self.name is None:
                if self.first or self.last or self.part:
                    self.name = '%t [%f à %l]'
                else:
                    self.name = '%t'
            self.name = self.name.replace('%t', str(self.tournament.name))
            if self.first_board:
                self.name = self.name.replace('%f', str(self.first_board.id))
            if self.last_board:
                self.name = self.name.replace('%l', str(self.last_board.id))

    @property
    def boards_lists(self) -> list[list[Board]]:
        self._extract_boards()
        return self.items_lists

    @property
    def first_board(self) -> Board:
        self._extract_boards()
        return self.first_item

    @property
    def last_board(self) -> Board:
        self._extract_boards()
        return self.last_item

    def _extract_players_by_name(self):
        if self.items_lists is None:
            self._extract_data(self.tournament.players_by_name, force_even=False)
            if self.name is None:
                if self.first or self.last or self.part:
                    self.name = '%t %f à %l'
                else:
                    self.name = '%t'
            self.name = self.name.replace('%t', str(self.tournament.name))
            if self.first_player_by_name:
                self.name = self.name.replace('%f', self.first_player_by_name.last_name)
            if self.last_player_by_name:
                self.name = self.name.replace('%l', self.last_player_by_name.last_name)

    @property
    def players_by_name_lists(self) -> list[list[Player]]:
        self._extract_players_by_name()
        return self.items_lists

    @property
    def first_player_by_name(self) -> Player:
        self._extract_players_by_name()
        return self.first_item

    @property
    def last_player_by_name(self) -> Player:
        self._extract_players_by_name()
        return self.last_item

    def _extract_players_by_rating(self):
        if self.items_lists is None:
            self._extract_data(self.tournament.players_by_rating, force_even=True)
            if self.name is None:
                if self.first or self.last or self.part:
                    self.name = '%t %f à %l'
                else:
                    self.name = '%t'
            self.name = self.name.replace('%t', str(self.tournament.name))
            if self.first_player_by_rating:
                self.name = self.name.replace('%f', str(self.first_player_by_rating.rating))
            if self.last_player_by_rating:
                self.name = self.name.replace('%l', str(self.last_player_by_rating.rating))

    @property
    def players_by_rating_tuple_lists(self) -> list[tuple[list[Player], list[Player]]]:
        self._extract_players_by_rating()
        players_by_rating_lists: list[list[Player]] = self.items_lists
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
        self._extract_players_by_rating()
        return self.first_item

    @property
    def last_player_by_rating(self) -> Player:
        self._extract_players_by_rating()
        return self.last_item

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


class ScreenSetBuilder:
    def __init__(self, config_reader: ConfigReader, tournaments: dict[str, Tournament]):
        self.config_reader = config_reader
        self.tournaments: dict[str, Tournament] = tournaments

    def read_screen_set_section_keys(self, screen_section_key: str, screen_type: ScreenType) -> list[str]:
        screen_set_section_keys: list[str]
        screen_set_single_section_key = f'{screen_section_key}.{screen_type.value}'
        if screen_set_single_section_key in self.config_reader:
            screen_set_section_keys = [screen_set_single_section_key, ]
            for screen_set_sub_section_key in self.config_reader.get_subsection_keys_with_prefix(
                    screen_set_single_section_key):
                self.config_reader.add_warning(
                    'rubrique non prise en compte, supprimez la rubrique '
                    f'[{screen_set_single_section_key}] pour cela',
                    f'{screen_set_single_section_key}.{screen_set_sub_section_key}'
                )
        else:
            screen_set_section_keys = [
                f'{screen_set_single_section_key}.{sub_section_key}'
                for sub_section_key
                in self.config_reader.get_subsection_keys_with_prefix(screen_set_single_section_key)
            ]
        if not screen_set_section_keys:
            if len(self.tournaments) == 1:
                self.config_reader[screen_set_single_section_key] = {}
                screen_set_section_keys.append(screen_set_single_section_key)
                self.config_reader.add_info(
                    'un seul tournoi, la rubrique [{screen_set_single_section_key}] a été ajoutée',
                    screen_section_key
                )
            else:
                self.config_reader.add_warning('rubrique absente, écran ignoré', screen_set_single_section_key)
        return screen_set_section_keys

    def build_screen_set(self, section_key: str, columns: int) -> ScreenSet | None:
        try:
            current_section = self.config_reader[section_key]
        except KeyError:
            self.config_reader.add_error('rubrique non trouvée', section_key)
            return None
        key = 'tournament'
        if key not in current_section:
            if len(self.tournaments) == 1:
                current_section[key] = list(self.tournaments.keys())[0]
            else:
                self.config_reader.add_warning(
                    'option absente, partie d\'écran ignorée',
                    section_key,
                    key
                )
                return None
        tournament_id: str = self.config_reader.get(section_key, key)
        if tournament_id not in self.tournaments:
            self.config_reader.add_warning(
                f"le tournoi [{tournament_id}] n'existe pas, partie d\'écran ignorée",
                section_key,
                key
            )
            return None
        if not self.tournaments[tournament_id].file:
            self.config_reader.add_warning(
                f"le fichier du tournoi [{tournament_id}] n'existe pas, partie d\'écran ignorée",
                section_key,
                key
            )
            return None
        if (
            ('first' in current_section or 'last' in current_section) and
            ('part' in current_section or 'parts' in current_section)
        ):
            self.config_reader.add_warning(
                'les options [part]/[parts] et [first]/[last] ne sont pas compatibles, partie d\'écran ignorée',
                section_key
            )
            return None
        key = 'first'
        first: int | None = None
        if key in current_section:
            first = self.config_reader.getint_safe(section_key, key, minimum=1)
            if first is None:
                self.config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    section_key,
                    key
                )
        key = 'last'
        last: int | None = None
        if key in current_section:
            last = self.config_reader.getint_safe(section_key, key)
            if last is None:
                self.config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    section_key,
                    key
                )
        if first is not None and last is not None and first > last:
            self.config_reader.add_warning(
                f'intervalle [{first}-{last}] non valide, partie d\'écran ignorée',
                section_key
            )
            return None
        key = 'part'
        part: int | None = None
        if key in current_section:
            part = self.config_reader.getint_safe(section_key, key)
            if part is None:
                self.config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    section_key,
                    key
                )
        key = 'parts'
        parts: int | None = None
        if key in current_section:
            parts = self.config_reader.getint_safe(section_key, key)
            if parts is None:
                self.config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    section_key,
                    key
                )
        if (
            (part is None and parts is not None) or
            (part is not None and parts is None)
        ):
            self.config_reader.add_warning(
                'les options [part]/[parts] sont obligatoires ensemble, partie d\'écran ignorée',
                section_key
            )
            return None
        if part is not None and parts is not None:
            if part > parts:
                self.config_reader.add_warning(
                    f"la partie [{part}] sur [{parts}] n'est pas valide, partie d\'écran ignorée",
                    section_key
                )
                return None
        key = 'name'
        name: str | None = None
        if key in current_section:
            name = self.config_reader.get(section_key, key)
        for key, value in self.config_reader.items(section_key):
            if key not in self.config_reader.screen_set_keys:
                self.config_reader.add_warning('option inconnue', section_key, key)
        return ScreenSet(
            self.tournaments[tournament_id],
            columns,
            first=first,
            last=last,
            part=part,
            parts=parts,
            name=name)
