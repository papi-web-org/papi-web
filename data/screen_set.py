import json
import math
from pathlib import Path
from typing import Any, TYPE_CHECKING
from logging import Logger
from dataclasses import dataclass, field
from itertools import chain
from collections.abc import Iterable

from common.config_reader import ConfigReader, TMP_DIR
from common.logger import get_logger
from data.board import Board
from data.player import Player
from data.tournament import Tournament
from data.util import ScreenType

logger: Logger = get_logger()


@dataclass
class ScreenSet:
    event_id: str
    tournament: Tournament
    screen_id: str
    id: int
    columns: int
    show_unpaired: bool
    fixed_boards: list[int] = field(default_factory=list)
    first: int | None = field(default=None, kw_only=True)
    last: int | None = field(default=None, kw_only=True)
    part: int | None = field(default=None, kw_only=True)
    parts: int | None = field(default=None, kw_only=True)
    number: int | None = field(default=None, kw_only=True)
    name: str | None = field(default=None, kw_only=True)
    first_item: Any | None = field(default=None, init=False)
    last_item: Any | None = field(default=None, init=False)
    items_lists: list[list[Any]] | None = field(default=None, init=False)

    @property
    def name_for_boards(self) -> str | None:
        if self.tournament.current_round:
            self._extract_boards()
        else:
            self._extract_players_by_name()
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
        # _
        # first
        # first and last
        # first and number
        # last
        # part and parts
        # number
        # part and number
        # fixed_boards
        if self.fixed_boards:
            if TYPE_CHECKING:
                assert all(isinstance(item, Board) for item in items)
            selected_items = [
                board for board in items
                if board.number in self.fixed_boards
            ]
            selected_first_index = 0
            selected_last_index = len(selected_items)
        else:
            if self.first is not None:
                selected_first_index = self.first - 1
                if self.last is not None:
                    # first and last
                    selected_last_index = min(self.last, len(items))
                elif self.number is not None:
                    # first and number
                    selected_last_index = selected_first_index + self.number
                else:
                    # first
                    selected_last_index = len(items)
            elif self.last is not None:
                # last
                selected_first_index = 0
                selected_last_index = self.last
            elif self.parts is not None:
                # part and parts
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
            elif self.part is not None:
                # part and number
                selected_first_index = min(self.number * (self.part - 1), len(items))
                selected_last_index = min(selected_first_index + self.number, len(items))
            elif self.number is not None:
                # number
                selected_first_index = 0
                selected_last_index = min(self.number, len(items))
            else:
                # _
                selected_first_index = 0
                selected_last_index = len(items)
            selected_items = items[selected_first_index:selected_last_index]
            self.first_item = items[selected_first_index]
            self.last_item = items[selected_last_index - 1]
        # now split in columns
        items_number = len(selected_items)
        q, r = divmod(items_number, self.columns)
        first_index = 0
        self.items_lists = []
        for _ in range(1, self.columns + 1):
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
                if self.first or self.last or self.part or self.number:
                    self.name = 'Ech. %f à %l'
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
        if TYPE_CHECKING:
            assert (
                isinstance(self.items_lists, list) and
                all(isinstance(item, list) for item in self.items_lists) and
                all(
                    isinstance(item, Board) for item in chain.from_iterable(*self.items_lists)
                )
            )
        return self.items_lists

    @property
    def first_board(self) -> Board:
        self._extract_boards()
        if TYPE_CHECKING:
            assert isinstance(self.first_item, Board)
        return self.first_item

    @property
    def last_board(self) -> Board:
        self._extract_boards()
        if TYPE_CHECKING:
            assert isinstance(self.last_item, Board)
        return self.last_item

    def _extract_players_by_name(self):
        if self.items_lists is None:
            if self.show_unpaired:
                self._extract_data(self.tournament.players_by_name_with_unpaired, force_even=False)
            else:
                self._extract_data(self.tournament.players_by_name_without_unpaired, force_even=False)
            if self.name is None:
                if self.first or self.last or self.part or self.number:
                    self.name = '%f à %l'
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
        if TYPE_CHECKING:
            assert (
                isinstance(self.items_lists, list) and
                all(isinstance(item, list) for item in self.items_lists) and
                all(
                    isinstance(item, Player)
                    for item in chain.from_iterable(*self.items_lists)
                )
            )
        return self.items_lists

    @property
    def players_by_name_tuple_lists(self) -> Iterable[tuple[list[Player], list[Player]]]:
        self._extract_players_by_name()
        if TYPE_CHECKING:
            assert (
                isinstance(self.items_lists, list) and
                all(isinstance(item, list) for item in self.items_lists) and
                all(
                    isinstance(item, Player)
                    for item in chain.from_iterable(*self.items_lists)
                )
            )
        players_by_name_lists: list[list[Player]] = self.items_lists
        for players_by_name in players_by_name_lists:
            yield (
                players_by_name[: (bound := math.ceil(len(players_by_name) / 2))],
                players_by_name[bound:]
            )

    @property
    def first_player_by_name(self) -> Player:
        self._extract_players_by_name()
        if TYPE_CHECKING:
            assert isinstance(self.first_item, Player)
        return self.first_item

    @property
    def last_player_by_name(self) -> Player:
        self._extract_players_by_name()
        if TYPE_CHECKING:
            assert isinstance(self.last_item, Player)
        return self.last_item

    @classmethod
    def __get_screen_set_file_dependencies_file(cls, event_id: str, screen_id: str, screen_set_id: int) -> Path:
        return TMP_DIR / 'events' / event_id / 'screen_set_file_dependencies' / f'{screen_id}_{screen_set_id}.json'

    @classmethod
    def get_screen_set_file_dependencies(cls, event_id: str, screen_id: str, screen_set_id: int) -> list[Path]:
        file_dependencies_file = cls.__get_screen_set_file_dependencies_file(event_id, screen_id, screen_set_id)
        try:
            with open(file_dependencies_file, 'r', encoding='utf-8') as f:
                return [Path(file) for file in json.load(f)]
        except FileNotFoundError:
            return []

    def set_file_dependencies(self, files: list[Path]):
        file_dependencies_file = self.__get_screen_set_file_dependencies_file(self.event_id, self.screen_id, self.id)
        try:
            file_dependencies_file.parents[0].mkdir(parents=True, exist_ok=True)
            with open(file_dependencies_file, 'w', encoding='utf-8') as f:
                return f.write(json.dumps([str(file) for file in files]))
        except FileNotFoundError:
            return []

    def __str__(self):
        if self.fixed_boards:
            return f"{self.tournament.id} (tables fixes {', '.join(self.fixed_boards)})"
        elif self.first is not None:
            if self.last is not None:
                # first and last
                return f'{self.tournament.id} (de n°{self.first} à n°{self.last})'
            elif self.number is not None:
                # first and number
                return f'{self.tournament.id} ({self.number} à partir de n°{self.first})'
            else:
                # first
                return f'{self.tournament.id} (à partir de n°{self.first})'
        elif self.last is not None:
            # last
            return f'{self.tournament.id} (jusqu\'à n°{self.last})'
        elif self.parts is not None:
            # part and parts
            return f'{self.tournament.id} ({self.part}/{self.parts})'
        elif self.part is not None:
            # part and number
            return f'{self.tournament.id} ({self.number}, partie n°{self.part})'
        elif self.number is not None:
            # number
            return f'{self.tournament.id} ({self.number} à partir de n°1)'
        else:
            # _
            return f'{self.tournament.id} (tout)'


