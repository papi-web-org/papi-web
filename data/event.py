import json
import os
from functools import total_ordering
from logging import Logger
from pathlib import Path
from typing import Iterator

from common.config_reader import ConfigReader, TMP_DIR, EVENTS_PATH
from common.logger import get_logger
from data.chessevent import ChessEvent, ChessEventBuilder
from data.family import FamilyBuilder
from data.rotator import Rotator, RotatorBuilder
from data.screen import AScreen, ScreenBuilder
from data.template import Template, TemplateBuilder
from data.timer import Timer, TimerBuilder
from data.tournament import Tournament, TournamentBuilder
from data.util import DEFAULT_RECORD_ILLEGAL_MOVES_NUMBER, DEFAULT_RECORD_ILLEGAL_MOVES_ENABLE
from database.sqlite import EventDatabase

logger: Logger = get_logger()

silent_event_uniq_ids: list[str] = []


@total_ordering
class Event:
    def __init__(self, event_uniq_id: str, load_screens: bool):
        self.uniq_id: str = event_uniq_id
        self.reader = ConfigReader(
            EVENTS_PATH / f'{self.uniq_id}.ini',
            TMP_DIR / 'events' / event_uniq_id / 'config' / f'{event_uniq_id}.ini.{os.getpid()}.read',
            silent=self.uniq_id in silent_event_uniq_ids)
        with EventDatabase(self.uniq_id, 'r') as self.database:
            self.name: str = self.uniq_id
            self.path: Path = Path('papi')
            self.css: str | None = None
            self.update_password: str | None = None
            self.record_illegal_moves: int = 0
            self.check_in_players: bool = False
            self.allow_deletion: bool = False
            self.chessevents: dict[str, ChessEvent] = {}
            self.tournaments: dict[str, Tournament] = {}
            self.templates: dict[str, Template] = {}
            self.screens_by_family_id: dict[str, list[AScreen]] = {}
            self.screens: dict[str, AScreen] = {}
            self.rotators: dict[str, Rotator] = {}
            self.timer: Timer | None = None
            if self.reader.errors:
                return
            self._build_root()
            if self.reader.errors:
                return
            self.chessevents = ChessEventBuilder(
                self.reader
            ).chessevents
            if self.reader.errors:
                return
            self.tournaments = TournamentBuilder(
                self.reader, self.database, self.uniq_id, self.path, self.chessevents, self.record_illegal_moves
            ).tournaments
            if self.reader.errors:
                return
            if load_screens:
                self.templates = TemplateBuilder(self.reader).templates
                if self.reader.errors:
                    return
                FamilyBuilder(self.reader, self.tournaments, self.templates)
                if self.reader.errors:
                    return
                self.screens = ScreenBuilder(
                    self.reader, self.uniq_id, self.tournaments, self.templates, self.screens_by_family_id
                ).screens
                if self.reader.errors:
                    return
                self.rotators = RotatorBuilder(self.reader, self.screens, self.screens_by_family_id).rotators
                if self.reader.errors:
                    return
                self.timer = TimerBuilder(self.reader).timer
                if not self.timer:
                    screen_ids: list[str] = []
                    for screen_id in self.screens:
                        if self.screens[screen_id].show_timer:
                            screen_ids.append(screen_id)
                    if screen_ids:
                        self.reader.add_warning(
                            'le chronomètre ([timer.hour.*]) n\'est pas défini',
                            section_key=f'screen.{",".join(screen_ids)}',
                            key='show_timer')
                event_file_dependencies = [self.ini_file, ]
                for screen in self.screens.values():
                    event_file_dependencies += [
                        screen_set.tournament.file
                        for screen_set in screen.sets
                    ]
                self.set_file_dependencies(event_file_dependencies)
            silent_event_uniq_ids.append(self.uniq_id)

    @classmethod
    def __get_event_file_dependencies_file(cls, event_uniq_id: str) -> Path:
        return TMP_DIR / 'events' / event_uniq_id / 'event_file_dependencies.json'

    @classmethod
    def get_event_file_dependencies(cls, event_uniq_id: str) -> list[Path]:
        file_dependencies_file = cls.__get_event_file_dependencies_file(event_uniq_id)
        try:
            with open(file_dependencies_file, 'r', encoding='utf-8') as f:
                return [Path(file) for file in json.load(f)]
        except FileNotFoundError:
            return []

    def set_file_dependencies(self, files: list[Path]):
        file_dependencies_file = self.__get_event_file_dependencies_file(self.uniq_id)
        try:
            file_dependencies_file.parents[0].mkdir(parents=True, exist_ok=True)
            with open(file_dependencies_file, 'w', encoding='utf-8') as f:
                return f.write(json.dumps([str(file) for file in files]))
        except FileNotFoundError:
            return []

    @property
    def ini_file(self) -> Path:
        return self.reader.ini_file

    @property
    def download_allowed(self) -> bool:
        for tournament in self.tournaments.values():
            if tournament.download_allowed:
                return True
        return False

    @property
    def errors(self) -> list[str]:
        return self.reader.errors

    @property
    def warnings(self) -> list[str]:
        return self.reader.warnings

    @property
    def infos(self) -> list[str]:
        return self.reader.infos

    def _build_root(self):
        section_key: str = 'event'
        try:
            section = self.reader[section_key]
        except KeyError:
            self.reader.add_error('rubrique absente', section_key)
            return

        key = 'css'
        try:
            self.css = section[key]
        except KeyError:
            self.reader.add_debug('option absente', section_key, key)

        key = 'name'
        default_name = self.uniq_id
        try:
            self.name = section[key]
            if not self.name:
                self.reader.add_error('option vide', section_key, key)
                return
        except KeyError:
            self.name = default_name
            self.reader.add_info(
                f'option absente, par défaut [{default_name}]',
                section_key,
                key
            )
        except TypeError:
            # NOTE(Amaras) This could happen because of a TOC/TOU bug
            # https://en.wikipedia.org/wiki/Time-of-check_to_time-of-use
            # After this, the section has already been retrieved, so no future
            # access will throw a TypeError.
            self.reader.add_error(
                'la rubrique est devenue une option, erreur fatale',
                section_key
            )
            return

        key = 'path'
        default_path: Path = Path('papi')
        try:
            self.path = Path(section[key])
        except KeyError:
            self.path = default_path
            self.reader.add_debug(
                f'option absente, par défaut [{default_path}]',
                section_key,
                key
            )
        # NOTE(Amaras) This could be a TOC/TOU bug
        # What would our threat model be for this?
        if not self.path.exists():
            self.reader.add_warning(
                f"le répertoire [{self.path}] n'existe pas",
                section_key,
                key
            )
            return
        elif not self.path.is_dir():
            self.reader.add_warning(
                f"[{self.path}] n'est pas un répertoire",
                section_key,
                key
            )

        key = 'update_password'
        try:
            self.update_password = section[key]
        except KeyError:
            self.reader.add_info(
                'option absente, aucun mot de passe ne sera demandé pour les saisies',
                section_key,
                key
            )

        key = 'record_illegal_moves'
        self.record_illegal_moves: int = (
            DEFAULT_RECORD_ILLEGAL_MOVES_NUMBER if DEFAULT_RECORD_ILLEGAL_MOVES_ENABLE else 0
        )
        if key in section:
            record_illegal_moves_bool: bool | None = self.reader.getboolean_safe(section_key, key)
            if record_illegal_moves_bool is not None:
                if record_illegal_moves_bool:
                    self.record_illegal_moves = DEFAULT_RECORD_ILLEGAL_MOVES_NUMBER
                else:
                    self.record_illegal_moves = 0
            else:
                record_illegal_moves_int: int | None = self.reader.getint_safe(section_key, key, minimum=0)
                if record_illegal_moves_int is None:
                    self.reader.add_warning(
                        f'un booléen ou un entier positif ou nul est attendu, par défaut [{self.record_illegal_moves}]',
                        section_key,
                        key)
                else:
                    self.record_illegal_moves = record_illegal_moves_int
        else:
            self.reader.add_debug(f'option absente, par défaut [{self.record_illegal_moves}]')

        key = 'check_in_players'
        if key in section:
            check_in_players_bool: bool | None = self.reader.getboolean_safe(section_key, key)
            if check_in_players_bool is None:
                self.reader.add_warning(
                    f'un booléen est attendu, par défaut [{self.check_in_players}]',
                    section_key,
                    key)
            else:
                self.check_in_players = check_in_players_bool
        else:
            self.reader.add_debug(f'option absente, par défaut [{self.check_in_players}]')
        
        key = 'allow_deletion'
        if key in section:
            allow_deletion: bool | None = self.reader.getboolean_safe(section_key, key)
            if allow_deletion is None:
                self.reader.add_warning(
                    f'un booléen est attendu, par défaut [{self.allow_deletion}]',
                    section_key,
                    key)
            else:
                self.allow_deletion = allow_deletion
        else:
            self.reader.add_debug(f'option absente, par défaut [{self.allow_deletion}]')

        section_keys: list[str] = [
            'name', 'path', 'update_password', 'css', 'record_illegal_moves', 'check_in_players',
            'allow_deletion'
        ]
        for key, _ in section.items():
            if key not in section_keys:
                self.reader.add_warning('option inconnue', section_key, key)

    def __lt__(self, other: 'Event'):
        # p1 < p2 calls p1.__lt__(p2)
        return self.uniq_id > other.uniq_id

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(self, Event):
            return NotImplemented
        return self.uniq_id == other.uniq_id


def __get_events(load_screens: bool, with_tournaments_only: bool = False) -> dict[str, Event]:
    event_files: Iterator[Path] = EVENTS_PATH.glob('*.ini')
    events: dict[str, Event] = {}
    for event_file in event_files:
        event_uniq_id: str = event_file.stem
        event: Event = Event(event_uniq_id, load_screens)
        if not with_tournaments_only or event.tournaments:
            events[event.uniq_id] = event
    return events


def get_events_sorted_by_name(load_screens: bool, with_tournaments_only: bool = False) -> list[Event]:
    return sorted(
        __get_events(load_screens, with_tournaments_only=with_tournaments_only).values(),
        key=lambda event: event.name)


def get_events_by_uniq_id(load_screens: bool, with_tournaments_only: bool = False) -> dict[str, Event]:
    return __get_events(load_screens, with_tournaments_only=with_tournaments_only)
