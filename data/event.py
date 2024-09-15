import fnmatch
import logging
import time
from dataclasses import dataclass
from functools import total_ordering
from logging import Logger
from pathlib import Path

from common import format_timestamp_date_time, format_timestamp_date, format_timestamp_time
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from data.chessevent import ChessEvent
from data.family import Family
from data.rotator import Rotator
from data.screen import Screen
from data.screen_set import ScreenSet
from data.timer import Timer, TimerHour
from data.tournament import Tournament
from data.util import ScreenType
from database.store import StoredEvent
from web.views_background import BackgroundWebContext

logger: Logger = get_logger()

event_last_load_date_by_uniq_id: dict[str, float] = {}
silent_event_uniq_ids: list[str] = []


@dataclass
class EventMessage:
    level: int
    text: str
    chessevent: ChessEvent | None
    tournament: Tournament | None
    family: Family | None
    timer: Timer | None
    timer_hour: TimerHour | None
    screen: Screen | None
    screen_set: ScreenSet | None
    rotator: Rotator | None

    def __post_init__(self):
        assert self.level in [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]

    @property
    def formatted_text(self) -> str:
        if self.tournament:
            return f'tournoi [{self.tournament.uniq_id}] : {self.text}'
        if self.chessevent:
            return f'connexion à ChessEvent [{self.chessevent.uniq_id}] : {self.text}'
        elif self.family:
            return f'famille [{self.family.uniq_id}] : {self.text}'
        elif self.timer_hour:
            return f'chronomètre [{self.timer_hour.timer.uniq_id}], horaire n°{self.timer_hour.order} : {self.text}'
        elif self.timer:
            return f'chronomètre [{self.timer.uniq_id}] : {self.text}'
        elif self.screen_set:
            return f'écran [{self.screen.uniq_id}], horaire n°{self.screen_set.order} : {self.text}'
        elif self.screen:
            return f'écran [{self.screen.uniq_id}] : {self.text}'
        elif self.rotator:
            return f'écran rotatif [{self.rotator.uniq_id}] : {self.text}'
        else:
            return f'{self.text}'


