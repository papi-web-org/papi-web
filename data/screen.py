from collections.abc import Iterator
from functools import cached_property
from logging import Logger
from typing import Self
from typing import TYPE_CHECKING

from common import format_timestamp_date_time
from common.background import inline_image_url
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.result import Result
from data.screen_set import ScreenSet
from data.timer import Timer
from data.util import ScreenType
from database.sqlite import EventDatabase
from database.store import StoredScreen

if TYPE_CHECKING:
    from data.event import Event

logger: Logger = get_logger()

DEFAULT_SHOW_UNPAIRED: bool = False


class Screen:
    """A data wrapper around a stored screen."""
    def __init__(
            self,
            event: 'Event',
            stored_screen: StoredScreen | None = None,
            family: 'NewFamily | None' = None,
            family_part: int | None = None,
    ):
        if stored_screen is None:
            assert family is not None and family_part is not None, \
                   f'screen={stored_screen}, family={family}, family_part={family_part}'
        else:
            assert family is None and family_part is None, \
                   f'screen={stored_screen}, family={family}, family_part={family_part}'
        self.event: 'Event' = event
        self.stored_screen: StoredScreen | None = stored_screen
        self.menu_screens: list[Self] = []
        self.family: 'NewFamily | None' = family
        self.family_part: int | None = family_part
        self.screen_sets_by_id: dict[int, ScreenSet] = {}
        self._build_screen_sets()

    def _build_screen_sets(self):
        match self.type:
            case ScreenType.Boards | ScreenType.Input | ScreenType.Players:
                if self.stored_screen:
                    for stored_screen_set in self.stored_screen.stored_screen_sets:
                        screen_set: ScreenSet = ScreenSet(self, stored_screen_set=stored_screen_set)
                        self.screen_sets_by_id[screen_set.id] = screen_set
                else:
                    screen_set: ScreenSet = ScreenSet(self, family=self.family, family_part=self.family_part)
                    self.screen_sets_by_id[screen_set.id] = screen_set
            case ScreenType.Results | ScreenType.Image:
                pass
            case _:
                raise ValueError(f'type=[{self.type}]')

    @property
    def id(self) -> int:
        return self.stored_screen.id if self.stored_screen else -1

    @property
    def family_id(self) -> int | None:
        return self.family.id if self.family else None

    @property
    def type(self) -> ScreenType:
        return ScreenType.from_str(self.stored_screen.type) if self.stored_screen else self.family.type

    @property
    def public(self) -> bool:
        return self.stored_screen.public if self.stored_screen else self.family.public

    @property
    def uniq_id(self) -> str:
        return self.stored_screen.uniq_id if self.stored_screen else f'{self.family.uniq_id}:{self.family_part:03}'

    @property
    def name(self) -> str:
        if self.stored_screen:
            if self.stored_screen.name:
                return self.stored_screen.name
        match self.type:
            case ScreenType.Boards | ScreenType.Input:
                return self.screen_sets_sorted_by_order[0].name_for_boards
            case ScreenType.Players:
                return self.screen_sets_sorted_by_order[0].name_for_players
            case ScreenType.Results:
                return 'Derniers résultats'
            case ScreenType.Image:
                return 'Image'
            case _:
                raise ValueError(f'type=[{self.type}]')

    @property
    def columns(self) -> int:
        if self.stored_screen:
            if self.stored_screen.columns:
                return self.stored_screen.columns
            else:
                return 1
        else:
            return self.family.columns

    @property
    def menu_link(self) -> str | None:
        return self.stored_screen.menu_link if self.stored_screen else self.family.menu_link

    @property
    def menu_text(self) -> str | None:
        return self.stored_screen.menu_text if self.stored_screen else self.family.menu_text

    @property
    def menu_label(self) -> str | None:
        if not self.menu_link:
            return None
        match self.type:
            case ScreenType.Boards | ScreenType.Input | ScreenType.Players:
                single_tournament = len(self.event.tournaments_by_id) == 1
                screen_set: ScreenSet = self.screen_sets_sorted_by_order[0]
                first_last = screen_set.first is not None or screen_set.last is not None
                text: str
                if self.type == ScreenType.Players or not screen_set.tournament.current_round:
                    text = self.menu_text or PapiWebConfig().default_players_screen_menu_text(
                        single_tournament=single_tournament, first_last=first_last)
                else:
                    text = self.menu_text or PapiWebConfig().default_boards_screen_menu_text(
                        single_tournament=single_tournament, first_last=first_last)
                text = text.replace('%t', screen_set.tournament.name)
                if self.type == ScreenType.Players or not screen_set.tournament.current_round:
                    if screen_set.first_player_by_name:
                        text = text.replace(
                            '%f', str(screen_set.first_player_by_name.last_name[:3]).upper())
                    if screen_set.last_player_by_name:
                        text = text.replace(
                            '%l', str(screen_set.last_player_by_name.last_name[:3]).upper())
                else:
                    if '%f' in text:
                        text = text.replace('%f', str(screen_set.first_board.id))
                    if '%l' in text:
                        text = text.replace('%l', str(screen_set.last_board.id))
                return text
            case ScreenType.Results:
                return self.stored_screen.menu_text or PapiWebConfig.default_results_screen_menu_text
            case _:
                raise ValueError(f'type=[{self.type}]')

    @property
    def menu(self) -> str:
        return self.stored_screen.menu if self.stored_screen else self.family.menu

    @property
    def timer(self) -> Timer | None:
        timer_id: int | None = self.stored_screen.timer_id if self.stored_screen else self.family.timer_id
        return self.event.timers_by_id[timer_id] if timer_id else None

    @cached_property
    def screen_sets_by_uniq_id(self) -> dict[str, ScreenSet]:
        return {screen_set.uniq_id: screen_set for screen_set in self.screen_sets_by_id.values()}

    @cached_property
    def screen_sets_sorted_by_order(self) -> list[ScreenSet]:
        return sorted(self.screen_sets_by_id.values(), key=lambda screen_set: screen_set.order)

    @property
    def players_show_unpaired(self) -> bool:
        match self.type:
            case ScreenType.Boards | ScreenType.Input:
                # Needed to display the players before the first round is paired
                return True
            case ScreenType.Players:
                if self.stored_screen:
                    if self.stored_screen.players_show_unpaired is not None:
                        return self.stored_screen.players_show_unpaired
                    else:
                        return PapiWebConfig.default_players_show_unpaired
                else:
                    return self.family.players_show_unpaired
            case _:
                raise ValueError(f'type=[{self.type}]')

    @property
    def icon_str(self) -> str:
        return self.type.icon_str

    @property
    def type_str(self) -> str:
        return str(self.type)

    @cached_property
    def results_limit(self) -> int:
        match self.type:
            case ScreenType.Results:
                if not self.stored_screen.results_limit:
                    return 0
                elif self.stored_screen.results_limit and self.stored_screen.results_limit % self.columns > 0:
                    results_limit: int = self.columns * (self.stored_screen.results_limit // self.columns + 1)
                    self.event.add_info(
                        f'limite positionnée à [{results_limit}] pour tenir sur {self.columns} colonnes',
                        screen=self)
                    return results_limit
                else:
                    return self.stored_screen.results_limit
            case _:
                raise ValueError(f'type=[{self.type}]')

    @cached_property
    def results_tournament_ids(self) -> list[int]:
        match self.type:
            case ScreenType.Results:
                return [
                    tournament_id
                    for tournament_id in self.stored_screen.results_tournament_ids
                    if tournament_id in self.event.tournaments_by_id
                ]
            case _:
                raise ValueError(f'type=[{self.type}]')

    @cached_property
    def results_tournament_names(self) -> str:
        return ', '.join([
            self.event.tournaments_by_id[results_tournament_id].name
            for results_tournament_id
            in self.results_tournament_ids
        ])

    @cached_property
    def _results(self) -> list[Result]:
        with EventDatabase(self.event.uniq_id) as event_database:
            return event_database.get_stored_results(self.results_limit, self.results_tournament_ids)

    @property
    def results_lists(self) -> Iterator[list[Result]]:
        column_size: int = (self.results_limit if self.results_limit else len(self._results)) // self.columns
        for i in range(self.columns):
            yield self._results[i * column_size:(i + 1) * column_size]

    @property
    def last_update(self) -> float:
        return self.stored_screen.last_update if self.stored_screen else self.family.last_update

    @property
    def background_image(self) -> str:
        if self.stored_screen and self.stored_screen.background_image:
            return self.stored_screen.background_image
        else:
            return self.event.background_image

    @cached_property
    def background_url(self) -> str:
        return inline_image_url(self.background_image)

    @property
    def background_color(self) -> str:
        if self.stored_screen and self.stored_screen.background_color:
            return self.stored_screen.background_color
        else:
            return self.event.background_color

    @property
    def last_update_str(self) -> str | None:
        return format_timestamp_date_time(self.last_update)
