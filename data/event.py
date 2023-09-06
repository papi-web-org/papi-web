import datetime
import re
from functools import total_ordering
from pathlib import Path

import time

from typing import List, Optional, Dict, Tuple, Iterator
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
        section: str = 'event'
        if not self.has_section(section):
            self._add_error(f'rubrique absente', section)
            return
        key = 'name'
        default_name = self.__id
        self.__name = default_name
        if not self.has_option(section, key):
            self._add_info(f'option absente, par défaut [{default_name}]', section, key)
        else:
            self.__name = self.get(section, key)
        key = 'path'
        default_path: Path = Path('papi')
        self.__path: Path = default_path
        if not self.has_option(section, key):
            self._add_debug(f'option absente, par défaut [{default_path}]', section, key)
        else:
            self.__path = Path(self.get(section, key))
        if not self.path.exists():
            self._add_error(f'le répertoire [{self.path}] n\'existe pas', section, key)
            return
        if not self.path.is_dir():
            self._add_error(f'[{self.path}] n\'est pas un répertoire', section, key)
            return
        key = 'css'
        if not self.has_option(section, key):
            self._add_debug(f'option absente', section, key)
        else:
            self.__css = self.get(section, key)
        key = 'update_password'
        if not self.has_option(section, key):
            self._add_info(
                f'option absente, aucun mot de passe ne sera demandé pour les saisies'.format(), section, key)
        else:
            self.__update_password = self.get(section, key)
        section_keys: List[str] = ['name', 'path', 'update_password', 'css', ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning(f'option inconnue', section, key)

    def __rename_section(self, old_name: str, new_name: str):
        self.add_section(new_name)
        for option in self.options(old_name):
            self.set(new_name, option, self.get(old_name, option))
            self.remove_option(old_name, option)
        self.remove_section(old_name)

    def __build_tournaments(self):
        tournament_ids: List[str] = self._get_subsections_with_prefix('tournament')
        if 'handicap' in tournament_ids:
            tournament_ids.remove('handicap')
        if self.has_section('tournament'):
            if tournament_ids:
                sections: str = ', '.join(['[tournament.' + id + ']' for id in tournament_ids])
                self._add_error(f'la rubrique [tournament] ne doit être utilisée que lorsque l\'évènement '
                                f'ne compte qu\'un tournoi, d\'autres rubriques sont présentes ({sections})',
                                'tournament.*')
                return
            default_tournament_id: str = 'default'
            old_tournament_section: str = 'tournament'
            new_tournament_section: str = 'tournament.' + default_tournament_id
            self.__rename_section(old_tournament_section, new_tournament_section)
            self._add_debug(f'un seul tournoi, la rubrique [{old_tournament_section}] a été renommée '
                            f'[{new_tournament_section}]', old_tournament_section)
            old_handicap_section: str = 'tournament.handicap'
            if self.has_section(old_handicap_section):
                new_handicap_section: str = 'tournament.' + default_tournament_id + '.handicap'
                self.__rename_section(old_handicap_section, new_handicap_section)
                self._add_debug(f'un seul tournoi, la rubrique [{old_handicap_section}] a été renommée '
                                f'[{new_tournament_section}]')
            tournament_ids.append(default_tournament_id)
        elif not tournament_ids:
            self._add_error(f'aucun tournoi trouvé', 'tournament.*')
            return
        for tournament_id in tournament_ids:
            self.__build_tournament(tournament_id)
        if not len(self.__tournaments):
            self._add_error(f'aucun tournoi initialisé')

    def __build_tournament(self, tournament_id: str):
        section: str = 'tournament.' + tournament_id
        key = 'path'
        default_path: Path = self.path
        path: Path = default_path
        if not self.has_option(section, key):
            self._add_debug(f'option absente, par défaut [{default_path}]', section, key)
        else:
            path = Path(self.get(section, key))
        if not path.exists():
            self._add_error(f'le répertoire [{path}] n\'existe pas, tournoi ignoré', section, key)
            return
        if not path.is_dir():
            self._add_error(f'[{path}] n\'est pas un répertoire, tournoi ignoré', section, key)
            return
        key = 'filename'
        filename: Optional[str] = None
        if self.has_option(section, key):
            filename = self.get(section, key)
        key = 'ffe_id'
        ffe_id: Optional[int] = None
        if self.has_option(section, key):
            ffe_id = self._getint_safe(section, key, minimum=1)
            if ffe_id is None:
                self._add_warning(f'un entier positif non nul est attendu', section, key)
        if filename is None and ffe_id is None:
            self._add_error(f'ni [filename] ni [ffe_id] ne sont indiqués, tournoi ignoré', section)
            return
        if filename is None:
            filename = str(ffe_id)
        file: Path = Path(path, filename + '.papi')
        if not file.exists():
            self._add_error(f'le fichier [{file}] n\'existe pas, tournoi ignoré', section)
            return
        if not file.is_file():
            self._add_error(f'[{file}] n\'est pas un fichier, tournoi ignoré', section)
            return
        key = 'name'
        default_name: str = tournament_id
        if not self.has_option(section, key):
            self._add_info(f'option absente, par défaut [{default_name}]', section, key)
        name: str = self.get(section, key, fallback=default_name)
        key = 'ffe_password'
        ffe_password: Optional[str] = None
        if ffe_id is not None:
            if not self.has_option(section, key):
                self._add_info(f'option absente, les opérations sur le site web de la FFE ne seront pas '
                               f'disponibles', section, key)
            else:
                ffe_password: str = self.get(section, key)
                if not re.match('^[A-Z]{10}$', ffe_password):
                    self._add_warning(
                        f'un mot de 10 lettres majuscules est attendu, le mot de passe est ignoré (les opérations '
                        f'sur le site web de la FFE ne seront pas disponibles)', section, key)
                    ffe_password = None
        elif self.has_option(section, key):
            self._add_info(f'option ignorée quand l\'option [ffe_id] n\'est pas indiquée', section, key)
        section_keys: List[str] = ['path', 'filename', 'name', 'ffe_id', 'ffe_password', ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning(f'option inconnue', section, key)
        handicap_initial_time: Optional[int]
        handicap_increment: Optional[int]
        handicap_penalty_step: Optional[int]
        handicap_penalty_value: Optional[int]
        handicap_min_time: Optional[int]
        handicap_section = 'tournament.' + tournament_id + 'handicap'
        handicap_initial_time, handicap_increment, handicap_penalty_step, handicap_penalty_value, handicap_min_time = \
            self.__build_tournament_handicap(handicap_section)
        if handicap_initial_time is not None and ffe_id is not None:
            self._add_warning(f'les tournois à handicap ne devraient pas être homologués', handicap_section)
        self.__tournaments[tournament_id] = Tournament(
            tournament_id, name, file, ffe_id, ffe_password, handicap_initial_time, handicap_increment,
            handicap_penalty_step, handicap_penalty_value, handicap_min_time)

    def __build_tournament_handicap(
            self, section: str
    ) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
        if not self.has_section(section):
            return None, None, None, None, None
        section_keys: List[str] = ['initial_time', 'increment', 'penalty_step', 'penalty_value', 'min_time', ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning('option inconnue', section, key)
        key = 'initial_time'
        initial_time: Optional[int] = None
        if not self.has_option(section, key):
            self._add_warning(f'option absente, configuration de handicap ignorée', section, key)
        else:
            initial_time = self._getint_safe(section, key, minimum=1)
            if initial_time is None:
                self._add_warning(
                    f'un entier positif non nul est attendu, configuration de handicap ignorée', section, key)
        key = 'increment'
        increment: Optional[int] = None
        if not self.has_option(section, key):
            self._add_info(f'option absente, configuration de handicap ignorée', section, key)
        else:
            increment = self._getint_safe(section, key, minimum=0)
            if increment is None:
                self._add_warning(
                    f'un entier positif est attendu, configuration de handicap ignorée', section, key)
        key = 'penalty_step'
        penalty_step: Optional[int] = None
        if not self.has_option(section, key):
            self._add_info(f'option absente, configuration de handicap ignorée', section, key)
        else:
            penalty_step = self._getint_safe(section, key, minimum=1)
            if penalty_step is None:
                self._add_warning(
                    f'un entier positif non nul est attendu, configuration de handicap ignorée', section, key)
        key = 'penalty_value'
        penalty_value: Optional[int] = None
        if not self.has_option(section, key):
            self._add_info(f'option absente, configuration de handicap ignorée', section, key)
        else:
            penalty_value = self._getint_safe(section, key, minimum=1)
            if penalty_value is None:
                self._add_warning(
                    f'un entier positif non nul est attendu, configuration de handicap ignorée', section, key)
        key = 'min_time'
        min_time: Optional[int] = None
        if not self.has_option(section, key):
            self._add_info(f'option absente, configuration de handicap ignorée', section, key)
        else:
            min_time = self._getint_safe(section, key, minimum=1)
            if min_time is None:
                self._add_warning(
                    f'un entier positif non nul est attendu, configuration de handicap ignorée', section, key)
        if None in [initial_time, increment, penalty_step, penalty_value, min_time]:
            return None, None, None, None, None
        return initial_time, increment, penalty_step, penalty_value, min_time

    def __build_templates(self):
        template_ids: List[str] = self._get_subsections_with_prefix('template')
        if not template_ids:
            self._add_debug(f'aucun modèle déclaré', 'template.*')
            return
        for template_id in template_ids:
            self.__build_template(template_id)
        if not len(self.__templates):
            self._add_debug(f'aucun modèle initialisé')

    def __build_template(self, template_id: str):
        template: Template = Template(template_id)
        section = 'template.' + template_id
        for key, value in self.items(section):
            if key not in self.screen_keys:
                self._add_warning(f'option de modèle inconnue, ignorée', section, key)
            else:
                template.add_data(None, key, value)
        for sub_section in self._get_subsections_with_prefix(section, first_level_only=False):
            if sub_section.split('.')[0] not in SCREEN_TYPE_NAMES or len(sub_section.split('.')) > 2:
                self._add_warning(f'rubrique de modèle non valide, ignorée', section + '.' + sub_section)
                continue
            for key, value in self.items(section + '.' + sub_section):
                if key not in self.screen_set_keys:
                    self._add_warning(f'option de modèle inconnue, ignorée', section + '.' + sub_section, key)
                else:
                    template.add_data(sub_section, key, value)
        self.__templates[template_id] = template

    def __build_families(self):
        family_ids: List[str] = self._get_subsections_with_prefix('family')
        if not family_ids:
            self._add_debug(f'aucune famille déclarée', 'family.*')
            return
        for family_id in family_ids:
            self.__build_family(family_id)

    def __build_family(self, family_id: str):
        section = 'family.' + family_id
        section_keys = ['template', 'range', ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning(f'option de famille inconnue, ignorée', section, key)
        key = 'template'
        if not self.has_option(section, key):
            self._add_warning(f'option absente, famille ignorée', section, key)
            return
        template_id: str = self.get(section, key)
        if template_id not in self.templates:
            self._add_warning(f'le modèle [{template_id}] n\'existe pas, famille ignorée', section, key)
            return
        template: Template = self.templates[template_id]
        key = 'range'
        if not self.has_option(section, key):
            self._add_warning(f'option absente, famille ignorée', section, key)
            return
        range_str = self.get(section, key).replace(' ', '')
        family_indices: Optional[List[str]] = None
        matches = re.match('^(\\d+)-(\\d+)$', range_str)
        if matches:
            first_number = int(matches.group(1))
            last_number = int(matches.group(2))
            if first_number <= last_number:
                family_indices = [str(number) for number in range(first_number, last_number + 1)]
        else:
            matches = re.match('^([A-Z])-([A-Z])$', range_str)
            if matches:
                first_letter = matches.group(1)
                last_letter = matches.group(2)
                if ord(first_letter) <= ord(last_letter):
                    family_indices = [chr(i) for i in range(ord(first_letter), ord(last_letter) + 1)]
            else:
                matches = re.match('^([a-z])-([a-z])$', range_str)
                if matches:
                    first_letter = matches.group(1)
                    last_letter = matches.group(2)
                    if ord(first_letter) <= ord(last_letter):
                        family_indices = [chr(i) for i in range(ord(first_letter), ord(last_letter) + 1)]
        if family_indices is None:
            self._add_warning(f'valeurs [{range_str}] non valides, famille ignorée', section, key)
            return
        for screen_index in family_indices:
            screen_id = section.split('.')[1] + '-' + screen_index
            screen_section = 'screen.' + screen_id
            if not self.has_section(screen_section):
                self._add_debug(f'rubrique ajoutée', screen_section)
                self.add_section(screen_section)
            self.set(screen_section, '__family__', family_id)
            for sub_section, properties in template.data.items():
                if sub_section is None:
                    new_section = screen_section
                else:
                    new_section = screen_section + '.' + sub_section
                if not self.has_section(new_section):
                    self._add_debug(f'rubrique ajoutée', new_section)
                    self.add_section(new_section)
                for key, value in properties.items():
                    if not self.has_option(new_section, key):
                        new_value = value.replace('?', screen_index)
                        self.set(new_section, key, new_value)
                        self._add_debug(f'option ajoutée avec la valeur [{new_value}]', new_section, key)
            self._add_debug(f'écran [{screen_id}] ajouté', section)

    def __build_screens(self):
        screen_ids: List[str] = self._get_subsections_with_prefix('screen')
        if not screen_ids:
            self._add_info(f'aucun écran défini, ajout des écrans par défaut', 'screen.*')
            for tournament_id in self.tournaments:
                if not self.tournaments[tournament_id].file:
                    continue
                name_prefix: str = ''
                if len(self.tournaments) > 1:
                    name_prefix = self.tournaments[tournament_id].name + ' - '
                data: Dict[str, Dict[str, str]] = {
                    tournament_id + '-' + SCREEN_TYPE_BOARDS + '-update': {
                        'type': SCREEN_TYPE_BOARDS,
                        'update': 'on',
                        'name': name_prefix + 'Saisie des résultats',
                        'menu_text': name_prefix + 'Saisie des résultats',
                    },
                    tournament_id + '-' + SCREEN_TYPE_BOARDS + '-view': {
                        'type': SCREEN_TYPE_BOARDS,
                        'update': 'off',
                        'name': name_prefix + 'Appariements par échiquier',
                        'menu_text': name_prefix + 'Appariements',
                    },
                    tournament_id + '-' + SCREEN_TYPE_PLAYERS: {
                        'type': SCREEN_TYPE_PLAYERS,
                        'name': name_prefix + 'Appariements par ordre alphabétique',
                        'columns': '2',
                        'menu_text': name_prefix + 'Ordre alphabétique',
                    },
                    tournament_id + '-' + SCREEN_TYPE_RESULTS: {
                        'type': SCREEN_TYPE_RESULTS,
                        'name': name_prefix + 'Derniers résultats',
                        'menu_text': name_prefix + 'Derniers résultats',
                    },
                }
                menu: str = ','.join([screen_id for screen_id in data])
                for screen_id, options in data.items():
                    section: str = 'screen.' + screen_id
                    self.add_section(section)
                    for key, value in options.items():
                        self.set(section, key, value)
                    self.set(section, 'menu', menu)
                    screen_ids.append(screen_id)
                    self._add_debug(f'l\'écran [{screen_id}] a été ajouté', 'screen.*')
                data: Dict[str, Dict[str, str]] = {
                    tournament_id + '-' + SCREEN_TYPE_BOARDS + '-input.' + SCREEN_TYPE_BOARDS: {
                        'tournament': tournament_id,
                    },
                    tournament_id + '-' + SCREEN_TYPE_BOARDS + '-print.' + SCREEN_TYPE_BOARDS: {
                        'tournament': tournament_id,
                    },
                    tournament_id + '-' + SCREEN_TYPE_PLAYERS + '.players': {
                        'tournament': tournament_id,
                    },
                }
                for screen_id, options in data.items():
                    section: str = 'screen.' + screen_id
                    self.add_section(section)
                    for key, value in options.items():
                        self.set(section, key, value)
        for screen_id in screen_ids:
            self.__build_screen(screen_id)
        if not len(self.__screens):
            self._add_warning(f'aucun écran n\'a été initialisé')
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
                    self._add_warning(f'l\'écran n\'appartient pas à une famille, aucun menu ne sera affiché',
                                      'screen.' + screen.id, 'menu')
                    screen.set_menu_screens([])
                    continue
                screen.set_menu_screens(self.__screens_by_family_id[screen.family_id])
                continue
            menu_screens: List[AScreen] = []
            for screen_id in screen.menu.replace(' ', '').split(','):
                if screen_id:
                    if screen_id in self.screens:
                        menu_screens.append(self.screens[screen_id])
                    else:
                        self._add_warning(f'l\'écran [{screen_id}] n\'existe pas, ignoré',
                                          'screen.' + screen.id, 'menu')
            screen.set_menu(', '.join([screen.id for screen in menu_screens]))
            screen.set_menu_screens(menu_screens)

    screen_keys: List[str] = [
        'type', 'name', 'columns', 'menu_text', 'show_timer', 'menu', 'update', 'limit',
    ]

    def __build_screen(self, screen_id: str):
        section = 'screen.' + screen_id
        key = 'template'
        if self.has_option(section, key):
            template_id = self.get(section, key)
            if template_id not in self.templates:
                self._add_warning(f'le modèle [{template_id}] n\'existe pas, écran ignoré', section, key)
                return
            template: Template = self.templates[template_id]
            for sub_section, properties in template.data.items():
                if sub_section is None:
                    new_section = section
                else:
                    new_section = section + '.' + sub_section
                if not self.has_section(new_section):
                    self.add_section(new_section)
                for key, value in properties.items():
                    if not self.has_option(new_section, key):
                        self.set(new_section, key, value)
        key = 'type'
        if not self.has_option(section, key):
            self._add_warning(f'option absente, écran ignoré', section, key)
            return
        screen_type: str = self.get(section, key)
        if screen_type not in SCREEN_TYPE_NAMES:
            self._add_warning(f'type d\'écran invalide [{screen_type}], écran ignoré', section, key)
            return
        screen_set_sections: List[str] = []
        screen_set_single_section = section + '.' + screen_type
        if screen_type == SCREEN_TYPE_BOARDS:
            if self.has_section(screen_set_single_section):
                screen_set_sections = [screen_set_single_section, ]
                for screen_set_sub_section in self._get_subsections_with_prefix(screen_set_single_section):
                    self._add_warning(f'rubrique non prise en compte, supprimez la rubrique '
                                      f'[{screen_set_single_section}] pour cela',
                                      screen_set_single_section + '.' + screen_set_sub_section)
            else:
                screen_set_sections = [
                    screen_set_single_section + '.' + sub_section
                    for sub_section in self._get_subsections_with_prefix(screen_set_single_section)
                ]
            if not screen_set_sections:
                if len(self.tournaments) == 1:
                    self.add_section(screen_set_single_section)
                    screen_set_sections.append(screen_set_single_section)
                    self._add_info(f'un seul tournoi, la rubrique [{screen_set_single_section}] a été ajoutée', section)
                else:
                    self._add_warning(f'rubrique absente, écran ignoré', screen_set_single_section)
                    return
        elif screen_type == SCREEN_TYPE_PLAYERS:
            if self.has_section(screen_set_single_section):
                screen_set_sections = [screen_set_single_section, ]
                for screen_set_sub_section in self._get_subsections_with_prefix(screen_set_single_section):
                    self._add_warning(f'rubrique non prise en compte, supprimez la rubrique '
                                      f'[{screen_set_single_section}] pour cela',
                                      screen_set_single_section + '.' + screen_set_sub_section)
            else:
                screen_set_sections = [
                    screen_set_single_section + '.' + sub_section
                    for sub_section in self._get_subsections_with_prefix(screen_set_single_section)
                ]
            if not screen_set_sections:
                if len(self.tournaments) == 1:
                    self.add_section(screen_set_single_section)
                    screen_set_sections.append(screen_set_single_section)
                    self._add_info(f'un seul tournoi, la rubrique [{screen_set_single_section}] a été ajoutée', section)
                else:
                    self._add_warning(f'rubrique absente, écran ignoré', screen_set_single_section)
                    return
        elif screen_type == SCREEN_TYPE_RESULTS:
            pass
        else:
            self._add_warning(f'type d\'écran [{screen_type}] inconnu, écran ignoré', section)
            return
        key = 'columns'
        default_columns: int = 1
        columns: int = default_columns
        if not self.has_option(section, key):
            pass  # self._add_info(f'key not found, defaults to [{default_columns}]', section, key)
        else:
            columns = self._getint_safe(section, key)
            if columns is None:
                self._add_warning(
                    f'un entier non nul positif est attendu, par défaut [{default_columns}]', section, key)
                columns = default_columns
        screen_sets: Optional[List[ScreenSet]] = None
        if screen_type in [SCREEN_TYPE_BOARDS, SCREEN_TYPE_PLAYERS, ]:
            screen_sets = self.__build_screen_sets(screen_set_sections, columns)
            if not screen_sets:
                if screen_type == SCREEN_TYPE_BOARDS:
                    self._add_warning(f'pas d\'ensemble d\'échiquiers déclaré, écran ignoré', section)
                else:
                    self._add_warning(f'pas d\'ensemble de joueur·euses déclaré, écran ignoré', section)
                return
        key = 'name'
        screen_name: Optional[str] = None
        if self.has_option(section, key):
            screen_name = self.get(section, key)
        elif screen_type == SCREEN_TYPE_RESULTS:
            screen_name = 'Derniers résultats'
            self._add_debug(f'option absente, par défaut [{screen_name}]', section, key)
        else:
            self._add_debug(f'option absente, le nom du premier ensemble sera utilisé', section, key)
        key = 'menu_text'
        menu_text: Optional[str] = None
        if self.has_option(section, key):
            menu_text = self.get(section, key)
        key = 'menu'
        default_menu: Optional[str] = None
        menu: Optional[str] = default_menu
        if not self.has_option(section, key):
            self._add_info(f'option absente, aucun menu ne sera affiché (indiquer [none] pour supprimer ce message)',
                           section, key)
        else:
            menu = self.get(section, key)
            if menu == 'none':
                menu = None
            elif menu == 'family':
                if screen_type == SCREEN_TYPE_RESULTS:
                    self._add_warning(f'l\'option [family] n\'est pas autorisée pour les écrans de type '
                                      f'[{screen_type}], no menu will be printed', section, key)
                    menu = None
            elif menu == 'view':
                pass
            elif menu == 'update':
                pass
            elif ',' in menu:
                pass
            else:
                self._add_warning(f'[none], [family], [view], [update] ou une liste d\'écrans séparés par des '
                                  'virgules sont attendus, no menu will be printed', section, key)
                menu = None
        key = 'show_timer'
        default_show_timer: bool = True
        show_timer: bool = default_show_timer
        if self.has_option(section, key):
            show_timer = self.getboolean(section, key)
            if show_timer is None:
                self._add_warning(f'un booléen est attendu, par défaut [{default_show_timer}]', section, key)
        key = 'update'
        default_update: bool = False
        update: bool = default_update
        if screen_type == SCREEN_TYPE_BOARDS:
            if self.has_option(section, key):
                update = self._getboolean_safe(section, key)
                if update is None:
                    self._add_warning(f'un booléen est attendu, écran ignoré', section, key)
                    return
        else:
            if self.has_option(section, key):
                self._add_warning(f'l\'option n\'est pas autorisée pour les écrans de type [{screen_type}], ignorée',
                                  section, key)
        key = 'limit'
        default_limit: int = 0
        limit: int = default_limit
        if screen_type == SCREEN_TYPE_RESULTS:
            if self.has_option(section, key):
                limit = self._getint_safe(section, key)
                if limit is None:
                    self._add_warning(f'un entier positif ou nul ets attendu, par défaut [{default_limit}]',
                                      section, key)
                    limit = default_limit
                if limit > 0 and limit % columns > 0:
                    limit = columns * (limit // columns + 1)
                    self._add_info(f'positionné à [{limit}] pour tenir sur {columns} colonnes', section, key)
        else:
            if self.has_option(section, key):
                self._add_warning(f'l\'option n\'est pas autorisée pour les écrans de type [{screen_type}], ignorée',
                                  section, key)
        key = '__family__'
        family_id: Optional[str] = None
        if self.has_option(section, key):
            family_id: str = self.get(section, key)
        if screen_type == SCREEN_TYPE_BOARDS:
            self.__screens[screen_id] = ScreenBoards(
                screen_id, family_id, screen_name, columns, menu_text, menu, show_timer, screen_sets, update)
        elif screen_type == SCREEN_TYPE_PLAYERS:
            self.__screens[screen_id] = ScreenPlayers(
                screen_id, family_id, screen_name, columns, menu_text, menu, show_timer, screen_sets)
        elif screen_type == SCREEN_TYPE_RESULTS:
            self.__screens[screen_id] = ScreenResults(
                self.id, screen_id, family_id, screen_name, columns, menu_text, menu, show_timer, limit)
        for key, value in self.items(section):
            if key not in self.screen_keys + ['template', '__family__', ]:
                self._add_warning(f'option absente', section, key)
        if family_id is not None:
            if family_id not in self.__screens_by_family_id:
                self.__screens_by_family_id[family_id] = []
            self.__screens_by_family_id[family_id].append(self.__screens[screen_id])

    screen_set_keys = ['tournament', 'name', 'first', 'last', 'part', 'parts', ]

    def __build_screen_sets(self, sections: List[str], columns: int) -> List[ScreenSet]:
        screen_sets: List[ScreenSet] = []
        for section in sections:
            key = 'tournament'
            if not self.has_option(section, key):
                if len(self.tournaments) == 1:
                    self.set(section, key, list(self.tournaments.keys())[0])
                else:
                    self._add_warning(f'option absente, écran ignoré', section, key)
                    continue
            tournament_id: str = self.get(section, key)
            if tournament_id not in self.tournaments:
                self._add_warning(f'le tournoi [{tournament_id}] n\'existe pas, écran ignoré', section, key)
                continue
            if not self.tournaments[tournament_id].file:
                self._add_warning(f'le fichier du tournoi [{tournament_id}] n\'existe pas, l\'ensemble est ignoré',
                                  section, key)
                continue
            if (self.has_option(section, 'first') or self.has_option(section, 'last')) \
                    and (self.has_option(section, 'part') or self.has_option(section, 'parts')):
                self._add_warning(f'les options [part]/[parts] et [first]/[last] ne sont pas compatibles, écran ignoré',
                                  section)
                continue
            key = 'first'
            first: Optional[int] = None
            if self.has_option(section, key):
                first = self._getint_safe(section, key, minimum=1)
                if first is None:
                    self._add_warning(f'un entier positif non nul est attendu, ignoré', section, key)
            key = 'last'
            last: Optional[int] = None
            if self.has_option(section, key):
                last = self._getint_safe(section, key)
                if last is None:
                    self._add_warning(f'un entier positif non nul est attendu, ignoré', section, key)
            if first is not None and last is not None and first > last:
                self._add_warning(f'intervalle [{first}-{last}] non valide', section)
                continue
            key = 'part'
            part: Optional[int] = None
            if self.has_option(section, key):
                part = self._getint_safe(section, key)
                if part is None:
                    self._add_warning(f'un entier positif non nul est attendu, ignoré', section, key)
            key = 'parts'
            parts: Optional[int] = None
            if self.has_option(section, key):
                parts = self._getint_safe(section, key)
                if parts is None:
                    self._add_warning(f'un entier positif non nul est attendu, ignoré', section, key)
            if (part is None and parts is not None) or (part is not None and parts is None):
                self._add_warning(f'les options [part]/[parts] et [first]/[last] ne sont pas compatibles, écran ignoré',
                                  section)
            if part is not None and part > parts:
                self._add_warning(f'la partie [{part}] sur [{parts}] n\'est pas valide, écran ignoré', section)
            key = 'name'
            name: Optional[str] = None
            if self.has_option(section, key):
                name = self.get(section, key)
            for key, value in self.items(section):
                if key not in self.screen_set_keys:
                    self._add_warning(f'option inconnue', section, key)
            screen_sets.append(ScreenSet(
                self.tournaments[tournament_id], columns, first=first, last=last, part=part, parts=parts, name=name))
        return screen_sets

    def __build_rotators(self):
        rotator_ids: List[str] = self._get_subsections_with_prefix('rotator')
        if not rotator_ids:
            self._add_debug(f'aucun écran rotatif déclaré', 'rotator.*')
            return
        for rotator_id in rotator_ids:
            self.__build_rotator(rotator_id)
        if not len(self.__rotators):
            self._add_debug(f'aucun écran rotatif défini')

    def __build_rotator(self, rotator_id: str):
        section = 'rotator.' + rotator_id
        section_keys: List[str] = ['screens', 'families', 'delay', ]
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning(f'option inconnue', section, key)
        key = 'delay'
        default_delay: int = ROTATOR_DEFAULT_DELAY
        delay: int = default_delay
        if not self.has_option(section, key):
            self._add_debug(f'option absente, par défaut [{default_delay}]', section, key)
        else:
            delay = self._getint_safe(section, key)
            if delay is None:
                self._add_warning(f'un entier positif non nul est attendu, par défaut [{default_delay}]', section, key)
        if not self.has_option(section, 'screens') and not self.has_option(section, 'families'):
            self._add_info(f'au moins une option parmi [screens] et [families] doit être définie, écran rotatif ignoré',
                           section)
            return
        screens: List[AScreen] = []
        key = 'families'
        if self.has_option(section, key):
            for family_id in str(self.get(section, key)).replace(' ', '').split(','):
                if family_id:
                    if family_id not in self.__screens_by_family_id:
                        self._add_warning(f'la famille [{family_id}] n\'existe pas, ignorée', section, key)
                    else:
                        screens = screens + self.__screens_by_family_id[family_id]
        key = 'screens'
        if self.has_option(section, key):
            for screen_id in str(self.get(section, key)).replace(' ', '').split(','):
                if screen_id:
                    if screen_id not in self.screens:
                        self._add_warning(f'l\'écran [{screen_id}] n\'existe pas, ignoré', section, key)
                    elif self.screens[screen_id] not in screens:
                        screens.append(self.screens[screen_id])
        if not self.has_option(section, 'screens') and not self.has_option(section, 'families'):
            self._add_warning(f'au moins des deux options [screens] ou [families] doit être utilisée, '
                              f'écran rotatif ignoré', section)
            return
        if not screens:
            self._add_warning(f'aucun écran, écran rotatif ignoré', section, key)
            return
        self.__rotators[rotator_id] = Rotator(rotator_id, delay, screens)

    def __build_timer(self):
        timer: Timer = Timer()
        section = 'timer.hour'
        hour_ids: List[str] = self._get_subsections_with_prefix(section)
        if not hour_ids:
            self._add_debug(f'aucun horaire déclaré, le chronomètre ne sera pas disponible', 'timer.hour.*')
            return
        for hour_id in hour_ids:
            self.__build_timer_hour(hour_id, timer)
        if not timer.hours:
            self._add_warning(f'aucun horaire défini, le chronomètre ne sera pas disponible', section)
            return
        self.__build_timer_colors(timer)
        self.__build_timer_delays(timer)
        self.__timer = timer
        self.timer.set_hours_timestamps()

    def __build_timer_hour(self, hour_id: str, timer: Timer):
        section = 'timer.hour.' + hour_id
        section_keys: List[str] = ['date', 'text_before', 'text_after', ]
        key = 'date'
        if not self.has_option(section, key):
            self._add_warning(f'option absente, horaire ignoré', section, key)
            return
        previous_hour: Optional[TimerHour] = None
        if timer.hours:
            previous_hour = timer.hours[-1]
        datetime_str = re.sub('\\s+', ' ', str(self.get(section, key)).strip().upper())
        timestamp: Optional[int] = None
        matches = re.match('^#?([0-9]{4})-([0-9]{1,2})-([0-9]{1,2}) ([0-9]{1,2}):([0-9]{1,2})$', datetime_str)
        if matches:
            timestamp = int(time.mktime(datetime.datetime.strptime(datetime_str, '%Y-%m-%d %H:%M').timetuple()))
        else:
            matches = re.match('^([0-9]{1,2}):([0-9]{1,2})$', datetime_str)
            if matches:
                if previous_hour is None:
                    self._add_warning(f'le jour du premier horaire doit être spécifié, horaire ignoré', section, key)
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
                self._add_warning(f'l\'horaire [{hour.datetime_str}] arrive avant l\'horaire précédent '
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
            self._add_warning(f'les options [text_before] et [text_after] sont attendues, horaire ignoré', section)
            return
        for key, value in self.items(section):
            if key not in section_keys:
                self._add_warning(f'option inconnue', section, key)
        timer.hours.append(hour)

    def __build_timer_colors(self, timer: Timer):
        section = 'timer.colors'
        if not self.has_section(section):
            return
        section_keys = [str(id) for id in range(1, 4)]
        simplified_hex_pattern = re.compile('^#?([0-9A-F])([0-9A-F])([0-9A-F])$')
        hex_pattern = re.compile('^#?([0-9A-F]{2})([0-9A-F]{2})([0-9A-F]{2})$')
        rgb_pattern = re.compile(r'^(RBG)*\(([0-9]+),([0-9]+)([0-9]+)\)*$')
        for key in self.options(section):
            if key not in section_keys:
                self._add_warning(f'option de couleur invalide (acceptées : [{", ".join(section_keys)}]), '
                                  f'couleur ignorée', section, key)
                continue
            color_id = int(key)
            color_rbg: Optional[Tuple[int, int, int]] = None
            color_value: str = self.get(section, key).replace(' ', '').upper()
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
                self._add_warning(f'couleur [{color_value}] non valide (#HHH, #HHHHHH ou RGB(RRR, GGG, BBB) attendu), '
                                  f'la couleur par défaut sera utilisée', section, key)
            else:
                self._add_info(f'couleur personnalisée [{color_rbg}] définie', section, key)
                timer.colors[color_id] = color_rbg

    def __build_timer_delays(self, timer: Timer):
        section = 'timer.delays'
        if not self.has_section(section):
            return
        section_keys = [str(id) for id in range(1, 4)]
        for key in self.options(section):
            if key not in section_keys:
                self._add_warning(f'option de délai non valide (acceptées: [{", ".join(section_keys)}])', section, key)
                continue
            delay_id = int(key)
            delay: Optional[int] = self._getint_safe(section, key, minimum=1)
            if delay is None:
                self._add_warning(f'un entier positif est attendu, ignoré', section, key)
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


def get_events(silent: bool = True) -> List[Event]:
    event_files: Iterator[Path] = EVENTS_PATH.glob('*.ini')
    events: List[Event] = []
    for event_file in event_files:
        event_id: str = event_file.stem
        event: Event = Event(event_id, silent=silent)
        events.append(event)
    return events


def get_events_by_name() -> List[Event]:
    return sorted(get_events(), key=lambda event: event.name)