@total_ordering
class Event:
    def __init__(self, stored_event: StoredEvent, lazy_load: bool):
        self.stored_event: StoredEvent = stored_event
        self.lazy_load = lazy_load
        self.chessevents_by_id: dict[int, ChessEvent] = {}
        self.chessevents_by_uniq_id: dict[str, ChessEvent] = {}
        self.tournaments_by_id: dict[int, Tournament] = {}
        self.tournaments_by_uniq_id: dict[str, Tournament] = {}
        self._tournaments_sorted_by_uniq_id: list[Tournament] | None = None
        self.screens_by_uniq_id: dict[str, Screen] = {}
        self._screens_sorted_by_uniq_id: list[Screen] | None = None
        self._screens_of_type_sorted_by_uniq_id: dict[ScreenType, list[Screen]] | None = None
        self._public_screens_sorted_by_uniq_id: list[Screen] | None = None
        self._public_screens_of_type_sorted_by_uniq_id: dict[ScreenType, list[Screen]] | None = None
        self.basic_screens_by_id: dict[int, Screen] = {}
        self.basic_screens_by_uniq_id: dict[str, Screen] = {}
        self.families_by_id: dict[int, Family] = {}
        self.families_by_uniq_id: dict[str, Family] = {}
        self.family_screens_by_uniq_id: dict[str, Screen] = {}
        self.rotators_by_id: dict[int, Rotator] = {}
        self.rotators_by_uniq_id: dict[str, Rotator] = {}
        self._rotators_sorted_by_uniq_id: list[Rotator] | None = None
        self._publics_rotators_sorted_by_uniq_id: list[Rotator] | None = None
        self.timers_by_id: dict[int, Timer] = {}
        self.timers_by_uniq_id: dict[str, Timer] = {}
        self._timer_colors: dict[int, str] | None = None
        self._timer_delays: dict[int, int] | None = None
        self._background_url: str | None = None
        self.messages: list[EventMessage] = []
        last_load_date: float = event_last_load_date_by_uniq_id.get(self.uniq_id, None)
        self._silent = last_load_date is not None and last_load_date > self.stored_event.last_update
        self.build()
        event_last_load_date_by_uniq_id[self.uniq_id] = time.time()

    def build(self):
        self.build_root()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur l\'évènement, les connexions à ChessEvent, chronomètres, tournois, '
                'écrans, familles et écrans rotatifs ne seront pas chargés')
            return
        self._build_chessevents()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur les connexions à ChessEvent, les chronomètres, tournois, écrans, '
                'familles et écrans rotatifs ne seront pas chargés')
            return
        self._build_timers()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur les chronomètres, les tournois, écrans, familles et écrans '
                'rotatifs ne seront pas chargés')
            return
        self._build_tournaments()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur les tournois, les écrans, familles et écrans rotatifs ne seront pas '
                'chargés')
            return
        # if lazy_load screen sets will not be calculated
        self._build_screens()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur les écrans, les familles et écrans rotatifs ne seront pas chargés')
            return
        # if lazy_load family screens will not be calculated
        self._build_families()
        if self.errors:
            self.add_warning(
                'Des erreurs ont été trouvées sur les familles, les écrans rotatifs ne seront pas chargés')
            return
        if not self.lazy_load:
            self._set_screen_menus()
        if not self.lazy_load:
            self._build_rotators()
            if self.errors:
                return

    @property
    def uniq_id(self) -> str:
        return self.stored_event.uniq_id

    @property
    def name(self) -> str:
        return self.stored_event.name if self.stored_event.name else self.uniq_id

    @property
    def start(self) -> float:
        return self.stored_event.start

    @property
    def stop(self) -> float:
        return self.stored_event.stop

    @property
    def formatted_start_date_time(self) -> str:
        return format_timestamp_date_time(self.start)

    @property
    def formatted_start_date(self) -> str:
        return format_timestamp_date(self.start)

    @property
    def formatted_start_time(self) -> str:
        return format_timestamp_time(self.start)

    @property
    def formatted_stop_date_time(self) -> str:
        return format_timestamp_date_time(self.stop)

    @property
    def formatted_stop_date(self) -> str:
        return format_timestamp_date(self.stop)

    @property
    def formatted_stop_time(self) -> str:
        return format_timestamp_time(self.stop)

    @property
    def players_number(self) -> int:
        return sum((len(tournament.players_by_name_with_unpaired) for tournament in self.tournaments_by_id.values()))

    @property
    def path(self) -> Path:
        return Path(self.stored_event.path) if self.stored_event.path else PapiWebConfig().default_papi_path

    @property
    def background_image(self) -> str:
        return self.stored_event.background_image or PapiWebConfig().default_background_image

    @property
    def background_url(self) -> str:
        if self._background_url is None:
            self._background_url = BackgroundWebContext.inline_image_url(self.background_image)
        return self._background_url

    @property
    def background_color(self) -> str:
        return self.stored_event.background_color or PapiWebConfig().default_background_color

    @property
    def update_password(self) -> str:
        return self.stored_event.update_password

    @property
    def record_illegal_moves(self) -> int:
        if self.stored_event.record_illegal_moves is None:
            return PapiWebConfig().default_record_illegal_moves_number
        return self.stored_event.record_illegal_moves

    @property
    def allow_results_deletion_on_input_screens(self) -> int:
        if self.stored_event.allow_results_deletion_on_input_screens is None:
            return PapiWebConfig().default_allow_results_deletion_on_input_screens
        else:
            return self.stored_event.allow_results_deletion_on_input_screens

    @property
    def timer_colors(self) -> dict[int, str]:
        if self._timer_colors is None:
            self._timer_colors = {
                i: self.stored_event.timer_colors[i]
                if i in self.stored_event.timer_colors and self.stored_event.timer_colors[i]
                else PapiWebConfig().default_timer_colors[i]
                for i in range(1, 4)}
        return self._timer_colors

    @property
    def timer_delays(self) -> dict[int, int]:
        if self._timer_delays is None:
            self._timer_delays = {
                i: self.stored_event.timer_delays[i]
                if i in self.stored_event.timer_delays and self.stored_event.timer_delays[i]
                else PapiWebConfig().default_timer_delays[i]
                for i in range(1, 4)}
        return self._timer_delays

    @property
    def public(self) -> bool:
        return self.stored_event.public

    @property
    def tournaments_sorted_by_uniq_id(self) -> list[Tournament]:
        if self._tournaments_sorted_by_uniq_id is None:
            self._tournaments_sorted_by_uniq_id = sorted(
                self.tournaments_by_id.values(), key=lambda tournament: tournament.uniq_id)
        return self._tournaments_sorted_by_uniq_id

    @property
    def screens_sorted_by_uniq_id(self) -> list[Screen]:
        if self._screens_sorted_by_uniq_id is None:
            self._screens_sorted_by_uniq_id = sorted(
                self.screens_by_uniq_id.values(), key=lambda screen: screen.uniq_id)
        return self._screens_sorted_by_uniq_id

    @property
    def screens_of_type_sorted_by_uniq_id(self) -> dict[ScreenType, list[Screen]]:
        if self._screens_of_type_sorted_by_uniq_id is None:
            self._screens_of_type_sorted_by_uniq_id = {}
            for screen in self.screens_sorted_by_uniq_id:
                if screen.type not in self._screens_of_type_sorted_by_uniq_id:
                    self._screens_of_type_sorted_by_uniq_id[screen.type] = []
                self._screens_of_type_sorted_by_uniq_id[screen.type].append(screen)
        return self._screens_of_type_sorted_by_uniq_id

    @property
    def input_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.screens_of_type_sorted_by_uniq_id.get(ScreenType.Input, [])

    @property
    def boards_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.screens_of_type_sorted_by_uniq_id.get(ScreenType.Boards, [])

    @property
    def players_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.screens_of_type_sorted_by_uniq_id.get(ScreenType.Players, [])

    @property
    def results_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.screens_of_type_sorted_by_uniq_id.get(ScreenType.Results, [])

    @property
    def image_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.screens_of_type_sorted_by_uniq_id.get(ScreenType.Image, [])

    @property
    def public_screens_sorted_by_uniq_id(self) -> list[Screen]:
        if self._public_screens_sorted_by_uniq_id is None:
            self._public_screens_sorted_by_uniq_id = [
                screen for screen in self.screens_by_uniq_id.values() if screen.public
            ]
        return self._public_screens_sorted_by_uniq_id

    @property
    def public_screens_of_type_sorted_by_uniq_id(self) -> dict[ScreenType, list[Screen]]:
        if self._public_screens_of_type_sorted_by_uniq_id is None:
            self._public_screens_of_type_sorted_by_uniq_id = {}
            for screen in self.public_screens_sorted_by_uniq_id:
                if screen.type not in self._public_screens_of_type_sorted_by_uniq_id:
                    self._public_screens_of_type_sorted_by_uniq_id[screen.type] = []
                self._public_screens_of_type_sorted_by_uniq_id[screen.type].append(screen)
        return self._public_screens_of_type_sorted_by_uniq_id

    @property
    def public_input_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.public_screens_of_type_sorted_by_uniq_id.get(ScreenType.Input, [])

    @property
    def public_boards_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.public_screens_of_type_sorted_by_uniq_id.get(ScreenType.Boards, [])

    @property
    def public_players_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.public_screens_of_type_sorted_by_uniq_id.get(ScreenType.Players, [])

    @property
    def public_results_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.public_screens_of_type_sorted_by_uniq_id.get(ScreenType.Results, [])

    @property
    def public_image_screens_sorted_by_uniq_id(self) -> list[Screen]:
        return self.public_screens_of_type_sorted_by_uniq_id.get(ScreenType.Image, [])

    @property
    def rotators_sorted_by_uniq_id(self) -> list[Rotator]:
        if self._rotators_sorted_by_uniq_id is None:
            self._rotators_sorted_by_uniq_id = sorted(
                self.rotators_by_id.values(), key=lambda rotator: rotator.uniq_id)
        return self._rotators_sorted_by_uniq_id

    @property
    def public_rotators_sorted_by_uniq_id(self) -> list[Rotator]:
        if self._publics_rotators_sorted_by_uniq_id is None:
            self._publics_rotators_sorted_by_uniq_id = sorted(
                [rotator for rotator in self.rotators_by_id.values() if rotator.public],
                key=lambda rotator: rotator.uniq_id)
        return self._publics_rotators_sorted_by_uniq_id

    @property
    def last_update(self) -> float | None:
        return self.stored_event.last_update

    @property
    def last_update_str(self) -> str | None:
        return format_timestamp_date_time(self.last_update)

    def build_root(self):
        if not self.stored_event.name:
            self.add_error(f'pas de nom défini, par défaut [{self.name}]')
        if not self.stored_event.path:
            self.add_debug(f'pas de répertoire défini par défaut pour les fichiers Papi, par défaut [{self.path}]')
        if not self.path.exists():
            self.add_warning(f'le répertoire [{self.path}] n\'existe pas')
        elif not self.path.is_dir():
            self.add_warning(f'[{self.path}] n\'est pas un répertoire')
        if not self.stored_event.background_image:
            self.add_debug('pas d\'image définie')
        if not self.stored_event.background_color:
            self.add_debug('pas de couleur de fond définie')
        if not self.stored_event.update_password:
            self.add_debug('pas de mot de passe défini pour les écrans de saisie')
        if self.stored_event.record_illegal_moves is None:
            self.add_debug(f'nombre de coups illégaux non défini, par défaut [{self.record_illegal_moves}]')
        if self.stored_event.allow_results_deletion_on_input_screens is None:
            self.add_debug(
                f'Autorisation de suppression des résultats entrés non définie, par défaut '
                f'[{"autorisée" if self.allow_results_deletion_on_input_screens else "non autorisée"}]')

    def _build_chessevents(self):
        for stored_chessevent in self.stored_event.stored_chessevents:
            chessevent: ChessEvent = ChessEvent(self, stored_chessevent)
            self.chessevents_by_id[chessevent.id] = chessevent
            self.chessevents_by_uniq_id[chessevent.uniq_id] = chessevent

    def _build_timers(self):
        for stored_timer in self.stored_event.stored_timers:
            timer: Timer = Timer(self, stored_timer)
            self.timers_by_id[timer.id] = timer
            self.timers_by_uniq_id[timer.uniq_id] = timer

    def _build_tournaments(self):
        for stored_tournament in self.stored_event.stored_tournaments:
            tournament: Tournament = Tournament(self, stored_tournament)
            self.tournaments_by_id[tournament.id] = tournament
            self.tournaments_by_uniq_id[tournament.uniq_id] = tournament

    def _build_screens(self):
        for stored_screen in self.stored_event.stored_screens:
            screen: Screen = Screen(self, stored_screen=stored_screen)
            self.basic_screens_by_id[screen.id] = screen
            self.basic_screens_by_uniq_id[screen.uniq_id] = screen
            self.screens_by_uniq_id[screen.uniq_id] = screen

    def _build_families(self):
        for stored_family in self.stored_event.stored_families:
            family: Family = Family(self, stored_family)
            self.families_by_uniq_id[stored_family.uniq_id] = family
            self.families_by_id[stored_family.id] = family
            for screen in family.screens_by_uniq_id.values():
                self.screens_by_uniq_id[screen.uniq_id] = screen
                self.family_screens_by_uniq_id[screen.uniq_id] = screen

    def _build_rotators(self):
        for stored_rotator in self.stored_event.stored_rotators:
            rotator: Rotator = Rotator(self, stored_rotator)
            self.rotators_by_uniq_id[stored_rotator.uniq_id] = rotator
            self.rotators_by_id[stored_rotator.id] = rotator

    def _set_screen_menus(self):
        boards_menu_screens: list[Screen] = []
        input_menu_screens: list[Screen] = []
        players_menu_screens: list[Screen] = []
        results_menu_screens: list[Screen] = []
        for screen in self.screens_by_uniq_id.values():
            if screen.menu_label:
                match screen.type:
                    case ScreenType.Boards:
                        boards_menu_screens.append(screen)
                    case ScreenType.Input:
                        input_menu_screens.append(screen)
                    case ScreenType.Players:
                        players_menu_screens.append(screen)
                    case ScreenType.Results:
                        results_menu_screens.append(screen)
                    case ScreenType.Image:
                        pass
                    case _:
                        raise ValueError(f'type={screen.type}')
        for screen in self.screens_by_uniq_id.values():
            if screen.menu is None:
                screen.menu_screens = []
                continue
            for menu_part in map(str.strip, screen.menu.split(',')):
                if not menu_part:
                    continue
                if menu_part == '@boards':
                    screen.menu_screens += boards_menu_screens
                    continue
                if menu_part == '@input':
                    screen.menu_screens += input_menu_screens
                    continue
                if menu_part == '@players':
                    screen.menu_screens += players_menu_screens
                    continue
                if menu_part == '@results':
                    screen.menu_screens += results_menu_screens
                    continue
                if menu_part == '@family':
                    assert screen.family_id is not None
                    screen.menu_screens += self.families_by_id[screen.family_id].screens_by_uniq_id.values()
                    continue
                if '*' in menu_part:
                    menu_part_screen_uniq_ids: list[str] = fnmatch.filter(self.screens_by_uniq_id.keys(), menu_part)
                    if not menu_part_screen_uniq_ids:
                        self.add_warning(f'Le motif [{menu_part}] ne correspond à aucun écran', screen=screen)
                    else:
                        screen.menu_screens += [
                            self.screens_by_uniq_id[screen_uniq_id] for screen_uniq_id in menu_part_screen_uniq_ids
                        ]
                    continue
                if menu_part in self.screens_by_uniq_id:
                    screen.menu_screens.append(self.screens_by_uniq_id[menu_part])
                else:
                    self.add_warning(f'L\'écran [{menu_part}] n\'existe pas', screen=screen)

    def _add_message(
            self, level: int, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        self.messages.append(EventMessage(
            level, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator))

    def add_debug(
            self, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        self._add_message(
            logging.DEBUG, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator)
        if not self._silent:
            logger.debug(text)

    @property
    def infos(self) -> list[str]:
        return [message.text for message in self.messages if message.level == logging.INFO]

    def add_info(
            self, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        self._add_message(
            logging.INFO, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator)
        if not self._silent:
            logger.info(text)

    @property
    def warnings(self) -> list[str]:
        return [message.text for message in self.messages if message.level == logging.WARNING]

    def add_warning(
            self, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        self._add_message(
            logging.WARNING, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator)
        if not self._silent:
            logger.info(text)

    @property
    def errors(self) -> list[str]:
        return [message.text for message in self.messages if message.level == logging.ERROR]

    def add_error(
            self, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        self._add_message(
            logging.ERROR, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator)
        if not self._silent:
            logger.info(text)

    @property
    def criticals(self) -> list[str]:
        return [message.text for message in self.messages if message.level == logging.CRITICAL]

    def add_critical(
            self, text: str, tournament: Tournament | None = None, chessevent: ChessEvent | None = None,
            family: Family | None = None, timer: Timer | None = None, timer_hour: TimerHour | None = None,
            screen: Screen | None = None, screen_set: ScreenSet | None = None, rotator: Rotator | None = None,
    ):
        """Adds a debug-level message and logs it"""
        self._add_message(
            logging.CRITICAL, text, tournament=tournament, chessevent=chessevent, family=family, timer=timer,
            timer_hour=timer_hour, screen=screen, screen_set=screen_set, rotator=rotator)
        if not self._silent:
            logger.info(text)

    @property
    def download_allowed(self) -> bool:
        for tournament in self.tournaments_by_id.values():
            if tournament.download_allowed:
                return True
        return False

    def __lt__(self, other: 'Event'):
        # p1 < p2 calls p1.__lt__(p2)
        return self.uniq_id > other.uniq_id

    def __eq__(self, other: 'Event'):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(self, Event):
            return NotImplemented
        return self.uniq_id == other.uniq_id
