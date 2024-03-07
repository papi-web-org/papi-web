import json
import warnings
from contextlib import suppress
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path

from common.config_reader import ConfigReader, TMP_DIR, EVENTS_PATH
from common.logger import get_logger
from data.result import Result
from data.screen_set import ScreenSet, ScreenSetBuilder
from data.template import Template
from data.tournament import Tournament
from data.util import ScreenType

logger: Logger = get_logger()


@dataclass
class AScreen:
    screen_id: str
    family_id: str | None
    _name: str
    _type: ScreenType | None = field(init=False)
    columns: int
    _menu_text: str | None
    menu: str
    show_timer: bool
    menu_screens: list['AScreen'] | None = field(default=None, init=False)

    def __post_init__(self):
        self._type = None

    @property
    def id(self) -> str:
        return self.screen_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> ScreenType | None:
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

    @property
    def menu_label(self) -> str | None:
        return self._menu_text

    def set_menu(self, menu: str):
        warnings.warn("Use direct assignment to menu instead")
        self.menu = menu

    def set_menu_screens(self, menu_screens: list['AScreen']):
        warnings.warn("Use direct assignment to menu_screens instead")
        self.menu_screens = menu_screens

    @property
    def update(self) -> bool:
        return False

    @property
    def sets(self) -> list[ScreenSet]:
        return []

    @classmethod
    def __get_screen_file_dependencies_file(cls, event_id: str, screen_id: str) -> Path:
        return TMP_DIR / 'events' / event_id / 'screen_file_dependencies' / f'{screen_id}.json'

    @classmethod
    def get_screen_file_dependencies(cls, event_id: str, screen_id: str) -> list[Path]:
        tournament_files_file = cls.__get_screen_file_dependencies_file(event_id, screen_id)
        try:
            with open(tournament_files_file, 'r') as f:
                return [Path(file) for file in json.load(f)]
        except FileNotFoundError:
            return []

    @classmethod
    def set_screen_file_dependencies(cls, event_id: str, screen_id: str, files: list[Path]):
        tournament_files_file = cls.__get_screen_file_dependencies_file(event_id, screen_id)
        try:
            tournament_files_file.parents[0].mkdir(parents=True, exist_ok=True)
            with open(tournament_files_file, 'w') as f:
                return f.write(json.dumps([str(file) for file in files]))
        except FileNotFoundError:
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
    update: bool = False
    record_illegal_moves: bool = False

    def __post_init__(self):
        self._type = ScreenType.Boards

    @property
    def name(self) -> str:
        if self._name is None:
            return self.sets[0].name_for_boards
        return self._name

    @property
    def menu_label(self) -> str | None:
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


@dataclass
class ScreenPlayers(AScreenWithSets):
    _show_unpaired: bool

    def __post_init__(self):
        self._type = ScreenType.Players

    @property
    def name(self) -> str:
        if self._name is None:
            return self._sets[0].name_for_players
        return self._name

    @property
    def menu_label(self) -> str | None:
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

    @property
    def show_unpaired(self) -> bool:
        return self._show_unpaired


class ScreenResults(AScreen):
    def __init__(
            self, event_id: str, screen_id: str, family_id: str | None, name: str, columns: int,
            menu_text: str | None, menu: str, show_timer: bool, limit: int):
        super().__init__(
            screen_id, family_id, name, columns, menu_text, menu, show_timer)
        self._type = ScreenType.Results
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


