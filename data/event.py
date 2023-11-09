import re
import time
from configparser import SectionProxy
from functools import total_ordering
from logging import Logger
from pathlib import Path
from typing import Iterator, NamedTuple

from common.config_reader import ConfigReader
from common.logger import get_logger
from data.board import Board
from data.family import FamilyBuilder
from data.result import Result
from data.rotator import Rotator, RotatorBuilder
from data.screen import AScreen, ScreenBuilder
from data.screen import ScreenType
from data.template import Template
from data.timer import Timer, TimerBuilder
from data.tournament import Tournament

logger: Logger = get_logger()

EVENTS_PATH: Path = Path('events')


class HandicapTournament(NamedTuple):
    """A helper data structure to store the information needed to
    compute handicap times if needed."""
    initial_time: int | None = None
    increment: int | None = None
    penalty_step: int | None = None
    penalty_value: int | None = None
    min_time: int | None = None


@total_ordering
class Event:
    def __init__(self, event_id: str, silent: bool = True):
        self.event_id: str = event_id
        self.reader = ConfigReader(EVENTS_PATH / f'{self.id}.ini', silent=silent)
        self.name: str = self.event_id
        self.path: Path = Path('papi')
        self.css: str | None = None
        self.update_password: str | None = None
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
        self._build_tournaments()
        if self.reader.errors:
            return
        self._build_templates()
        if self.reader.errors:
            return
        FamilyBuilder(self.reader, self.templates)
        if self.reader.errors:
            return
        self.screens = ScreenBuilder(
            self.reader, self.event_id, self.tournaments, self.templates, self.screens_by_family_id
        ).screens
        if self.reader.errors:
            return
        self.rotators = RotatorBuilder(
            self.reader, self.screens, self.screens_by_family_id
        ).rotators
        if self.reader.errors:
            return
        self.timer = TimerBuilder(
            self.reader
        ).timer

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

    def __rename_section(self, old_section_key: str, new_section_key: str):
        # NOTE(Amaras) this can add values that are in DEFAULTSEC if any.
        # This can also cause a crash if we're trying to delete DEFAULTSEC,
        # as deleting DEFAUTLSEC causes a ValueError.
        self.reader[new_section_key] = self.reader[old_section_key]
        del self.reader[old_section_key]

    def _build_tournaments(self):
        tournament_ids: list[str] = self.reader.get_subsection_keys_with_prefix('tournament')
        # NOTE(Amaras) Special case of tournament: handicap depends on
        # the [tournament] section being there.
        if 'handicap' in tournament_ids:
            tournament_ids.remove('handicap')
        if 'tournament' in self.reader:
            if tournament_ids:
                section_keys: str = ', '.join(
                    ('[tournament.' + id + ']' for id in tournament_ids)
                )
                self.reader.add_error(
                    "la rubrique [tournament] ne doit être utilisée que lorsque"
                    " l'évènement ne compte qu'un tournoi, d'autres rubriques "
                    f"sont présentes ({section_keys})",
                    'tournament.*'
                )
                return
            default_tournament_id: str = 'default'
            old_tournament_section_key: str = 'tournament'
            new_tournament_section_key: str = 'tournament.' + default_tournament_id
            self.__rename_section(old_tournament_section_key, new_tournament_section_key)
            self.reader.add_debug(
                f'un seul tournoi, la rubrique [{old_tournament_section_key}] a '
                f'été renommée [{new_tournament_section_key}]',
                old_tournament_section_key
            )
            old_handicap_section_key: str = 'tournament.handicap'
            if old_handicap_section_key in self.reader:
                new_handicap_section_key = f'tournament.{default_tournament_id}.handicap'
                self.__rename_section(old_handicap_section_key, new_handicap_section_key)
                self.reader.add_debug(
                    f'un seul tournoi, la rubrique [{old_handicap_section_key}] a '
                    f'été renommée [{new_tournament_section_key}]'
                )
            tournament_ids.append(default_tournament_id)
        elif not tournament_ids:
            self.reader.add_error('aucun tournoi trouvé', 'tournament.*')
            return
        for tournament_id in tournament_ids:
            self._build_tournament(tournament_id)
        if not len(self.tournaments):
            self.reader.add_error('aucun tournoi initialisé')

    def _build_tournament(self, tournament_id: str):
        section_key: str = f'tournament.{tournament_id}'
        try:
            section = self.reader[section_key]
        except KeyError:
            self.reader.add_error('Tournoi non trouvé', section_key)
            return
        key = 'path'
        default_path: Path = self.path
        path: Path = default_path
        try:
            path = Path(section[key])
        except KeyError:
            self.reader.add_debug(
                    f'option absente, par défault [{default_path}]',
                    section_key,
                    key
            )
        except TypeError:
            self.reader.add_error(
                    f'La rubrique [{section_key}] est en fait une option',
                    section_key
            )
            return
        # NOTE(Amaras) TOC/TOU bug
        if not path.exists():
            self.reader.add_error(
                    f"le répertoire [{path}] n'existe pas, tournoi ignoré",
                    section_key,
                    key
            )
            return
        if not path.is_dir():
            self.reader.add_error(
                    f"[{path}] n'est pas un répertoire, tournoi ignoré",
                    section_key,
                    key
            )
            return
        key = 'filename'
        filename: str | None = section.get(key)
        key = 'ffe_id'
        ffe_id: int | None = None
        try:
            ffe_id = int(section[key])
            assert ffe_id >= 1
        except KeyError:
            pass
        except ValueError:
            self.reader.add_warning('un entier est attendu', section_key, key)
            ffe_id = None
        except AssertionError:
            self.reader.add_warning(
                    'un entier positif non nul est attendu',
                    section_key,
                    key
            )
            ffe_id = None
        if filename is None and ffe_id is None:
            self.reader.add_error(
                    'ni [filename] ni [ffe_id] ne sont indiqués, tournoi ignoré',
                    section_key
            )
            return
        if filename is None:
            filename = str(ffe_id)
        file: Path = path / f'{filename}.papi'
        # NOTE(Amaras) TOC/TOU bug
        if not file.exists():
            self.reader.add_error(f'le fichier [{file}] n\'existe pas, tournoi ignoré', section_key)
            return
        if not file.is_file():
            self.reader.add_error(f'[{file}] n\'est pas un fichier, tournoi ignoré', section_key)
            return
        key = 'name'
        default_name: str = tournament_id
        try:
            name = section[key]
        except KeyError:
            self.reader.add_info(
                    f'option absente, par défaut [{default_name}]',
                    section_key,
                    key
            )
            name = default_name
        key = 'ffe_password'
        ffe_password: str | None = None
        if ffe_id is not None:
            try:
                ffe_password = section[key]
                if not re.match('^[A-Z]{10}$', ffe_password):
                    self.reader.add_warning(
                        'un mot de 10 lettres majuscules est attendu, le mot '
                        'de passe est ignoré (les opérations sur le site web '
                        'de la FFE ne seront pas disponibles',
                        section_key,
                        key
                    )
                    ffe_password = None
            except KeyError:
                self.reader.add_info(
                    'option absente, les opération sur le site web de la FFE '
                    'ne seront pas disponibles',
                    section_key,
                    key
                )
        elif key in section:
            self.reader.add_info(
                "option ignorée quand l'option [ffe_id] n'est pas indiquée",
                section_key,
                key
            )
        section_keys: list[str] = [
                'path',
                'filename',
                'name',
                'ffe_id',
                'ffe_password',
            ]
        for key, value in section.items():
            if key not in section_keys:
                self.reader.add_warning('option inconnue', section_key, key)
        handicap_section_key = 'tournament.' + tournament_id + '.handicap'
        handicap_values = self._build_tournament_handicap(handicap_section_key)
        if handicap_values[0] is not None and ffe_id is not None:
            self.reader.add_warning(
                'les tournois à handicap ne devraient pas être homologués',
                handicap_section_key
            )
        self.tournaments[tournament_id] = Tournament(
            tournament_id,
            name,
            file,
            ffe_id,
            ffe_password,
            *handicap_values
        )

    def _get_value_with_warning(
        self,
        section: SectionProxy,
        section_key: str,
        key: str,
        target_type: type,
        predicate,
        default_value,
        *messages,
    ):
        try:
            value = target_type(section[key])
            assert predicate(value)
            return value
        except TypeError:
            self.reader.add_error(messages[0], section_key)
            return default_value
        except KeyError:
            self.reader.add_warning(messages[1], section_key, key)
            return default_value
        except ValueError:
            self.reader.add_warning(messages[2], section_key, key)
            return default_value
        except AssertionError:
            self.reader.add_warning(messages[3], section_key, key)
            return default_value

    def _build_tournament_handicap(self, section_key: str) -> HandicapTournament:
        try:
            handicap_section = self.reader[section_key]
        except KeyError:
            return HandicapTournament()
        section_keys: list[str] = [
            'initial_time',
            'increment',
            'penalty_step',
            'penalty_value',
            'min_time',
        ]
        for key in self.reader[section_key]:
            if key not in section_keys:
                self.reader.add_warning('option inconnue', section_key, key)
        ignore_message = 'configuration de handicap ignorée'
        positive_messages = (
            f'La rubrique est en fait une option, {ignore_message}',
            f'option absente, {ignore_message}',
            f'un entier est attendu, {ignore_message}',
            f'un entier strictement positif est attendu, {ignore_message}'
        )
        non_negative_messages = (
            f'La rubrique est en fait une option, {ignore_message}'
            f'option absente, {ignore_message}',
            f'un entier est attendu, {ignore_message}',
            f'un entier positif est attendu, {ignore_message}'
        )

        key = 'initial_time'
        initial_time: int | None = self._get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if initial_time is None:
            return HandicapTournament()

        key = 'increment'
        increment: int | None = self._get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 0,
            None,
            *non_negative_messages
        )
        if increment is None:
            return HandicapTournament()

        key = 'penalty_step'
        penalty_step: int | None = self._get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_step is None:
            return HandicapTournament()

        key = 'penalty_value'
        penalty_value: int | None = self._get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_value is None:
            return HandicapTournament()

        key = 'min_time'
        min_time: int | None = self._get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            *positive_messages
        )
        if min_time is None:
            return HandicapTournament()

        return HandicapTournament(
            initial_time,
            increment,
            penalty_step,
            penalty_value,
            min_time,
        )

    def _build_templates(self):
        template_ids: list[str] = self.reader.get_subsection_keys_with_prefix('template')
        if not template_ids:
            self.reader.add_debug('aucun modèle déclaré', 'template.*')
            return
        for template_id in template_ids:
            self._build_template(template_id)
        if not len(self.templates):
            self.reader.add_debug('aucun modèle initialisé')

    def _build_template(self, template_id: str):
        template: Template = Template(template_id)
        section_key = f'template.{template_id}'
        template_section = self.reader[section_key]
        for key, value in template_section.items():
            if key not in self.screen_keys:
                self.reader.add_warning(
                    'option de modèle inconnue, ignorée',
                    section_key,
                    key
                )
            else:
                template.add_data(None, key, value)
                self.reader.add_debug(f'option {key} = {value}', section_key)
        subsection_keys = self.reader.get_subsection_keys_with_prefix(
            section_key,
            first_level_only=False
        )
        for sub_section_key in subsection_keys:
            splitted = sub_section_key.split('.')
            if splitted[0] not in ScreenType.names() or len(splitted) > 2:
                self.reader.add_warning(
                    'rubrique de modèle non valide, ignorée',
                    f'{section_key}.{sub_section_key}'
                )
                continue
            # NOTE(Amaras) Nesting subsections in the Python INI parser
            # (ConfigParser) only works because nested subsections have
            # unique names. Is this behaviour expected?
            subsection_key = f'{section_key}.{sub_section_key}'
            for key, value in self.reader.items(subsection_key):
                if key not in self.screen_set_keys:
                    self.reader.add_warning(
                        'option de modèle inconnue, ignorée',
                        subsection_key,
                        key
                    )
                else:
                    template.add_data(sub_section_key, key, value)
                    self.reader.add_debug(f'option [{sub_section_key}].{key} = {value}', section_key)
        self.templates[template_id] = template

    screen_keys: list[str] = [
        'type',
        'name',
        'columns',
        'menu_text',
        'show_timer',
        'menu',
        'update',
        'limit',
    ]

    screen_set_keys = ['tournament', 'name', 'first', 'last', 'part', 'parts', ]

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
