from typing import List, Dict, Optional
from logging import Logger

from common.logger import get_logger
from data.result import Result
from data.screen_set import ScreenSet

logger: Logger = get_logger()

SCREEN_TYPE_BOARDS: str = 'boards'
SCREEN_TYPE_PLAYERS: str = 'players'
SCREEN_TYPE_RESULTS: str = 'results'
SCREEN_TYPE_NAMES: Dict[str, str] = {
    SCREEN_TYPE_BOARDS: 'Appariements par table',
    SCREEN_TYPE_PLAYERS: 'Appariements par joueur.euse',
    SCREEN_TYPE_RESULTS: 'Résultats',
}


class AScreen:
    def __init__(self, screen_id: str, family_id: Optional[str], name: str, type: str, columns: int,
                 menu_text: Optional[str], menu: Optional[str], show_timer: bool):
        self.__id: str = screen_id
        self.__family_id: Optional[str] = family_id
        self._name: str = name
        self.__type: str = type
        self.__columns: int = columns
        self._menu_text: Optional[str] = menu_text
        self.__menu: str = menu
        self.__show_timer: bool = show_timer
        self.__menu_screens: Optional[List[AScreen]] = None

    @property
    def id(self) -> str:
        return self.__id

    @property
    def family_id(self) -> Optional[str]:
        return self.__family_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> str:
        return self.__type

    @property
    def type_str(self) -> str:
        return '???'

    @property
    def icon_str(self) -> str:
        return 'bi-question-circle'

    @property
    def columns(self) -> int:
        return self.__columns

    @property
    def menu_text(self) -> Optional[str]:
        return self._menu_text

    @property
    def menu(self) -> Optional[str]:
        return self.__menu

    def set_menu(self, menu: str):
        self.__menu = menu

    @property
    def show_timer(self) -> bool:
        return self.__show_timer

    @property
    def menu_screens(self) -> List['AScreen']:
        return self.__menu_screens

    def set_menu_screens(self, menu_screens: List['AScreen']):
        self.__menu_screens = menu_screens

    @property
    def update(self) -> bool:
        return False

    @property
    def sets(self) -> List[ScreenSet]:
        return []


class AScreenWithSets(AScreen):
    def __init__(self, screen_id: str, family_id: Optional[str], name: str, type: str, columns: int,
                 menu_text: Optional[str], menu: Optional[str], show_timer: bool, sets: List[ScreenSet]):
        super().__init__(screen_id, family_id, name, type, columns, menu_text, menu, show_timer)
        self._sets: List[ScreenSet] = sets

    @property
    def sets(self) -> List[ScreenSet]:
        return self._sets

    @property
    def sets_str(self) -> str:
        strings: List[str] = []
        for set in self._sets:
            strings.append(str(set))
        return ' + '.join(strings)


class ScreenBoards(AScreenWithSets):
    def __init__(
            self, screen_id: str, family_id: Optional[str], name: str, columns: int, menu_text: Optional[str],
            menu: Optional[str], show_timer: bool, sets: List[ScreenSet], update: bool):
        super().__init__(screen_id, family_id, name, SCREEN_TYPE_BOARDS, columns, menu_text, menu, show_timer, sets)
        self.__update: bool = update

    @property
    def name(self) -> str:
        if self._name is None:
            return self.sets[0].name_for_boards
        return self._name

    @property
    def menu_text(self) -> Optional[str]:
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
                text = text.replace('%f', str(set.first_player_by_rating.rating))
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
        return self.__update


class ScreenPlayers(AScreenWithSets):
    def __init__(
            self, screen_id: str, family_id: Optional[str], name: str, columns: int, menu_text: Optional[str],
            menu: Optional[str], show_timer: bool, sets: List[ScreenSet]):
        super().__init__(
            screen_id, family_id, name, SCREEN_TYPE_PLAYERS, columns, menu_text, menu, show_timer, sets)

    @property
    def name(self) -> str:
        if self._name is None:
            return self._sets[0].name_for_players
        return self._name

    @property
    def menu_text(self) -> Optional[str]:
        if self._menu_text is None:
            return None
        text: str = self._menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            text = text.replace('%f', str(set.first_player_by_name.last_name)[:3])
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
            self, event_id: str, screen_id: str, family_id: Optional[str], name: str, columns: int,
            menu_text: Optional[str], menu: Optional[str], show_timer: bool, limit: int):
        super().__init__(
            screen_id, family_id, name, SCREEN_TYPE_RESULTS, columns, menu_text, menu, show_timer)
        self.__event_id = event_id
        self.__limit: int = limit

    @property
    def event_id(self) -> str:
        return self.__event_id

    @property
    def type_str(self) -> str:
        return 'Résultats'

    @property
    def icon_str(self) -> str:
        return 'bi-trophy-fill'

    @property
    def limit(self) -> int:
        return self.__limit

    @property
    def results_lists(self) -> List[List[Result]]:
        results: List[Result] = Result.get_results(self.event_id, self.limit)
        results_by_column: List[List[Result]] = []
        column_size: int = (self.limit if self.limit else len(results)) // self.columns
        for i in range(self.columns):
            results_by_column.append(results[i * column_size:(i + 1) * column_size])
        return results_by_column
