from logging import Logger
from dataclasses import dataclass, field
import warnings

from common.logger import get_logger
from data.result import Result
from data.screen_set import ScreenSet

logger: Logger = get_logger()

# TODO(Amaras) Change those constants into an Enum
SCREEN_TYPE_BOARDS: str = 'boards'
SCREEN_TYPE_PLAYERS: str = 'players'
SCREEN_TYPE_RESULTS: str = 'results'
SCREEN_TYPE_NAMES: dict[str, str] = {
    SCREEN_TYPE_BOARDS: 'Appariements par table',
    SCREEN_TYPE_PLAYERS: 'Appariements par joueur.euse',
    SCREEN_TYPE_RESULTS: 'Résultats',
}


@dataclass
class AScreen:
    screen_id: str
    family_id: str | None
    _name: str
    _type: str = field(init=False)
    columns: int
    _menu_text: str | None
    menu: str
    show_timer: bool
    menu_screens: list['AScreen'] | None = field(default=None, init=False)

    def __post_init__(self):
        self._type = '???'

    @property
    def id(self) -> str:
        return self.screen_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> str:
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
        self._type = SCREEN_TYPE_BOARDS

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
        self._type = SCREEN_TYPE_PLAYERS

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
        self._type = SCREEN_TYPE_RESULTS
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