class ScreenBuilder:
    def __init__(
            self, config_reader: ConfigReader, event_id: str, tournaments: dict[str, Tournament],
            templates: dict[str, Template], screens_by_family_id: dict[str, list[AScreen]]):
        self._config_reader: ConfigReader = config_reader
        self._event_id: str = event_id
        self._tournaments: dict[str, Tournament] = tournaments
        self._templates: dict[str, Template] = templates
        self._screens_by_family_id: dict[str, list[AScreen]] = screens_by_family_id
        self.screens: dict[str, AScreen] = {}
        screen_ids: list[str] = self._read_screen_ids()
        if not screen_ids:
            self._add_default_screens(screen_ids)
        for screen_id in screen_ids:
            if screen := self._build_screen(screen_id):
                self.screens[screen.screen_id] = screen
        if not self.screens:
            self._config_reader.add_warning("aucun écran n'a été initialisé")
        self._update_screens()

    def _read_screen_ids(self) -> list[str]:
        return self._config_reader.get_subsection_keys_with_prefix('screen')

    def _build_screen(self, screen_id: str) -> AScreen | None:
        screen_section_key = f'screen.{screen_id}'
        screen_section = self._config_reader[screen_section_key]
        key = 'template'
        with suppress(KeyError):
            template_id = screen_section[key]
            if template_id not in self._templates:
                self._config_reader.add_warning(
                    f"le modèle [{template_id}] n'existe pas, écran ignoré",
                    screen_section_key,
                    key
                )
                return None
            template: Template = self._templates[template_id]
            for sub_section_key, properties in template.data.items():
                if sub_section_key is None:
                    new_section_key = screen_section_key
                else:
                    new_section_key = f'{screen_section_key}.{sub_section_key}'
                if not new_section_key not in self._config_reader:
                    self._config_reader[new_section_key] = {}
                    self._config_reader.add_debug(f"ajout de la rubrique [{new_section_key}]", screen_section_key)
                for key, value in properties.items():
                    self._config_reader[new_section_key].setdefault(key, value)
                self._config_reader.add_debug(f"ajout de l'option [{key} = {value}]", new_section_key)
        key = 'type'
        try:
            maybe_screen_type = screen_section[key]
        except KeyError:
            self._config_reader.add_warning(f"type d'écran non précisé, écran ignoré", screen_section_key, key)
            return None
        try:
            screen_type = ScreenType.from_str(maybe_screen_type)
        except ValueError:
            self._config_reader.add_warning(f"Type d'écran invalide {maybe_screen_type}", screen_section_key, key)
            return None
        match screen_type:
            case ScreenType.Boards | ScreenType.Players | ScreenType.Results:
                pass
            case _:
                self._config_reader.add_warning(
                    f"type d'écran [{screen_type}] inconnu, écran ignoré", screen_section_key)
                return None
        key = 'columns'
        default_columns: int = 1
        try:
            columns = int(screen_section[key])
            assert columns >= 1
        except KeyError:
            columns = default_columns
        except ValueError:
            self._config_reader.add_warning(
                f'un entier est attendu, par défault [{default_columns}]', screen_section_key, key)
            columns = default_columns
        except AssertionError:
            self._config_reader.add_warning(
                'un entier strictement positif est attendu, par défaut [{default_columns}]', screen_section_key, key)
            columns = default_columns
        match screen_type:
            case ScreenType.Boards | ScreenType.Players | ScreenType.Results:
                pass
            case _:
                self._config_reader.add_warning(
                    f"type d'écran [{screen_type}] inconnu, écran ignoré", screen_section_key)
                return
        key = 'name'
        screen_name: str | None = None
        try:
            screen_name = screen_section[key]
        except KeyError:
            if screen_type == ScreenType.Results:
                screen_name = 'Derniers résultats'
                self._config_reader.add_debug(f'option absente, par défault [{screen_name}]', screen_section_key, key)
            else:
                self._config_reader.add_debug(
                    'option absente, le nom du premier ensemble sera utilisé', screen_section_key, key)
        key = 'menu_text'
        menu_text = screen_section.get(key)
        key = 'menu'
        menu = screen_section.get(key)
        if menu is None:
            pass
        elif menu == 'none':
            self._config_reader.add_info(
                'option absente, aucun menu ne sera affiché (indiquer [none] pour supprimer ce message)',
                screen_section_key, key)
            menu = None
        elif menu == 'family':
            if screen_type == ScreenType.Results:
                self._config_reader.add_warning(
                    "l'option [family] n'est pas autorisée pour les écrans de type [{screen_type}], "
                    "aucun menu ne sera affiché", screen_section_key, key)
                menu = None
        elif menu == 'view':
            pass
        elif menu == 'update':
            pass
        elif ',' in menu:
            pass
        else:
            self._config_reader.add_warning(
                '[none], [family], [view], [update] ou une liste d\'écrans séparés par des virgules sont attendus, '
                'aucun menu ne sera affiché', screen_section_key, key)
            menu = None
        key = 'show_timer'
        default_show_timer: bool = True
        show_timer: bool = default_show_timer
        if key in screen_section:
            show_timer = self._config_reader.getboolean(screen_section_key, key)
            if show_timer is None:
                self._config_reader.add_warning(
                    f'un booléen est attendu, par défaut [{default_show_timer}]', screen_section_key, key)
        key = 'update'
        default_update: bool = False
        update: bool | None = default_update
        if screen_type == ScreenType.Boards:
            if key in screen_section:
                update = self._config_reader.getboolean_safe(screen_section_key, key)
                if update is None:
                    self._config_reader.add_warning('un booléen est attendu, écran ignoré', screen_section_key, key)
                    return None
        else:
            if key in screen_section:
                self._config_reader.add_warning(
                    f"l'option n'est pas autorisée pour les écrans de type [{screen_type}], ignorée",
                    screen_section_key, key)
        key = 'record_illegal_moves'
        default_record_illegal_moves: bool = False
        record_illegal_moves: bool | None = default_record_illegal_moves
        if screen_type == ScreenType.Boards:
            if key in screen_section:
                record_illegal_moves = self._config_reader.getboolean_safe(screen_section_key, key)
                if record_illegal_moves is None:
                    self._config_reader.add_warning('un booléen est attendu, écran ignoré', screen_section_key, key)
                    return None
        else:
            if key in screen_section:
                self._config_reader.add_warning(
                    f"l'option n'est pas autorisée pour les écrans de type [{screen_type}], ignorée",
                    screen_section_key, key)
        key = 'show_unpaired'
        default_show_unpaired: bool = False
        show_unpaired: bool | None = default_show_unpaired
        if screen_type == ScreenType.Players:
            if key in screen_section:
                show_unpaired = self._config_reader.getboolean_safe(screen_section_key, key)
                if show_unpaired is None:
                    self._config_reader.add_warning('un booléen est attendu, écran ignoré', screen_section_key, key)
                    return None
        else:
            if key in screen_section:
                self._config_reader.add_warning(
                    f"l'option n'est pas autorisée pour les écrans de type [{screen_type}], ignorée",
                    screen_section_key, key)
        key = 'limit'
        default_limit: int = 0
        limit: int | None = default_limit
        if screen_type == ScreenType.Results:
            if key in screen_section:
                limit = self._config_reader.getint_safe(screen_section_key, key)
                if limit is None:
                    self._config_reader.add_warning(
                        f'un entier positif ou nul ets attendu, par défaut [{default_limit}]',
                        screen_section_key, key)
                    limit = default_limit
                if limit > 0 and limit % columns > 0:
                    limit = columns * (limit // columns + 1)
                    self._config_reader.add_info(
                        f'positionné à [{limit}] pour tenir sur {columns} colonnes', screen_section_key, key)
        else:
            if key in screen_section:
                self._config_reader.add_warning(
                    f"l'option n'est pas autorisée pour les écrans de type [{screen_type}], ignorée",
                    screen_section_key, key)
        screen_sets: list[ScreenSet] | None = None
        if screen_type in [ScreenType.Boards, ScreenType.Players, ]:
            screen_sets = ScreenSetBuilder(
                self._config_reader, self._tournaments, screen_section_key, screen_type, columns, show_unpaired
            ).screen_sets
            if not screen_sets:
                if screen_type == ScreenType.Boards:
                    self._config_reader.add_warning(
                        "pas d'ensemble d'échiquiers déclaré, écran ignoré", screen_section_key)
                    # NOTE(Amaras) should this return?
                else:
                    self._config_reader.add_warning(
                        "pas d'ensemble de joueur·euses déclaré, écran ignoré", screen_section_key)
                return None
        key = '__family__'
        family_id: str | None = None
        if key in screen_section:
            family_id: str = self._config_reader.get(screen_section_key, key)
        screen: AScreen | None = None
        if screen_type == ScreenType.Boards:
            screen = ScreenBoards(
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                screen_sets,
                update,
                record_illegal_moves,
            )
            AScreen.set_screen_file_dependencies(
                self._event_id,
                screen_id,
                [EVENTS_PATH / f'{self._event_id}.ini', ] + [screen_set.tournament.file for screen_set in screen_sets]
            )
        elif screen_type == ScreenType.Players:
            screen = ScreenPlayers(
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                screen_sets,
                show_unpaired
            )
            AScreen.set_screen_file_dependencies(
                self._event_id,
                screen_id,
                [EVENTS_PATH / f'{self._event_id}.ini', ] + [screen_set.tournament.file for screen_set in screen_sets]
            )
        elif screen_type == ScreenType.Results:
            screen = ScreenResults(
                self._event_id,
                screen_id,
                family_id,
                screen_name,
                columns,
                menu_text,
                menu,
                show_timer,
                limit
            )
            AScreen.set_screen_file_dependencies(
                self._event_id,
                screen_id,
                [EVENTS_PATH / f'{self._event_id}.ini', ]
                + [tournament.file for tournament in self._tournaments.values()]
            )
        for key, value in self._config_reader.items(screen_section_key):
            if key not in ConfigReader.screen_keys + ['template', '__family__', ]:
                self._config_reader.add_warning('option absente', screen_section_key, key)
        if family_id is not None:
            if family_id not in self._screens_by_family_id:
                self._screens_by_family_id[family_id] = []
            self._screens_by_family_id[family_id].append(screen)
        return screen

    def _update_screens(self):
        view_menu: list[AScreen] = []
        update_menu: list[AScreen] = []
        for screen in self.screens.values():
            if screen.menu_text:
                if screen.update:
                    update_menu.append(screen)
                else:
                    view_menu.append(screen)
        for screen in self.screens.values():
            if screen.menu is None:
                screen.menu_screens = []
                continue
            if screen.menu == 'view':
                screen.menu_screens = view_menu
                continue
            if screen.menu == 'update':
                screen.menu_screens = update_menu
                continue
            if screen.menu == 'family':
                if screen.family_id is None:
                    self._config_reader.add_warning(
                        "l'écran n'appartient pas à une famille, aucun menu ne sera affiché",
                        f'screen.{screen.id}', 'menu')
                    screen.menu_screens = []
                    continue
                screen.menu_screens = self._screens_by_family_id[screen.family_id]
                continue
            menu_screens: list[AScreen] = []
            for screen_id in screen.menu.replace(' ', '').split(','):
                if screen_id:
                    if screen_id in self.screens:
                        menu_screens.append(self.screens[screen_id])
                    else:
                        self._config_reader.add_warning(
                            f"l'écran [{screen_id}] n'existe pas, ignoré",
                            f'screen.{screen.id}', 'menu')
            screen.menu = ', '.join([screen.id for screen in menu_screens])
            screen.menu_screens = menu_screens

    def _add_default_screens(self, screen_ids: list[str]):
        self._config_reader.add_info('aucun écran défini, ajout des écrans par défaut', 'screen.*')
        results_screen_id: str = f'auto-{ScreenType.Results.value}'
        if len(self._tournaments) > 1:
            update_menu: str = ','.join([
                f'{tournament_id}-auto-{ScreenType.Boards.value}-update' for tournament_id in self._tournaments
            ])
            view_menu: str = ','.join([
                f'{tournament_id}-auto-{ScreenType.Boards.value}-view' for tournament_id in self._tournaments
            ])
            players_menu: str = ','.join([
                f'{tournament_id}-auto-{ScreenType.Players.value}' for tournament_id in self._tournaments
            ])
            results_menu: str = 'none'
        else:
            tournament: Tournament = list(self._tournaments.values())[0]
            update_menu: str = 'none'
            view_menu: str = ','.join([
                f'{tournament.id}-auto-{ScreenType.Boards.value}-view',
                f'{tournament.id}-auto-{ScreenType.Players.value}',
                f'auto-{ScreenType.Results.value}',
            ])
            players_menu: str = view_menu
            results_menu: str = view_menu
        for tournament_id in self._tournaments:
            tournament_name = self._tournaments[tournament_id].name
            auto_screens: dict[str, dict[str, str]] = {
                f'{tournament_id}-auto-{ScreenType.Boards.value}-update': {
                    'type': ScreenType.Boards.value,
                    'update': 'on',
                    'name': f'{f"{tournament_name} - " if len(self._tournaments) > 1 else ""}'
                            f'Saisie des résultats',
                    'menu_text': tournament_name if len(self._tournaments) > 1 else '',
                    'menu': update_menu,
                },
                f'{tournament_id}-auto-{ScreenType.Boards.value}-view': {
                    'type': ScreenType.Boards.value,
                    'update': 'off',
                    'name': f'{f"{tournament_name} - " if len(self._tournaments) > 1 else ""}'
                            f'Appariements par échiquier',
                    'menu_text': tournament_name
                    if len(self._tournaments) > 1
                    else 'Appariements par échiquier',
                    'menu': view_menu,
                },
                f'{tournament_id}-auto-{ScreenType.Players.value}': {
                    'type': ScreenType.Players.value,
                    'name': f'{f"{tournament_name} - " if len(self._tournaments) > 1 else ""}'
                            f'Appariements par ordre alphabétique',
                    'columns': '2',
                    'menu_text': tournament_name
                    if len(self._tournaments) > 1
                    else 'Appariements par ordre alphabétique',
                    'menu': players_menu,
                },
            }
            for screen_id, options in auto_screens.items():
                section_key: str = f'screen.{screen_id}'
                self._config_reader[section_key] = options
                screen_ids.append(screen_id)
                self._config_reader.add_debug(
                    f"l'écran [{screen_id}] a été ajouté",
                    'screen.*'
                )
            auto_screen_sets: dict[str, dict[str, str]] = {
                f'{tournament_id}-auto-{ScreenType.Boards.value}-update.{ScreenType.Boards.value}': {
                    'tournament': tournament_id,
                },
                f'{tournament_id}-auto-{ScreenType.Boards.value}-view.{ScreenType.Boards.value}': {
                    'tournament': tournament_id,
                },
                f'{tournament_id}-auto-{ScreenType.Players.value}.players': {
                    'tournament': tournament_id,
                },
            }
            for screen_set_id, options in auto_screen_sets.items():
                section_key: str = f'screen.{screen_set_id}'
                self._config_reader[section_key] = options
        self._config_reader[f'screen.{results_screen_id}'] = {
            'type': ScreenType.Results.value,
            'name': f'Derniers résultats',
            'menu_text': f'Derniers résultats',
            'menu': results_menu,
        }
        self._config_reader.add_debug(
            f"l'écran [{results_screen_id}] a été ajouté",
            'screen.*'
        )
        screen_ids.append(results_screen_id)
        if len(self._tournaments) > 1:
            self._config_reader[f'rotator.auto-{ScreenType.Boards.value}'] = {
                'screens': view_menu,
            }
            self._config_reader[f'rotator.auto-{ScreenType.Players.value}'] = {
                'screens': players_menu,
            }
        else:
            self._config_reader['rotator.auto'] = {
                'screens': view_menu,
            }