class ScreenSetBuilder:
    def __init__(self, config_reader: ConfigReader, event_id: str, tournaments: dict[str, Tournament], screen_id: str,
                 screen_type: ScreenType, columns: int, show_unpaired: bool):
        self._config_reader = config_reader
        self.event_id: str = event_id
        self._tournaments: dict[str, Tournament] = tournaments
        self.screen_id: str = screen_id
        self.screen_set_id: int = 0
        self.screen_section_key: str = f'screen.{self.screen_id}'
        self.screen_type: ScreenType = screen_type
        self.columns: int = columns
        self.show_unpaired = show_unpaired
        self.screen_sets = []
        self.fixed_boards: list[int] = []
        for screen_set_section_key in self._read_screen_set_section_keys():
            if screen_set := self._build_screen_set(screen_set_section_key):
                self.screen_sets.append(screen_set)

    def _read_screen_set_section_keys(self) -> list[str]:
        screen_set_section_keys: list[str]
        screen_set_single_section_key = f'{self.screen_section_key}.{self.screen_type.value}'
        if screen_set_single_section_key in self._config_reader:
            screen_set_section_keys = [screen_set_single_section_key, ]
            for screen_set_sub_section_key in self._config_reader.get_subsection_keys_with_prefix(
                    screen_set_single_section_key):
                self._config_reader.add_warning(
                    'rubrique non prise en compte, supprimez la rubrique '
                    f'[{screen_set_single_section_key}] pour cela',
                    f'{screen_set_single_section_key}.{screen_set_sub_section_key}'
                )
        else:
            screen_set_section_keys = [
                f'{screen_set_single_section_key}.{sub_section_key}'
                for sub_section_key
                in self._config_reader.get_subsection_keys_with_prefix(screen_set_single_section_key)
            ]
        if not screen_set_section_keys:
            if len(self._tournaments) == 1:
                self._config_reader[screen_set_single_section_key] = {}
                screen_set_section_keys.append(screen_set_single_section_key)
                self._config_reader.add_info(
                    f'un seul tournoi, la rubrique [{screen_set_single_section_key}] a été ajoutée',
                    self.screen_section_key)
            else:
                self._config_reader.add_warning('rubrique absente, écran ignoré', screen_set_single_section_key)
        return screen_set_section_keys

    def _build_screen_set(self, screen_set_section_key: str) -> ScreenSet | None:
        try:
            current_section = self._config_reader[screen_set_section_key]
        except KeyError:
            self._config_reader.add_error('rubrique non trouvée', screen_set_section_key)
            return None
        key = 'tournament'
        if key not in current_section:
            if len(self._tournaments) == 1:
                current_section[key] = list(self._tournaments.keys())[0]
            else:
                self._config_reader.add_warning(
                    'option absente, partie d\'écran ignorée',
                    screen_set_section_key,
                    key
                )
                return None
        tournament_id: str = self._config_reader.get(screen_set_section_key, key)
        try:
            tournament: Tournament = self._tournaments[tournament_id]
        except KeyError:
            self._config_reader.add_warning(
                f"le tournoi [{tournament_id}] n'existe pas, partie d\'écran ignorée",
                screen_set_section_key,
                key
            )
            return None
        if not tournament.file:
            self._config_reader.add_warning(
                f"le fichier du tournoi [{tournament.id}] n'est pas "
                f"défini, partie d\'écran ignorée",
                screen_set_section_key,
                key
            )
            return None
        if not tournament.file.exists():
            self._config_reader.add_warning(
                f"le fichier du tournoi [{tournament.id}] ({tournament.file}) n'existe pas, "
                f"partie d\'écran ignorée",
                screen_set_section_key,
                key
            )
            return None
        # at first check that the options have valid values
        key = 'first'
        first: int | None = None
        if key in current_section:
            first = self._config_reader.getint_safe(screen_set_section_key, key, minimum=1)
            if first is None:
                self._config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    screen_set_section_key,
                    key
                )
        key = 'last'
        last: int | None = None
        if key in current_section:
            last = self._config_reader.getint_safe(screen_set_section_key, key)
            if last is None:
                self._config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    screen_set_section_key,
                    key
                )
        key = 'part'
        part: int | None = None
        if key in current_section:
            part = self._config_reader.getint_safe(screen_set_section_key, key)
            if part is None:
                self._config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    screen_set_section_key,
                    key
                )
        key = 'parts'
        parts: int | None = None
        if key in current_section:
            parts = self._config_reader.getint_safe(screen_set_section_key, key)
            if parts is None:
                self._config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    screen_set_section_key,
                    key
                )
        key = 'number'
        number: int | None = None
        if key in current_section:
            number = self._config_reader.getint_safe(screen_set_section_key, key)
            if number is None:
                self._config_reader.add_warning(
                    'un entier positif non nul est attendu, option ignorée',
                    screen_set_section_key,
                    key
                )
        key = 'fixed_boards'
        fixed_boards: list[int] = []
        if key in current_section:
            all_fixed = self._config_reader.getboolean_safe(screen_set_section_key, key)
            if all_fixed:
                fixed_boards = [
                    player.fixed for player in tournament.players_by_id
                    if player.fixed != 0
                ]
            boards_to_parse = list(map(str.strip, current_section[key].split(',')))
            for board in boards_to_parse:
                try:
                    fixed_boards.append(int(board))
                except ValueError:
                    self._config_reader.add_warning(
                        f'un entier positif est attendu, échiquier [{board}] ignoré',
                        screen_set_section_key, key)
        # then check that the values are coherent
        if first is not None and last is not None and first > last:
            self._config_reader.add_warning(f'intervalle [{first}-{last}] non valide, partie d\'écran ignorée',
                                            screen_set_section_key)
            return None
        if part is not None and parts is not None and part > parts:
            self._config_reader.add_warning(f"la partie [{part}] sur [{parts}] n'est pas valide, "
                                            f"partie d\'écran ignorée", screen_set_section_key)
            return None
        # eventually check that options are all compatible
        if fixed_boards and (first, last, part, parts, number) != (None,) * 5:
                self._config_reader.add_warning(
                    "l'option [fixed_boards] est incompatible avec les options"
                    " [first], [last], [part], [parts] et [number], partie"
                    " d'écran ignorée",
                    screen_set_section_key)
        elif first is not None:
            # first is set
            if last is not None and number is not None:
                self._config_reader.add_warning('les options [last] et [number] ne peuvent pas être utilisées '
                                                'en même temps, partie d\'écran ignorée', screen_set_section_key)
                return None
            if part is not None or parts is not None:
                self._config_reader.add_warning('les options [part] et [parts] ne peuvent pas être utilisées '
                                                'en même temps que l\'option [first], partie d\'écran ignorée',
                                                screen_set_section_key)
                return None
            # here we have: first | first + last | first + number
        else:
            # first is not set
            if last is not None:
                # first and last are not set
                if part is not None or parts is not None or number is not None:
                    self._config_reader.add_warning('l\'option [last] n\'est pas compatible avec les options '
                                                    '[part], [parts] ou [number], partie d\'écran ignorée',
                                                    screen_set_section_key)
                    return None
                # here we have: last
            else:
                # first and last are not set
                if parts is not None and number is not None:
                    self._config_reader.add_warning('les options [parts] et [number] ne peuvent pas être utilisées '
                                                    'en même temps, partie d\'écran ignorée', screen_set_section_key)
                    return None
                if part is not None:
                    if parts is None and number is None:
                        self._config_reader.add_warning('l\'option [part] doit être utilisée avec une des options '
                                                        '[parts] ou [number], partie d\'écran ignorée',
                                                        screen_set_section_key)
                        return None
                else:
                    if parts is not None:
                        self._config_reader.add_warning('l\'option [parts] ne peut pas être utilisée sans '
                                                        'l\'option [part], partie d\'écran ignorée',
                                                        screen_set_section_key)
                        return None
                    if number is not None:
                        self._config_reader.add_warning('l\'option [number] ne peut pas être utilisée sans '
                                                        'une des options [first] ou [part], partie d\'écran ignorée',
                                                        screen_set_section_key)
                        return None
                # here we have _ | number | part + parts | part + number
        # at this stage, the following options are correctly set :
        # _
        # first
        # first and last
        # last
        # first and number
        # number
        # part and parts
        # part and number
        key = 'name'
        name: str | None = None
        if key in current_section:
            name = self._config_reader.get(screen_set_section_key, key)
        for key, _ in self._config_reader.items(screen_set_section_key):
            if key not in self._config_reader.screen_set_keys:
                self._config_reader.add_warning('option inconnue', screen_set_section_key, key)
        screen_set: ScreenSet = ScreenSet(
            self.event_id,
            self._tournaments[tournament_id],
            self.screen_id,
            self.screen_set_id,
            self.columns,
            self.show_unpaired,
            fixed_boards=fixed_boards,
            first=first,
            last=last,
            part=part,
            parts=parts,
            name=name,
            number=number)
        self.screen_set_id += 1
        return screen_set
