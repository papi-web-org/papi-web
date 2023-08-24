from typing import List, Dict, Optional
from logging import Logger

from common.logger import get_logger
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
    def __init__(self, screen_id: str, family_id: Optional[str], name: str, type: str, columns: int, menu_text: str,
                 menu: Optional[str], show_timer: bool, sets: List[ScreenSet], enter_results: bool):
        self.__id: str = screen_id
        self.__family_id: Optional[str] = family_id
        self.__name: str = name
        self.__type: str = type
        self.__columns: int = columns
        self.__menu_text: str = menu_text
        self.__menu: str = menu
        self.__show_timer: bool = show_timer
        self.__menu_screens: Optional[List[AScreen]] = None
        self.__sets: List[ScreenSet] = sets
        self.__enter_results: bool = enter_results

    @property
    def id(self) -> str:
        return self.__id

    @property
    def family_id(self) -> Optional[str]:
        return self.__family_id

    @property
    def name(self) -> str:
        if self.__name is None:
            return self.__sets[0].name
        return self.__name

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
        return self.__menu_text

    @property
    def menu_text_boards(self) -> Optional[str]:
        if self.__menu_text is None:
            return None
        text: str = self.__menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            text = text.replace('%f', str(set.first_board.id))
            text = text.replace('%l', str(set.last_board.id))
        return text

    @property
    def menu_text_players_by_name(self) -> Optional[str]:
        if self.__menu_text is None:
            return None
        text: str = self.__menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            text = text.replace('%f', str(set.first_player_by_name.last_name)[:3])
            text = text.replace('%l', str(set.last_player_by_name.last_name)[:3])
        return text

    @property
    def menu_text_players_by_rating(self) -> Optional[str]:
        if self.__menu_text is None:
            return None
        text: str = self.__menu_text
        if self.sets:
            set: ScreenSet = self.sets[0]
            text = text.replace('%t', set.tournament.name)
            text = text.replace('%f', str(set.first_player_by_rating.rating))
            text = text.replace('%l', str(set.last_player_by_rating.rating))
        return text

    @property
    def menu(self) -> Optional[str]:
        return self.__menu

    def set_menu(self, menu: str):
        self.__menu = menu

    @property
    def show_timer(self) -> bool:
        return self.__show_timer

    @property
    def sets(self) -> List[ScreenSet]:
        return self.__sets

    @property
    def enter_results(self) -> bool:
        return self.__enter_results

    @property
    def sets_str(self) -> str:
        strings: List[str] = []
        for set in self.__sets:
            strings.append(str(set))
        return ' + '.join(strings)

    @property
    def menu_screens(self) -> List['AScreen']:
        return self.__menu_screens

    def set_menu_screens(self, menu_screens: List['AScreen']):
        self.__menu_screens = menu_screens


class ScreenBoards(AScreen):
    def __init__(
            self, screen_id: str, family_id: Optional[str], name: str, columns: int, menu_text: str,
            menu: Optional[str], show_timer: bool, sets: List[ScreenSet], enter_results: bool):
        super().__init__(
            screen_id, family_id, name, SCREEN_TYPE_BOARDS, columns, menu_text, menu, show_timer, sets,
            enter_results)

    @property
    def type_str(self) -> str:
        return 'Saisie' if self.enter_results else 'Appariements'

    @property
    def icon_str(self) -> str:
        return 'bi-pencil-fill' if self.enter_results else 'bi-card-list'


class ScreenPlayers(AScreen):
    def __init__(
            self, screen_id: str, family_id: Optional[str], name: str, columns: int, menu_text: str,
            menu: Optional[str], show_timer: bool, sets: List[ScreenSet]):
        super().__init__(
            screen_id, family_id, name, SCREEN_TYPE_PLAYERS, columns, menu_text, menu, show_timer, sets, False)

    @property
    def type_str(self) -> str:
        return 'Alphabétique'

    @property
    def icon_str(self) -> str:
        return 'bi-people-fill'


class ScreenResults(AScreen):
    def __init__(
            self, screen_id: str, family_id: Optional[str], name: str, columns: int, menu_text: str,
            menu: Optional[str], show_timer: bool):
        super().__init__(
            screen_id, family_id, name, SCREEN_TYPE_RESULTS, columns, menu_text, menu, show_timer, [], False)

    @property
    def type_str(self) -> str:
        return 'Résultats'

    @property
    def icon_str(self) -> str:
        return 'bi-trophy-fill'
