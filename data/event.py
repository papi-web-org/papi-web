import datetime
import re
from functools import total_ordering
from pathlib import Path
from contextlib import suppress

import time

from typing import List, Optional, Dict, Tuple, Iterator, NamedTuple
from logging import Logger

from common.config_reader import ConfigReader
from common.logger import get_logger
from data.board import Board
from data.result import Result
from data.rotator import Rotator, ROTATOR_DEFAULT_DELAY
from data.screen import SCREEN_TYPE_NAMES, SCREEN_TYPE_BOARDS, SCREEN_TYPE_PLAYERS, SCREEN_TYPE_RESULTS
from data.screen import ScreenSet, ScreenBoards, ScreenPlayers, ScreenResults, AScreen
from data.template import Template
from data.timer import Timer, TimerHour
from data.tournament import Tournament

logger: Logger = get_logger()

EVENTS_PATH: Path = Path('events')

class HandicapTournament(NamedTuple):
    initial_time: Optional[int] = None
    increment: Optional[int] = None
    penalty_step: Optional[int] = None
    penalty_value: Optional[int] = None
    min_time: Optional[int] = None


@total_ordering
class Event(ConfigReader):
    def __init__(self, event_id: str, silent: bool = True):
        self.__id: str = event_id
        super().__init__(Path(EVENTS_PATH, self.id + '.ini'), silent=silent)
        self.__name: str = self.__id
        self.__path: Path = Path('papi')
        self.__css: Optional[str] = None
        self.__update_password: Optional[str] = None
        self.__tournaments: Dict[str, Tournament] = {}
        self.__templates: Dict[str, Template] = {}
        self.__screens_by_family_id: Dict[str, List[AScreen]] = {}
        self.__screens: Dict[str, AScreen] = {}
        self.__rotators: Dict[str, Rotator] = {}
        self.__timer: Optional[Timer] = None
        if self.errors or self.warnings:  # warning when the configuration file is not found
            return
        self.__build_root()
        if self.errors:
            return
        self.__build_tournaments()
        if self.errors:
            return
        self.__build_templates()
        if self.errors:
            return
        self.__build_families()
        if self.errors:
            return
        self.__build_screens()
        if self.errors:
            return
        self.__build_rotators()
        if self.errors:
            return
        self.__build_timer()

    @property
    def id(self) -> str:
        return self.__id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def path(self) -> Path:
        return self.__path

    @property
    def css(self) -> Optional[str]:
        return self.__css

    @property
    def update_password(self) -> Optional[str]:
        return self.__update_password

    @property
    def tournaments(self) -> Dict[str, Tournament]:
        return self.__tournaments

    @property
    def templates(self) -> Dict[str, Template]:
        return self.__templates

    @property
    def screens(self) -> Dict[str, AScreen]:
        return self.__screens

    @property
    def rotators(self) -> Dict[str, Rotator]:
        return self.__rotators

    @property
    def timer(self) -> Optional[Timer]:
        return self.__timer

    def __build_root(self):
        section_key: str = 'event'
        if not self.has_section(section_key):
            self._add_error('rubrique absente', section_key)
            return
        section = self[section_key]

        key = 'name'
        default_name = self.__id
        try:
            self.__name = section[key]
            if not self.__name:
                self._add_error('option vide', section, key)
                return
        except KeyError:
            self.__name = default_name
            self._add_info(
                   f'option absente, par défaut [{default_name}]',
                   section_key,
                   key
            )
        except TypeError:
            # NOTE(Amaras) This could happen because of a TOC/TOU bug
            # https://en.wikipedia.org/wiki/Time-of-check_to_time-of-use
            # After this, the secion has already been retrieved, so no future
            # access will throw a TypeError.
            self._add_error(
                    'la rubrique est devenue une option, erreur fatale',
                    section_key
            )
            return

        key = 'path'
        default_path: Path = Path('papi')
        try:
            self.__path = Path(section[key])
        except KeyError:
            self.__path = default_path
            self._add_debug(
                    f'option absente, par défaut [{default_path}]',
                    section_key,
                    key
            )
        # NOTE(Amaras) This could be a TOC/TOU bug
        # What would our threat model be for this?
        if not self.path.exists():
            self._add_error(
                    f"le répertoire [{self.path}] n'existe pas",
                    section_key,
                    key
            )
            return
        elif not self.path.is_dir():
            self._add_error(
                    f"[{self.path}] n'est pas un répertoire",
                    section_key,
                    key
            )

        key = 'css'
        try:
            self.__css = section[key]
        except KeyError:
            self._add_debug('option absente', section_key, key)

        key = 'update_password'
        try:
            self.__update_password = section[key]
        except KeyError:
            self._add_info(
                'option absente, aucun mot de passe ne sera demandé pour les saisies',
                section_key,
                key
            )

        section_keys: List[str] = ['name', 'path', 'update_password', 'css', ]
        for key, value in section.items():
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)

    def __rename_section(self, old_name: str, new_name: str):
        # NOTE(Amaras) this can add values that are in DEFAULTSEC if any.
        # This can also cause a crash if we're trying to delete DEFAULTSEC,
        # as deleting DEFAUTLSEC causes a ValueError.
        self[new_name] = self[old_name]
        del self[old_name]

    def __build_tournaments(self):
        tournament_ids: List[str] = self._get_subsections_with_prefix('tournament')
        # NOTE(Amaras) Special case of tournament: handicap depends on
        # the [tournament] section being there.
        if 'handicap' in tournament_ids:
            tournament_ids.remove('handicap')
        if self.has_section('tournament'):
            if tournament_ids:
                sections: str = ', '.join(
                    ('[tournament.' + id + ']' for id in tournament_ids)
                )
                self._add_error(
                    "la rubrique [tournament] ne doit être utilisée que lorsque"
                    " l'évènement ne compte qu'un tournoi, d'autres rubriques "
                    f"sont présentes ({sections})",
                    'tournament.*'
                )
                return
            default_tournament_id: str = 'default'
            old_tournament_section: str = 'tournament'
            new_tournament_section: str = 'tournament.' + default_tournament_id
            self.__rename_section(old_tournament_section, new_tournament_section)
            self._add_debug(
                f'un seul tournoi, la rubrique [{old_tournament_section}] a '
                f'été renommée [{new_tournament_section}]',
                old_tournament_section
            )
            old_handicap_section: str = 'tournament.handicap'
            if self.has_section(old_handicap_section):
                new_handicap_section = f'tournament.{default_tournament_id}.handicap'
                self.__rename_section(old_handicap_section, new_handicap_section)
                self._add_debug(
                    f'un seul tournoi, la rubrique [{old_handicap_section}] a '
                    f'été renommée [{new_tournament_section}]'
                )
            tournament_ids.append(default_tournament_id)
        elif not tournament_ids:
            self._add_error('aucun tournoi trouvé', 'tournament.*')
            return
        for tournament_id in tournament_ids:
            self.__build_tournament(tournament_id)
        if not len(self.__tournaments):
            self._add_error('aucun tournoi initialisé')

    def __build_tournament(self, tournament_id: str):
        section_key: str = f'tournament.{tournament_id}'
        try:
            section = self[section_key]
        except KeyError:
            self._add_error('Pas de tournoi trouvé', section_key)
        key = 'path'
        default_path: Path = self.path
        try:
            path = section[key]
        except KeyError:
            self._add_debug(
                    f'option absente, par dfault [{default_path}]',
                    section_key,
                    key
            )
            path: Path = default_path
        except TypeError:
            self._add_error(
                    f'La rubrique [{section_key}] est en fait une option',
                    section_key
            )
        # NOTE(Amaras) TOC/TOU bug
        if not path.exists():
            self._add_error(
                    f"le répertoire [{path}] n'existe pas, tournoi ignoré",
                    section_key,
                    key
            )
            return
        if not path.is_dir():
            self._add_error(
                    f"[{path}] n'est pas un répertoire, tournoi ignoré",
                    section_key,
                    key
            )
            return
        key = 'filename'
        filename: Optional[str] = section.get(key)
        key = 'ffe_id'
        ffe_id: Optional[int] = None
        try:
            ffe_id = int(section[key])
            assert ffe_id >= 1
        except KeyError:
            pass
        except ValueError:
            self._add_warning('un entier est attendu', section_key, key)
            ffe_id = None
        except AssertionError:
            self._add_warning(
                    'un entier positif non nul est attendu',
                    section_key,
                    key
            )
            ffe_id = None
        if filename is None and ffe_id is None:
            self._add_error(
                    'ni [filename] ni [ffe_id] ne sont indiqués, tournoi ignoré',
                    section_key
            )
            return
        if filename is None:
            filename = str(ffe_id)
        file: Path = path / f'{filename}.papi'
        # NOTE(Amaras) TOC/TOU bug
        if not file.exists():
            self._add_error(f'le fichier [{file}] n\'existe pas, tournoi ignoré', section)
            return
        if not file.is_file():
            self._add_error(f'[{file}] n\'est pas un fichier, tournoi ignoré', section)
            return
        key = 'name'
        default_name: str = tournament_id
        try:
            name = section[key]
        except KeyError:
            self._add_info(
                    f'option absente, par défaut [{default_name}]',
                    section_key,
                    key
            )
            name = default_name
        key = 'ffe_password'
        ffe_password: Optional[str] = None
        if ffe_id is not None:
            try:
                ffe_password = section[key]
                if not re.match('^[A-Z]{10}$', ffe_password):
                    self._add_warning(
                        'un mot de 10 lettres majuscules est attendu, le mot '
                        'de passe est ignoré (les opérations sur le site web '
                        'de la FFE ne seront pas disponibles',
                        section_key,
                        key
                    )
                    ffe_password = None
            except KeyError:
                self._add_info(
                    'option absente, les opération sur le site web de la FFE '
                    'ne seront pas disponibles',
                    section_key,
                    key
                )
        elif self.has_option(section_key, key):
            self._add_info(
                "option ignorée quand l'option [ffe_id] n'est pas indiquée",
                section_key,
                key
            )
        section_keys: List[str] = [
                'path',
                'filename',
                'name',
                'ffe_id',
                'ffe_password',
            ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)
        handicap_section = 'tournament.' + tournament_id + '.handicap'
        handicap_values = self.__build_tournament_handicap(handicap_section)
        if handicap_values[0] is not None and ffe_id is not None:
            self._add_warning(
                'les tournois à handicap ne devraient pas être homologués',
                handicap_section
            )
        self.__tournaments[tournament_id] = Tournament(
            tournament_id,
            name,
            file,
            ffe_id,
            ffe_password,
            *handicap_values
        )
    def _get_value_with_warning(
        self,
        section: dict,
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
            self._add_error(messages[0], section_key)
            return default_value
        except KeyError:
            self._add_warning(messages[1], section_key, key)
            return default_value
        except ValueError:
            self._add_warning(messages[2], section_key, key)
            return default_value
        except AssertionError:
            self._add_warning(messages[3], section_key, key)
            return default_value

    def __build_tournament_handicap(self, section: str) -> HandicapTournament:
        try:
            handicap_section = self[section]
        except KeyError:
            return HandicapTournament()
        section_keys: List[str] = [
            'initial_time',
            'increment',
            'penalty_step',
            'penalty_value',
            'min_time',
        ]
        for key in self[section]:
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)
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
        initial_time: Optional[int] = self._get_value_with_warning(
            handicap_section,
            section,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if initial_time is None:
            return HandicapTournament()

        key = 'increment'
        increment: Optional[int] = self._get_value_with_warning(
            handicap_section,
            section,
            key,
            int,
            lambda x: x >= 0,
            None,
            *non_negative_messages
        )
        if increment is None:
            return HandicapTournament()

        key = 'penalty_step'
        penalty_step: Optional[int] = self._get_value_with_warning(
            handicap_section,
            section,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_step is None:
            return HandicapTournament()

        key = 'penalty_value'
        penalty_value: Optional[int] = self._get_value_with_warning(
            handicap_section,
            section,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_value is None:
            return HandicapTournament()

        key = 'min_time'
        min_time: Optional[int] = self._get_value_with_warning(
            handicap_section,
            section,
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

    def __build_templates(self):
        template_ids: List[str] = self._get_subsections_with_prefix('template')
        if not template_ids:
            self._add_debug('aucun modèle déclaré', 'template.*')
            return
        for template_id in template_ids:
            self.__build_template(template_id)
        if not len(self.__templates):
            self._add_debug('aucun modèle initialisé')

    def __build_template(self, template_id: str):
        template: Template = Template(template_id)
        section = f'template.{template_id}'
        template_section = self[section]
        for key, value in template_section.items():
            if key not in self.screen_keys:
                self._add_warning(
                    'option de modèle inconnue, ignorée',
                    section,
                    key
                )
            else:
                template.add_data(None, key, value)
        subsections = self._get_subsections_with_prefix(
            section,
            first_level_only=False
        )
        for sub_section in subsections:
            splitted = sub_section.split('.')
            if splitted[0] not in SCREEN_TYPE_NAMES or len(splitted) > 2:
                self._add_warning(
                    'rubrique de modèle non valide, ignorée',
                    f'{section}.{sub_section}'
                )
                continue
            # NOTE(Amaras) Nesting subsections in the Python INI parser
            # (ConfigParser) only works because nested subsections have
            # unique names. Is this behaviour expected?
            subsection_key = f'{section}.{sub_section}'
            for key, value in self.items(subsection_key):
                if key not in self.screen_set_keys:
                    self._add_warning(
                        'option de modèle inconnue, ignorée',
                        subsection_key,
                        key
                    )
                else:
                    template.add_data(sub_section, key, value)
        self.__templates[template_id] = template

    def __build_families(self):
        family_ids: List[str] = self._get_subsections_with_prefix('family')
        if not family_ids:
            self._add_debug('aucune famille déclarée', 'family.*')
            return
        for family_id in family_ids:
            self.__build_family(family_id)

    def __build_family(self, family_id: str):
        section = f'family.{family_id}'
        family_section = self[section]
        section_keys = ['template', 'range', ]
        for key in family_section:
            if key not in section_keys:
                self._add_warning(
                    'option de famille inconnue, ignorée',
                    section,
                    key
                )
        key = 'template'
        try:
            template_id = family_section[key]
        except KeyError:
            self._add_warning('option absente, famille ignorée', section, key)
            return
        if template_id not in self.templates:
            self._add_warning(
                f"le modèle [{template_id}] n'existe pas, famille ignorée",
                section,
                key
            )
            return
        template: Template = self.templates[template_id]
        key = 'range'
        try:
            range_str = family_section[key]
        except KeyError:
            self._add_warning('option absente, famille ignorée', section, key)
            return

        family_indices: Optional[List[str]] = None
        # NOTE(Amaras) The walrus operator (:= aka assignment expression)
        # is available since Python 3.8 and this use case is one of the
        # motivational examples for its introduction, so let's use it.
        if (matches := re.match(r'^(\d+)-(\d+)$', range_str)):
            first_number = int(matches.group(1))
            last_number = int(matches.group(2))
            if first_number <= last_number:
                family_indices = list(
                    map(str, range(first_number, last_number + 1))
                )
        elif (matches := re.match('^([A-Z])-([A-Z])$', range_str)):
            first_letter = matches.group(1)
            last_letter = matches.group(2)
            if ord(first_letter) <= ord(last_letter):
                family_indices = list(
                    map(chr, range(ord(first_letter), ord(last_letter) + 1))
                )
        elif (matches := re.match('^([a-z])-([a-z])$', range_str)):
            first_letter = matches.group(1)
            last_letter = matches.group(2)
            if ord(first_letter) <= ord(last_letter):
                family_indices = list(
                    map(chr, range(ord(first_letter), ord(last_letter) + 1))
                )
        if family_indices is None:
            self._add_warning(
                f'valeurs [{range_str}] non valides, famille ignorée',
                section,
                key
            )
            return
        for screen_index in family_indices:
            screen_id = f'{section.split(".")[1]}-{screen_index}'
            screen_section = f'screen.{screen_id}'
            # TODO(Amaras) Could this check be replaced with a .setdefault()?
            # https://docs.python.org/3/library/stdtypes.html?highlight=dict#dict.setdefault
            if not self.has_section(screen_section):
                self._add_debug('rubrique ajoutée', screen_section)
                self[screen_section] = {}
            self[screen_section]['__family__'] = family_id
            for sub_section, properties in template.data.items():
                if sub_section is None:
                    new_section = screen_section
                else:
                    new_section = f'{screen_section}.{sub_section}'
                # TODO(Amaras) setdefault()?
                if not self.has_section(new_section):
                    self._add_debug('rubrique ajoutée', new_section)
                    self.add_section(new_section)
                for key, value in properties.items():
                    # TODO(Amaras) This is definitely a .setdefault() in waiting
                    if not self.has_option(new_section, key):
                        new_value = value.replace('?', screen_index)
                        self[new_section][key] = new_value
                        self._add_debug(
                            f'option ajoutée avec la valeur [{new_value}]',
                            new_section,
                            key
                        )
            self._add_debug(f'écran [{screen_id}] ajouté', section)

    def __build_screens(self):
        screen_ids: List[str] = self._get_subsections_with_prefix('screen')
        if not screen_ids:
            self._add_info(
                'aucun écran défini, ajout des écrans par défaut',
                'screen.*'
            )
            for tournament_id in self.tournaments:
                if not self.tournaments[tournament_id].file:
                    continue
                name_prefix: str = ''
                if len(self.tournaments) > 1:
                    name_prefix = f'{self.tournaments[tournament_id].name} - '
                data: Dict[str, Dict[str, str]] = {
                    f'{tournament_id}-{SCREEN_TYPE_BOARDS}-update': {
                        'type': SCREEN_TYPE_BOARDS,
                        'update': 'on',
                        'name': f'{name_prefix}Saisie des résultats',
                        'menu_text': f'{name_prefix}Saisie des résultats',
                    },
                    f'{tournament_id}-{SCREEN_TYPE_BOARDS}-view': {
                        'type': SCREEN_TYPE_BOARDS,
                        'update': 'off',
                        'name': f'{name_prefix}Appariements par échiquier',
                        'menu_text': f'{name_prefix}Appariements',
                    },
                    f'{tournament_id}-{SCREEN_TYPE_PLAYERS}': {
                        'type': SCREEN_TYPE_PLAYERS,
                        'name': f'{name_prefix}Appariements par ordre alphabétique',
                        'columns': '2',
                        'menu_text': f'{name_prefix}Ordre alphabétique',
                    },
                    f'{tournament_id}-{SCREEN_TYPE_RESULTS}': {
                        'type': SCREEN_TYPE_RESULTS,
                        'name': f'{name_prefix}Derniers résultats',
                        'menu_text': f'{name_prefix}Derniers résultats',
                    },
                }
                menu: str = ','.join((screen_id for screen_id in data))
                for screen_id, options in data.items():
                    section: str = f'screen.{screen_id}'
                    self[section] = options
                    self[section]['menu'] = menu
                    screen_ids.append(screen_id)
                    self._add_debug(
                        f"l'écran [{screen_id}] a été ajouté",
                        'screen.*'
                    )
                data: Dict[str, Dict[str, str]] = {
                    f'{tournament_id}-{SCREEN_TYPE_BOARDS}-input.{SCREEN_TYPE_BOARDS}': {
                        'tournament': tournament_id,
                    },
                    f'{tournament_id}-{SCREEN_TYPE_BOARDS}-print.{SCREEN_TYPE_BOARDS}': {
                        'tournament': tournament_id,
                    },
                    f'{tournament_id}-{SCREEN_TYPE_PLAYERS}.players': {
                        'tournament': tournament_id,
                    },
                }
                for screen_id, options in data.items():
                    section: str = f'screen.{screen_id}'
                    self[section] = options
        for screen_id in screen_ids:
            self.__build_screen(screen_id)
        if not len(self.__screens):
            self._add_warning("aucun écran n'a été initialisé")
        view_menu: List[AScreen] = []
        update_menu: List[AScreen] = []
        for screen in self.__screens.values():
            if screen.menu_text:
                if screen.update:
                    update_menu.append(screen)
                else:
                    view_menu.append(screen)
        for screen in self.__screens.values():
            if screen.menu is None:
                screen.set_menu_screens([])
                continue
            if screen.menu == 'view':
                screen.set_menu_screens(view_menu)
                continue
            if screen.menu == 'update':
                screen.set_menu_screens(update_menu)
                continue
            if screen.menu == 'family':
                if screen.family_id is None:
                    self._add_warning(
                        "l'écran n'appartient pas à une famille, aucun menu "
                        "ne sera affiché",
                        f'screen.{screen.id}',
                        'menu'
                    )
                    screen.set_menu_screens([])
                    continue
                screen.set_menu_screens(
                    self.__screens_by_family_id[screen.family_id]
                )
                continue
            menu_screens: List[AScreen] = []
            for screen_id in screen.menu.replace(' ', '').split(','):
                if screen_id:
                    if screen_id in self.screens:
                        menu_screens.append(self.screens[screen_id])
                    else:
                        self._add_warning(
                            f"l'écran [{screen_id}] n'existe pas, ignoré",
                            f'screen.{screen.id}',
                            'menu'
                        )
            screen.set_menu(', '.join([screen.id for screen in menu_screens]))
            screen.set_menu_screens(menu_screens)

    screen_keys: List[str] = [
        'type',
        'name',
        'columns',
        'menu_text',
        'show_timer',
        'menu',
        'update',
        'limit',
    ]

    def __build_screen(self, screen_id: str):
        section = f'screen.{screen_id}'
        screen_section = self[section]
        key = 'template'
        with suppress(KeyError):
            template_id = screen_section[key]
            if template_id not in self.templates:
                self._add_warning(
                    f"le modèle [{template_id}] n'existe pas, écran ignoré",
                    section,
                    key
                )
                return
            template: Template = self.templates[template_id]
            for sub_section, properties in template.data.items():
                if sub_section is None:
                    new_section = section
                else:
                    new_section = f'{section}.{sub_section}'
                if not new_section not in self:
                    self[new_section] = {}
                for key, value in properties.items():
                    self[new_section].setdefault(key, value)
        key = 'type'
        try:
            screen_type = screen_section[key]
        except KeyError:
            self._add_warning(
                f"type d'écran invalide [{screen_type}], écran ignoré",
                section,
                key
            )
            return
        screen_set_sections: List[str] = []
        screen_set_single_section = f'{section}.{screen_type}'
        if screen_type == SCREEN_TYPE_BOARDS:
            if screen_set_single_section in self:
                screen_set_sections = [screen_set_single_section, ]
                for screen_set_sub_section in self._get_subsections_with_prefix(screen_set_single_section):
                    self._add_warning(
                        'rubrique non prise en compte, supprimez la rubrique '
                        f'[{screen_set_single_section}] pour cela',
                        f'{screen_set_single_section}.{screen_set_sub_section}'
                    )
            else:
                screen_set_sections = [
                    f'{screen_set_single_section}.{sub_section}'
                    for sub_section
                    in self._get_subsections_with_prefix(screen_set_single_section)
                ]
            if not screen_set_sections:
                if len(self.tournaments) == 1:
                    self[screen_set_single_section] = {}
                    screen_set_sections.append(screen_set_single_section)
                    self._add_info(
                        'un seul tournoi, la rubrique '
                        f'[{screen_set_single_section}] a été ajoutée',
                        section
                    )
                else:
                    self._add_warning(
                        'rubrique absente, écran ignoré',
                        screen_set_single_section
                    )
                    return
        elif screen_type == SCREEN_TYPE_PLAYERS:
            if screen_set_single_section in self:
                screen_set_sections = [screen_set_single_section, ]
                for screen_set_sub_section in self._get_subsections_with_prefix(screen_set_single_section):
                    self._add_warning(
                        'rubrique non prise en compte, supprimez la rubrique '
                        f'[{screen_set_single_section}] pour cela',
                        f'{screen_set_single_section}.{screen_set_sub_section}'
                    )
            else:
                screen_set_sections = [
                    screen_set_single_section + '.' + sub_section
                    for sub_section in self._get_subsections_with_prefix(screen_set_single_section)
                ]
            if not screen_set_sections:
                if len(self.tournaments) == 1:
                    self[screen_set_single_section] = {}
                    screen_set_sections.append(screen_set_single_section)
                    self._add_info(
                        'un seul tournoi, la rubrique '
                        f'[{screen_set_single_section}] a été ajoutée',
                        section
                    )
                else:
                    self._add_warning(
                        'rubrique absente, écran ignoré',
                        screen_set_single_section
                    )
                    return
        elif screen_type == SCREEN_TYPE_RESULTS:
            pass
        else:
            self._add_warning(
                f"type d'écran [{screen_type}] inconnu, écran ignoré",
                section
            )
            return
        key = 'columns'
        default_columns: int = 1
        try:
            columns = int(screen_section[key])
            assert columns >= 1
        except KeyError:
            columns = default_columns
        except ValueError:
            self._add_warning(
                f'un entier est attendu, par défault [{default_columns}]',
                section,
                key
            )
            columns = default_columns
        except AssertionError:
            self._add_warning(
                'un entier strictement positif est attendu, par défaut '
                f'[{default_columns}]',
                section,
                key
            )
            columns = default_columns
        screen_sets: Optional[List[ScreenSet]] = None
        if screen_type in [SCREEN_TYPE_BOARDS, SCREEN_TYPE_PLAYERS, ]:
            screen_sets = self.__build_screen_sets(screen_set_sections, columns)
            if not screen_sets:
                if screen_type == SCREEN_TYPE_BOARDS:
                    self._add_warning(
                        "pas d'ensemble d'échiquiers déclaré, écran ignoré",
                        section
                    )
                    # NOTE(Amaras) should this return?
                else:
                    self._add_warning(
                        "pas d'ensemble de joueur·euses déclaré, écran ignoré",
                        section
                    )
                return
        key = 'name'
        screen_name: Optional[str] = None
        try:
            screen_name = screen_section[key]
        except KeyError:
            if screen_type == SCREEN_TYPE_RESULTS:
                screen_name = 'Derniers résultats'
                self._add_debug(
                    f'option absente, par défault [{screen_name}]',
                    section,
                    key
                )
            else:
                self._add_debug(
                    'option absente, le nom du premier ensemble sera utilisé',
                    section,
                    key
                )
        key = 'menu_text'
        menu_text = screen_section.get(key)
        key = 'menu'
        default_menu: Optional[str] = None
        menu: Optional[str] = default_menu
        menu = screen_section.get(key)
        if menu is None:
            self._add_info(
                'option absente, aucun menu ne sera affiché (indiquer [none] '
                'pour supprimer ce message)',
                section,
                key
            )
        elif menu == 'none':
            menu = None
        elif menu == 'family':
            if screen_type == SCREEN_TYPE_RESULTS:
                self._add_warning(
                    "l'option [family] n'est pas autorisée pour les écrans de "
                    f'type [{screen_type}], aucun menu ne sera affiché',
                    section,
                    key
                )
                menu = None
        elif menu == 'view':
            pass
        elif menu == 'update':
            pass
        elif ',' in menu:
            pass
        else:
            self._add_warning(
                "[none], [family], [view], [update] ou une liste d'écrans "
                'séparés par des virgules sont attendus, aucun menu ne sera '
                'affiché',
                section,
                key
            )
            menu = None
        key = 'show_timer'
        default_show_timer: bool = True
        show_timer: bool = default_show_timer
        if key in screen_section:
            show_timer = self.getboolean(section, key)
            if show_timer is None:
                self._add_warning(
                    f'un booléen est attendu, par défaut [{default_show_timer}]',
                    section,
                    key
                )
        key = 'update'
        default_update: bool = False
        update: bool = default_update
        if screen_type == SCREEN_TYPE_BOARDS:
            if key in screen_section:
                update = self._getboolean_safe(section, key)
                if update is None:
                    self._add_warning(
                        'un booléen est attendu, écran ignoré',
                        section,
                        key
                    )
                    return
        else:
            if key in screen_section:
                self._add_warning(
                    "l'option n'est pas autorisée pour les écrans de type "
                    f"[{screen_type}], ignorée",
                    section,
                    key
                )
        key = 'limit'
        default_limit: int = 0
        limit: int = default_limit
        if screen_type == SCREEN_TYPE_RESULTS:
            if key in screen_section:
                limit = self._getint_safe(section, key)
                if limit is None:
                    self._add_warning(
                        'un entier positif ou nul ets attendu, par défaut '
                        f'[{default_limit}]',
                        section,
                        key
                    )
                    limit = default_limit
                if limit > 0 and limit % columns > 0:
                    limit = columns * (limit // columns + 1)
                    self._add_info(
                        f'positionné à [{limit}] pour tenir sur {columns} '
                        'colonnes',
                        section,
                        key
                    )
        else:
            if key in screen_section:
                self._add_warning(
                    "l'option n'est pas autorisée pour les écrans de type "
                    f"[{screen_type}], ignorée",
                    section,
                    key
                )
        key = '__family__'
        family_id: Optional[str] = None
        if key in screen_section:
            family_id: str = self.get(section, key)
        if screen_type == SCREEN_TYPE_BOARDS:
            self.__screens[screen_id] = ScreenBoards(
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                screen_sets,
                update
            )
        elif screen_type == SCREEN_TYPE_PLAYERS:
            self.__screens[screen_id] = ScreenPlayers(
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                screen_sets
            )
        elif screen_type == SCREEN_TYPE_RESULTS:
            self.__screens[screen_id] = ScreenResults(
                self.id,
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                limit
            )
        for key, value in self.items(section):
            if key not in self.screen_keys + ['template', '__family__', ]:
                self._add_warning('option absente', section, key)
        if family_id is not None:
            if family_id not in self.__screens_by_family_id:
                self.__screens_by_family_id[family_id] = []
            self.__screens_by_family_id[family_id].append(self.__screens[screen_id])

    screen_set_keys = ['tournament', 'name', 'first', 'last', 'part', 'parts', ]

    def __build_screen_sets(self, sections: List[str], columns: int) -> List[ScreenSet]:
        screen_sets: List[ScreenSet] = []
        for section in sections:
            try:
                current_section = self[section]
            except KeyError:
                self._add_error('rubrique non trouvée', section)
                return screen_sets
            key = 'tournament'
            if key not in current_section
                if len(self.tournaments) == 1:
                    current_section[ley] = list(self.tournaments.keys())[0]
                else:
                    self._add_warning(
                        'option absente, écran ignoré',
                        section,
                        key
                    )
                    continue
            tournament_id: str = self.get(section, key)
            if tournament_id not in self.tournaments:
                self._add_warning(
                    f"le tournoi [{tournament_id}] n'existe pas, écran ignoré",
                    section,
                    key
                )
                continue
            if not self.tournaments[tournament_id].file:
                self._add_warning(
                    f"le fichier du tournoi [{tournament_id}] n'existe pas, "
                    "l'ensemble est ignoré",
                    section,
                    key
                )
                continue
            if (
                ('first' in current_section or 'last' in current_section) and
                ('part' in current_section or 'parts' in current_section)
            ):
                self._add_warning(
                    'les options [part]/[parts] et [first]/[last] ne sont pas '
                    'compatibles, écran ignoré',
                    section
                )
                continue
            key = 'first'
            first: Optional[int] = None
            if key in current_section:
                first = self._getint_safe(section, key, minimum=1)
                if first is None:
                    self._add_warning(
                        'un entier positif non nul est attendu, ignoré',
                        section,
                        key
                    )
            key = 'last'
            last: Optional[int] = None
            if key in current_section:
                last = self._getint_safe(section, key)
                if last is None:
                    self._add_warning(
                        'un entier positif non nul est attendu, ignoré',
                        section,
                        key
                    )
            if first is not None and last is not None and first > last:
                self._add_warning(
                    f'intervalle [{first}-{last}] non valide',
                    section
                )
                continue
            key = 'part'
            part: Optional[int] = None
            if key in current_section:
                part = self._getint_safe(section, key)
                if part is None:
                    self._add_warning(
                        'un entier positif non nul est attendu, ignoré',
                        section,
                        key
                    )
            key = 'parts'
            parts: Optional[int] = None
            if key in current_section:
                parts = self._getint_safe(section, key)
                if parts is None:
                    self._add_warning(
                        'un entier positif non nul est attendu, ignoré',
                        section,
                        key
                    )
            if (
                (part is None and parts is not None) or
                (part is not None and parts is None)
            ):
                # NOTE(Amaras) this should probably be another warning
                self._add_warning(
                    'les options [part]/[parts] et [first]/[last] ne sont pas '
                    'compatibles, écran ignoré',
                    section
                )
            if part is not None and part > parts:
                self._add_warning(
                    f"la partie [{part}] sur [{parts}] n'est pas valide, écran "
                    "ignoré",
                    section
                )
            key = 'name'
            name: Optional[str] = None
            if key in current_section:
                name = self.get(section, key)
            for key, value in self.items(section):
                if key not in self.screen_set_keys:
                    self._add_warning('option inconnue', section, key)
            screen_sets.append(ScreenSet(
                self.tournaments[tournament_id],
                columns,
                first=first,
                last=last,
                part=part,
                parts=parts,
                name=name))
        return screen_sets

    def __build_rotators(self):
        rotator_ids: List[str] = self._get_subsections_with_prefix('rotator')
        if not rotator_ids:
            self._add_debug('aucun écran rotatif déclaré', 'rotator.*')
            return
        for rotator_id in rotator_ids:
            self.__build_rotator(rotator_id)
        if not len(self.__rotators):
            self._add_debug('aucun écran rotatif défini')

    def __build_rotator(self, rotator_id: str):
        section = f'rotator.{rotator_id}'
        rotator_section = self[section]
        section_keys: List[str] = ['screens', 'families', 'delay', ]
        for for key, value in rotator_section:
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)
        key = 'delay'
        default_delay: int = ROTATOR_DEFAULT_DELAY
        delay: int = default_delay
        # if not self.has_option(section, key):
        if key not in rotator_section:
            self._add_debug(
                f'option absente, par défaut [{default_delay}]',
                section,
                key
            )
        else:
            delay = self._getint_safe(section, key, minmum=1)
            if delay is None:
                self._add_warning(
                    f'un entier positif non nul est attendu, par défaut '
                    f'[{default_delay}]',
                    section,
                    key
                )
        if 'screens' not in rotator_section and 'families' not in rotator_section:
            self._add_info(
                'au moins une option parmi [screens] et [families] doit être '
                'définie, écran rotatif ignoré',
                section
            )
            return
        screens: List[AScreen] = []
        key = 'families'
        if key in rotator_section:
            for family_id in str(rotator_section.get(key)).replace(' ', '').split(','):
                if family_id:
                    if family_id not in self.__screens_by_family_id:
                        self._add_warning(
                            f"la famille [{family_id}] n'existe pas, ignorée",
                            section,
                            key
                        )
                    else:
                        screens += self.__screens_by_family_id[family_id]
        key = 'screens'
        # if self.has_option(section, key):
        if key in rotator_section:
            for screen_id in str(rotator_section.get(key)).replace(' ', '').split(','):
                if screen_id:
                    if screen_id not in self.screens:
                        self._add_warning(
                            f"l'écran [{screen_id}] n'existe pas, ignoré",
                            section,
                            key
                        )
                    elif self.screens[screen_id] not in screens:
                        screens.append(self.screens[screen_id])

        if 'screens' not in rotator_section and not 'families' in rotator_section:
            self._add_warning(
                'au moins une des deux options [screens] ou [families] doit '
                'être utilisée, écran rotatif ignoré',
                section
            )
            return
        if not screens:
            self._add_warning('aucun écran, écran rotatif ignoré', section, key)
            return
        self.__rotators[rotator_id] = Rotator(rotator_id, delay, screens)

    def __build_timer(self):
        timer: Timer = Timer()
        section = 'timer.hour'
        hour_ids: List[str] = self._get_subsections_with_prefix(section)
        if not hour_ids:
            self._add_debug('aucun horaire déclaré, le chronomètre ne sera '
                'pas disponible',
                'timer.hour.*'
            )
            return
        for hour_id in hour_ids:
            self.__build_timer_hour(hour_id, timer)
        if not timer.hours:
            self._add_warning(
                'aucun horaire défini, le chronomètre ne sera pas disponible',
                section
            )
            return
        self.__build_timer_colors(timer)
        self.__build_timer_delays(timer)
        self.__timer = timer
        self.timer.set_hours_timestamps()

    def __build_timer_hour(self, hour_id: str, timer: Timer):
        section = f'timer.hour.{hour_id}'
        timer_section = self[section]
        section_keys: List[str] = ['date', 'text_before', 'text_after', ]
        key = 'date'
        if key not in timer_section:
            self._add_warning('option absente, horaire ignoré', section, key)
            return
        previous_hour: Optional[TimerHour] = None
        if timer.hours:
            previous_hour = timer.hours[-1]
        datetime_str = re.sub(r'\s+', ' ', str(timer_section.get(key)).strip().upper())
        timestamp: Optional[int] = None
        matches = re.match('^#?([0-9]{4})-([0-9]{1,2})-([0-9]{1,2}) ([0-9]{1,2}):([0-9]{1,2})$', datetime_str)
        if matches:
            timestamp = int(time.mktime(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M').timetuple()))
        else:
            matches = re.match('^([0-9]{1,2}):([0-9]{1,2})$', datetime_str)
            if matches:
                if previous_hour is None:
                    self._add_warning('le jour du premier horaire doit être spécifié, horaire ignoré', section, key)
                    return
                self._add_debug(f'jour non spécifié, [{datetime_str} {previous_hour}] pris en compte', section, key)
                timestamp = int(time.mktime(datetime.datetime.strptime(
                    previous_hour.date_str + ' ' + datetime_str, '%Y-%m-%d %H:%M').timetuple()))
        if timestamp is None:
            self._add_warning(f'date [{datetime_str}] non valide ([YYYY-MM-DD hh:mm] ou [hh:mm] attendu), '
                              f'horaire ignoré', section, key)
            return
        hour: TimerHour = TimerHour(hour_id, timestamp)
        if timer.hours:
            previous_hour: TimerHour = timer.hours[-1]
            if timestamp <= previous_hour.timestamp:
                self._add_warning(f"l'horaire [{hour.datetime_str}] arrive avant l'horaire précédent "
                                  f'[{previous_hour.datetime_str}], horaire ignoré', section, key)
                return

        if hour_id.isdigit():
            hour.set_round(int(hour_id))
        key = 'text_before'
        if self.has_option(section, key):
            hour.set_text_before(self.get(section, key))
        key = 'text_after'
        if self.has_option(section, key):
            hour.set_text_after(self.get(section, key))
        if hour.text_before is None or hour.text_after is None:
            self._add_warning(
                'les options [text_before] et [text_after] sont attendues, '
                'horaire ignoré',
                section
            )
            return
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)
        timer.hours.append(hour)

    def __build_timer_colors(self, timer: Timer):
        section = 'timer.colors'
        try:
            color_section = self[section]
        except KeyError:
            return
        section_keys = [str(id) for id in range(1, 4)]
        simplified_hex_pattern = re.compile('^#?([0-9A-F])([0-9A-F])([0-9A-F])$')
        hex_pattern = re.compile('^#?([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})$')
        rgb_pattern = re.compile(r'^(RBG)*\(([0-9]+),([0-9]+)([0-9]+)\)*$')
        for key in color_section:
            if key not in section_keys:
                self._add_warning(
                    'option de couleur invalide (acceptées : '
                    f'[{", ".join(section_keys)}]), '
                    'couleur ignorée',
                    section,
                    key
                )
                continue
            color_id = int(key)
            color_rbg: Optional[Tuple[int, int, int]] = None
            color_value: str = color_section.get(key).replace(' ', '').upper()
            matches = simplified_hex_pattern.match(color_value)
            if matches:
                color_rbg = (
                    int(matches.group(1) * 2, 16),
                    int(matches.group(2) * 2, 16),
                    int(matches.group(3) * 2, 16),
                )
            else:
                matches = hex_pattern.match(color_value)
                if matches:
                    color_rbg = (
                        int(matches.group(1), 16),
                        int(matches.group(2), 16),
                        int(matches.group(3), 16),
                    )
                else:
                    matches = rgb_pattern.match(color_value)
                    if matches:
                        color_rbg = (
                            int(matches.group(1)),
                            int(matches.group(2)),
                            int(matches.group(3)),
                        )
                        if color_rbg[0] > 255 or color_rbg[1] > 255 or color_rbg[2] > 255:
                            color_rbg = None
            if color_rbg is None:
                self._add_warning(
                    f'couleur [{color_value}] non valide (#HHH, #HHHHHH ou '
                    'RGB(RRR, GGG, BBB) attendu), la couleur par défaut sera '
                    'utilisée',
                    section,
                    key
                )
            else:
                self._add_info(
                    f'couleur personnalisée [{color_rbg}] définie',
                    section,
                    key
                )
                timer.colors[color_id] = color_rbg

    def __build_timer_delays(self, timer: Timer):
        section = 'timer.delays'
        try:
            delay_section = self[section]
        except KeyError:
            return
        section_keys = [str(id) for id in range(1, 4)]
        for key in delay_section:
            if key not in section_keys:
                self._add_warning(
                    'option de délai non valide (acceptées: '
                    f'[{", ".join(section_keys)}])',
                    section,
                    key
                )
                continue
            delay_id = int(key)
            delay: Optional[int] = self._getint_safe(section, key, minimum=1)
            if delay is None:
                self._add_warning(
                    'un entier positif est attendu, ignoré',
                    section,
                    key
                )
            else:
                timer.delays[delay_id] = delay

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

    def __eq__(self, other: 'Event'):
        # p1 == p2 calls p1.__eq__(p2)
        return self.name == other.name


def get_events(silent: bool = True, with_tournaments_only: bool = False) -> List[Event]:
    event_files: Iterator[Path] = EVENTS_PATH.glob('*.ini')
    events: List[Event] = []
    for event_file in event_files:
        event_id: str = event_file.stem
        event: Event = Event(event_id, silent=silent)
        if not with_tournaments_only or event.tournaments:
            events.append(event)
    return events


def get_events_by_name(silent: bool = True, with_tournaments_only: bool = False) -> List[Event]:
    return sorted(get_events(silent=silent, with_tournaments_only=with_tournaments_only), key=lambda event: event.name)
