import warnings
from dataclasses import dataclass, field
from enum import StrEnum, auto
from logging import Logger
from typing import Self

from common.logger import get_logger
from data.result import Result
from data.screen_set import ScreenSet

logger: Logger = get_logger()


class ScreenType(StrEnum):
    Boards = auto()
    Players = auto()
    Results = auto()

    def __str__(self):
        match self:
            case ScreenType.Boards:
                return "Appariements par table"
            case ScreenType.Players:
                return "Appariements par joueur.euse"
            case ScreenType.Results:
                return "Résultats"
            case _:
                raise ValueError

    @classmethod
    def from_str(cls, value) -> Self:
        match value:
            case 'boards':
                return cls.Boards
            case 'players':
                return cls.Players
            case 'results':
                return cls.Results
            case _:
                raise ValueError(f'Invalid board type: {value}')

    @classmethod
    def names(cls) -> list[str]:
        return [member.value for member in iter(cls)]


@dataclass
class AScreen:
    screen_id: str
    family_id: str | None
    _name: str
    _type: ScreenType | None = field(init=False)
    columns: int
    _menu_text: str | None
    menu: str
    show_timer: bool
    menu_screens: list['AScreen'] | None = field(default=None, init=False)

    def __post_init__(self):
        self._type = None

    @property
    def id(self) -> str:
        return self.screen_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> ScreenType | None:
        return self._type

    @property
    def type_str(self) -> str:
        return '???'

    @property
    def icon_str(self) -> str:
        return 'bi-question-circle'

    @property
    def menu_text(self) -> str | None:
        return self._menu_text

    def set_menu(self, menu: str):
        warnings.warn("Use direct assigment to menu instead")
        self.menu = menu

    def set_menu_screens(self, menu_screens: list['AScreen']):
        warnings.warn("Use direct assigment to menu_screens instead")
        self.menu_screens = menu_screens

    @property
    def update(self) -> bool:
        return False

    @property
    def sets(self) -> list[ScreenSet]:
        return []


@dataclass
class AScreenWithSets(AScreen):
    _sets: list[ScreenSet]

    @property
    def sets(self) -> list[ScreenSet]:
        return self._sets

    @property
    def sets_str(self) -> str:
        strings: list[str] = []
        for set in self._sets:
            strings.append(str(set))
        return ' + '.join(strings)


@dataclass
class ScreenBoards(AScreenWithSets):
    _update: bool

    def __post_init__(self):
        self._type = ScreenType.Boards

    @property
    def name(self) -> str:
        if self._name is None:
            return self.sets[0].name_for_boards
        return self._name

    @property
    def menu_text(self) -> str | None:
        if self._menu_text is None:
            return None
        text: str = self._menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            if set.tournament.current_round:
                text = text.replace('%f', str(set.first_board.id))
                text = text.replace('%l', str(set.last_board.id))
            else:
                if set.first_player_by_rating:
                    text = text.replace('%f', str(set.first_player_by_rating.rating))
                if set.last_player_by_rating:
                    text = text.replace('%l', str(set.last_player_by_rating.rating))
        return text

    @property
    def type_str(self) -> str:
        return 'Saisie' if self.update else 'Appariements'

    @property
    def icon_str(self) -> str:
        return 'bi-pencil-fill' if self.update else 'bi-card-list'

    @property
    def update(self) -> bool:
        return self._update


@dataclass
class ScreenPlayers(AScreenWithSets):

    def __post_init__(self):
        self._type = ScreenType.Players

    @property
    def name(self) -> str:
        if self._name is None:
            return self._sets[0].name_for_players
        return self._name

    @property
    def menu_text(self) -> str | None:
        if self._menu_text is None:
            return None
        text: str = self._menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            if set.first_player_by_name:
                text = text.replace('%f', str(set.first_player_by_name.last_name)[:3])
            if set.last_player_by_name:
                text = text.replace('%l', str(set.last_player_by_name.last_name)[:3])
        return text

    @property
    def type_str(self) -> str:
        return 'Alphabétique'

    @property
    def icon_str(self) -> str:
        return 'bi-people-fill'


class ScreenResults(AScreen):
    def __init__(
            self, event_id: str, screen_id: str, family_id: str | None, name: str, columns: int,
            menu_text: str | None, menu: str, show_timer: bool, limit: int):
        super().__init__(
            screen_id, family_id, name, columns, menu_text, menu, show_timer)
        self._type = ScreenType.Results
        self.event_id = event_id
        self.limit: int = limit

    @property
    def type_str(self) -> str:
        return 'Résultats'

    @property
    def icon_str(self) -> str:
        return 'bi-trophy-fill'

    @property
    def results_lists(self) -> list[list[Result]]:
        results: list[Result] = Result.get_results(self.event_id, self.limit)
        results_by_column: list[list[Result]] = []
        column_size: int = (self.limit if self.limit else len(results)) // self.columns
        for i in range(self.columns):
            results_by_column.append(results[i * column_size:(i + 1) * column_size])
        return results_by_column
