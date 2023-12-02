import time
from functools import total_ordering
from logging import Logger
from pathlib import Path
from typing import Iterator

from common.config_reader import ConfigReader, TMP_DIR, EVENTS_PATH
from common.logger import get_logger
from data.board import Board
from data.chessevent_connection import ChessEventConnection, ChessEventConnectionBuilder
from data.family import FamilyBuilder
from data.result import Result
from data.rotator import Rotator, RotatorBuilder
from data.screen import AScreen, ScreenBuilder
from data.template import Template, TemplateBuilder
from data.timer import Timer, TimerBuilder
from data.tournament import Tournament, TournamentBuilder

logger: Logger = get_logger()


@total_ordering
class Event:
    def __init__(self, event_id: str, silent: bool = True):
        self.event_id: str = event_id
        self.reader = ConfigReader(
            EVENTS_PATH / f'{self.id}.ini', TMP_DIR / event_id / f'{event_id}.ini.read', silent=silent)
        self.name: str = self.event_id
        self.path: Path = Path('papi')
        self.css: str | None = None
        self.update_password: str | None = None
        self.chessevent_connections: dict[str, ChessEventConnection] = {}
        self.tournaments: dict[str, Tournament] = {}
        self.templates: dict[str, Template] = {}
        self.screens_by_family_id: dict[str, list[AScreen]] = {}
        self.screens: dict[str, AScreen] = {}
        self.rotators: dict[str, Rotator] = {}
        self.timer: Timer | None = None
        if self.reader.errors or self.reader.warnings:  # warning when the configuration file is not found
            return
        self._build_root()
        if self.reader.errors:
            return
        self.chessevent_connections = ChessEventConnectionBuilder(
            self.reader
        ).chessevent_connections
        if self.reader.errors:
            return
        self.tournaments = TournamentBuilder(
            self.reader, self.event_id, self.path, self.chessevent_connections
        ).tournaments
        if self.reader.errors:
            return
        self.templates = TemplateBuilder(self.reader).templates
        if self.reader.errors:
            return
        FamilyBuilder(self.reader, self.tournaments, self.templates)
        if self.reader.errors:
            return
        self.screens = ScreenBuilder(
            self.reader, self.event_id, self.tournaments, self.templates, self.screens_by_family_id).screens
        if self.reader.errors:
            return
        self.rotators = RotatorBuilder(self.reader, self.screens, self.screens_by_family_id).rotators
        if self.reader.errors:
            return
        self.timer = TimerBuilder(self.reader).timer

    @property
    def id(self) -> str:
        return self.event_id

    @property
    def ini_file(self) -> Path:
        return self.reader.ini_file

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

        key = 'name'
        default_name = self.event_id
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
            self.reader.add_error(
                    f"le répertoire [{self.path}] n'existe pas",
                    section_key,
                    key
            )
            return
        elif not self.path.is_dir():
            self.reader.add_error(
                    f"[{self.path}] n'est pas un répertoire",
                    section_key,
                    key
            )

        key = 'css'
        try:
            self.css = section[key]
        except KeyError:
            self.reader.add_debug('option absente', section_key, key)

        key = 'update_password'
        try:
            self.update_password = section[key]
        except KeyError:
            self.reader.add_info(
                'option absente, aucun mot de passe ne sera demandé pour les saisies',
                section_key,
                key
            )

        section_keys: list[str] = ['name', 'path', 'update_password', 'css', ]
        for key, value in section.items():
            if key not in section_keys:
                self.reader.add_warning('option inconnue', section_key, key)

    def store_result(self, tournament: Tournament, board: Board, result: int):
        results_dir: Path = Result.results_dir(self.id)
        if not results_dir.is_dir():
            results_dir.mkdir(parents=True)
        now: float = time.time()
        # delete old files
        for file in results_dir.glob('*'):
            if now - file.lstat().st_ctime > 3600:
                file.unlink()
                logger.debug(f'le fichier [{file}] a été supprimé')
        # add a new file
        white_str: str = (f'{board.white_player.last_name} {board.white_player.first_name} {board.white_player.rating}'
                          .replace(' ', '_'))
        black_str: str = (f'{board.black_player.last_name} {board.black_player.first_name} {board.black_player.rating}'
                          .replace(' ', '_'))
        filename: str = f'{now} {tournament.id} {tournament.current_round} {board.id} {white_str} {black_str} {result}'
        result_file: Path = Path(results_dir, filename)
        result_file.touch()
        logger.info(f'le fichier [{result_file}] a été ajouté')

    def __lt__(self, other: 'Event'):
        # p1 < p2 calls p1.__lt__(p2)
        return self.name > other.name

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(self, Event):
            return NotImplemented
        return self.name == other.name


def get_events(silent: bool = True, with_tournaments_only: bool = False) -> list[Event]:
    event_files: Iterator[Path] = EVENTS_PATH.glob('*.ini')
    events: list[Event] = []
    for event_file in event_files:
        event_id: str = event_file.stem
        event: Event = Event(event_id, silent=silent)
        if not with_tournaments_only or event.tournaments:
            events.append(event)
    return events


def get_events_by_name(silent: bool = True, with_tournaments_only: bool = False) -> list[Event]:
    return sorted(get_events(silent=silent, with_tournaments_only=with_tournaments_only), key=lambda event: event.name)
