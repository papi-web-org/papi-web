import re
from math import ceil
from typing import TYPE_CHECKING

from common.config_reader import ConfigReader
from common.papi_web_config import PapiWebConfig
from data.screen import ANewScreen, ANewScreenWithSets, NewBoardsScreen, NewPlayersScreen
from data.template import Template
from data.tournament import Tournament, NewTournament
from data.util import ScreenType
from database.store import StoredFamily

if TYPE_CHECKING:
    from data.event import NewEvent


class FamilyBuilder:
    def __init__(self, config_reader: ConfigReader, tournaments: dict[str, Tournament], templates: dict[str, Template]):
        self._config_reader: ConfigReader = config_reader
        self._tournaments: dict[str, Tournament] = tournaments
        self._templates: dict[str, Template] = templates
        family_ids: list[str] = self._read_family_ids()
        if not family_ids:
            self._config_reader.add_debug('aucune famille déclarée', 'family.*')
            return
        for family_id in family_ids:
            self._build_family(family_id)

    def _read_family_ids(self) -> list[str]:
        return self._config_reader.get_subsection_keys_with_prefix('family')

    def _build_family(self, family_id: str):
        section_key = f'family.{family_id}'
        family_section = self._config_reader[section_key]
        section_keys = ['template', 'range', 'parts', 'number', 'first', 'last']
        for key in family_section:
            if key not in section_keys:
                self._config_reader.add_warning(
                    'option de famille inconnue, ignorée',
                    section_key, key)
        key = 'template'
        try:
            template_id = family_section[key]
        except KeyError:
            if family_id in self._templates:
                template_id = family_id
                self._config_reader.add_info(
                    f'option absente, utilisation par défaut du modèle du même nom [{template_id}]',
                    section_key, key)
            elif len(self._templates) == 1:
                template_id = list(self._templates.keys())[0]
                self._config_reader.add_info(
                    f'option absente, utilisation par défaut de l\'unique modèle [{template_id}]',
                    section_key, key)
            else:
                self._config_reader.add_warning(
                    f'option absente et modèle [{family_id}] non trouvé, famille ignorée',
                    section_key, key)
                return
        if template_id not in self._templates:
            self._config_reader.add_warning(
                f"le modèle [{template_id}] n'existe pas, famille ignorée",
                section_key, key)
            return
        template: Template = self._templates[template_id]
        template_type: ScreenType = ScreenType(template.data[None]['type'])
        # note: template_type is boards or players (control done by TemplateBuilder)
        key = 'first'
        first: int | None = None
        if key in family_section:
            first = self._config_reader.getint_safe(section_key, key, minimum=1)
            if first is None:
                self._config_reader.add_warning('un entier positif non nul est attendu, option ignorée',
                                                section_key, key)
            elif template_type != ScreenType.Boards:
                self._config_reader.add_warning(f"l'option [first] ne peut être utilisée que pour les modèles de"
                                                f" type [{ScreenType.Boards}]")
                first = None
        key = 'last'
        last: int | None = None
        if key in family_section:
            last = self._config_reader.getint_safe(section_key, key, minimum=1)
            if last is None:
                self._config_reader.add_warning('un entier positif non nul est attendu, option ignorée',
                                                section_key, key)
            elif template_type != ScreenType.Boards:
                self._config_reader.add_warning(f"l'option [last] ne peut être utilisée que pour les modèles de"
                                                f" type [{ScreenType.Boards}]")
                last = None
        key = 'number'
        number: int | None = None
        if key in family_section:
            number = self._config_reader.getint_safe(section_key, key, minimum=1)
            if number is None:
                self._config_reader.add_warning('un entier positif non nul est attendu, option ignorée',
                                                section_key, key)
        key = 'parts'
        parts: int | None = None
        if key in family_section:
            parts = self._config_reader.getint_safe(section_key, key, minimum=1)
            if parts is None:
                self._config_reader.add_warning('un entier positif non nul est attendu, option ignorée',
                                                section_key, key)
        if parts is not None and number is not None:
            self._config_reader.add_warning("les options [parts] et [number] ne sont pas compatibles, "
                                            "famille ignorée", section_key)
            return
        key = 'range'
        range_str: str | None
        try:
            range_str = family_section[key]
        except KeyError:
            range_str = None
        family_indices: list[str] | None = None
        if parts is not None:
            first_number: int = 0
            last_number: int = 0
            if range_str is not None:
                if matches := re.match(r'^(?P<first>\d+)-(?P<second>\d+)$', range_str):
                    first_number = int(matches.group('first'))
                    last_number = min(parts, int(matches.group('second')))
            else:
                first_number = 1
                last_number = parts
            if first_number <= last_number:
                family_indices = list(
                    map(str, range(first_number, last_number + 1))
                )
            else:
                self._config_reader.add_warning(
                    f'valeurs [{first_number}-{last_number}] non valides, famille ignorée', section_key)
                return
        elif number is not None:
            key = 'number'
            # need the total number of items of the tournament
            tournament: Tournament | None = None
            for sub_section_key, properties in template.data.items():
                if sub_section_key is not None and 'tournament' in properties:
                    tournament_uniq_id: str = properties['tournament']
                    try:
                        tournament = self._tournaments[tournament_uniq_id]
                    except KeyError:
                        self._config_reader.add_warning(f'le tournoi [{tournament_uniq_id}] du modèle [{template.id}] '
                                                        f'n\'existe pas, famille ignorée', section_key, key)
                        return
            if tournament is None:
                if len(self._tournaments) == 1:
                    tournament = list(self._tournaments.values())[0]
                else:
                    self._config_reader.add_warning(f'le tournoi du modèle [{template.id}] n\'est pas défini, '
                                                    f'famille ignorée', section_key, key)
                    return
            total_items_number: int
            if template_type == ScreenType.Boards:
                if tournament.current_round:
                    total_items_number = len(tournament.boards[slice(first, last)])
                else:
                    total_items_number = len(list(tournament.players_by_id.keys())[slice(first, last)])
            else:  # Players
                # note: template_type is boards or players (control done by TemplateBuilder)
                if tournament.current_round:
                    template_show_unpaired: bool = PapiWebConfig().default_players_show_unpaired
                    if 'show_unpaired' in template.data[None]:
                        template_section_key: str = f'template.{template_id}'
                        template_show_unpaired = self._config_reader.getboolean_safe(
                            template_section_key, 'show_unpaired')
                        if template_show_unpaired is None:
                            self._config_reader.add_warning(
                                f'un booléen est attendu pour l\'option show_unpaired '
                                f'du modèle {template_id}, famille ignorée', section_key)
                            return
                    if template_show_unpaired:
                        total_items_number = len(tournament.players_by_id)
                    else:
                        total_items_number = len(tournament.players_by_id) - len(tournament.unpaired_players)
                else:
                    total_items_number = len(tournament.players_by_id)
            if not total_items_number:
                self._config_reader.add_warning(f'Il n\'y a aucun élément à afficher pour le tournoi '
                                                f'[{tournament.uniq_id}], famille ignorée', section_key, key)
                return
            number_parts: int = ceil(total_items_number / number)
            first_number: int
            last_number: int
            if range_str is not None:
                if matches := re.match(r'^(?P<first>\d+)-(?P<second>\d+)$', range_str):
                    first_number = int(matches.group('first'))
                    last_number = min(number_parts, int(matches.group('second')))
                else:
                    self._config_reader.add_warning(
                        f'valeurs [{range_str}] non valides, famille ignorée', section_key)
                    return
            else:
                first_number = 1
                last_number = number_parts
            if first_number <= last_number:
                family_indices = list(map(str, range(first_number, last_number + 1)))
            else:
                self._config_reader.add_warning(
                    f'valeurs [{first_number}-{last_number}] non valides, famille ignorée', section_key)
                return
        else:
            key = 'range'
            if range_str is None:
                self._config_reader.add_warning("une des options [parts], [number] ou [range] est obligatoire, "
                                                "famille ignorée", section_key)
                return
            if matches := re.match(r'^(?P<first>\d+)-(?P<second>\d+)$', range_str):
                first_number = int(matches.group('first'))
                last_number = int(matches.group('second'))
                if first_number <= last_number:
                    family_indices = list(
                        map(str, range(first_number, last_number + 1))
                    )
            else:
                first_letter: str | None = None
                last_letter: str | None = None
                if matches := re.match('^(?P<first>[A-Z])-(?P<second>[A-Z])$', range_str):
                    first_letter = matches.group('first')
                    last_letter = matches.group('second')
                elif matches := re.match('^(?P<first>[a-z])-(?P<second>[a-z])$', range_str):
                    first_letter = matches.group('first')
                    last_letter = matches.group('second')
                if ord(first_letter) <= ord(last_letter):
                    family_indices = list(
                        map(chr, range(ord(first_letter), ord(last_letter) + 1))
                    )
            if family_indices is None:
                self._config_reader.add_warning(f'valeurs [{range_str}] non valides, famille ignorée',
                                                section_key, key)
                return
        self._config_reader.add_debug(f"valeurs : {' '.join(family_indices)}", section_key, key)
        for screen_index in family_indices:
            screen_id = f'{section_key.split(".")[1]}-{screen_index}'
            screen_section_key = f'screen.{screen_id}'
            self._config_reader.setdefault(screen_section_key, {})
            self._config_reader[screen_section_key]['__family__'] = family_id
            template_extended_data: dict[str | None, dict[str, str]] = template.data
            if template_type.value not in template.data:
                # this way parts, number and part will be set below even if [template.<template_id>.template_type]
                # is not declared
                template_extended_data[str(template_type.value)] = {}
            if first is not None:
                template_extended_data[str(template_type.value)]['first'] = str(first)
            if last is not None:
                template_extended_data[str(template_type.value)]['last'] = str(last)
            for sub_section_key, properties in template_extended_data.items():
                if sub_section_key is None:
                    new_section_key = screen_section_key
                else:
                    new_section_key = f'{screen_section_key}.{sub_section_key}'
                self._config_reader.add_debug(f"ajout de la rubrique [{new_section_key}]", section_key)
                self._config_reader.setdefault(new_section_key, {})
                for key, value in properties.items():
                    new_value = value.replace('?', screen_index)
                    self._config_reader.add_debug(f"ajout de l'option {key} = {new_value}", new_section_key)
                    self._config_reader[new_section_key][key] = new_value
                if sub_section_key is not None:
                    key = 'parts'
                    if parts is not None:
                        new_value: str = str(parts)
                        if key not in self._config_reader[new_section_key]:
                            self._config_reader.add_debug(f"ajout de l'option {key} = {new_value}",
                                                          new_section_key)
                            self._config_reader[new_section_key][key] = new_value
                        elif self._config_reader[new_section_key][key] != new_value:
                            self._config_reader.add_debug(f"remplacement de l'option {key} = "
                                                          f"{self._config_reader[new_section_key][key]} "
                                                          f"> {new_value}", new_section_key)
                            self._config_reader[new_section_key][key] = new_value
                    key = 'number'
                    if number is not None:
                        new_value: str = str(number)
                        if key not in self._config_reader[new_section_key]:
                            self._config_reader.add_debug(f"ajout de l'option {key} = {new_value}",
                                                          new_section_key)
                            self._config_reader[new_section_key][key] = new_value
                        elif self._config_reader[new_section_key][key] != new_value:
                            self._config_reader.add_debug(f"remplacement de l'option {key} = "
                                                          f"{self._config_reader[new_section_key][key]} "
                                                          f"> {new_value}", new_section_key)
                            self._config_reader[new_section_key][key] = new_value
                    key = 'part'
                    if number is not None or parts is not None:
                        new_value: str = screen_index
                        if key not in self._config_reader[new_section_key]:
                            self._config_reader.add_debug(f"ajout de l'option {key} = {new_value}",
                                                          new_section_key)
                            self._config_reader[new_section_key][key] = new_value
                        elif self._config_reader[new_section_key][key] != new_value:
                            self._config_reader.add_debug(f"remplacement de l'option {key} = "
                                                          f"{self._config_reader[new_section_key][key]} "
                                                          f"> {new_value}", new_section_key)
                            self._config_reader[new_section_key][key] = new_value
            self._config_reader.add_debug(f'écran [{screen_id}] ajouté', section_key)


class NewFamily:
    def __init__(
            self,
            event: 'NewEvent',
            stored_family: StoredFamily,
    ):
        self.event: 'NewEvent' = event
        self.stored_family: StoredFamily = stored_family
        self.screens_by_uniq_id: dict[str, ANewScreen] = {}
        self.error: str | None = None
        self.calculated_first: int | None = None
        self.calculated_last: int | None = None
        self.calculated_number: int | None = None
        self.calculated_parts: int | None = None
        if self._calculate_screens():
            self._build_screens()

    @property
    def id(self) -> int:
        return self.stored_family.id

    @property
    def type(self) -> ScreenType:
        return ScreenType.from_str(self.stored_family.type)

    @property
    def uniq_id(self) -> str:
        return self.stored_family.uniq_id

    @property
    def name(self) -> str | None:
        if self.stored_family.name:
            return self.stored_family.name
        else:
            if len(self.screens_by_uniq_id) > 1:
                return '%f à %l'
            else:
                return '%t'

    @property
    def tournament_id(self) -> int | None:
        return self.stored_family.tournament_id

    @property
    def tournament(self) -> Tournament | None:
        return self.event.tournaments_by_id[self.tournament_id] if self.tournament_id else None

    @property
    def columns(self) -> int:
        if self.stored_family.columns:
            return self.stored_family.columns
        return 1

    @property
    def menu_text(self) -> str | None:
        return self.stored_family.menu_text

    @property
    def menu(self) -> str | None:
        return self.stored_family.menu

    @property
    def timer_id(self) -> int | None:
        return self.stored_family.timer_id

    @property
    def timer(self) -> Tournament | None:
        return self.event.timers_by_id[self.timer_id] if self.timer_id else None

    @property
    def boards_update(self) -> bool:
        return self.stored_family.boards_update

    @property
    def players_show_unpaired(self) -> bool:
        if self.stored_family.players_show_unpaired is None:
            return PapiWebConfig().default_players_show_unpaired
        return self.stored_family.players_show_unpaired

    @staticmethod
    def screen_icon_str(type: ScreenType, boards_update: bool = None) -> str:
        match type:
            case ScreenType.Boards:
                return 'bi-pencil-fill' if boards_update else 'bi-card-list'
            case ScreenType.Players:
                return 'bi-people-fill'
            case ScreenType.Results:
                return 'bi-trophy-fill'
            case _:
                raise ValueError(f'type=[{type}]')

    @property
    def icon_str(self) -> str:
        return self.screen_icon_str(self.type, self.boards_update if self.type == ScreenType.Boards else None)

    @staticmethod
    def screen_type_str(type: ScreenType, boards_update: bool | None) -> str:
        match type:
            case ScreenType.Boards:
                return 'Saisie' if boards_update else 'Échiquiers'
            case ScreenType.Players:
                return 'Joueur·euses'
            case ScreenType.Results:
                return 'Résultats'
            case _:
                raise ValueError(f'type=[{type}]')

    @property
    def type_str(self) -> str:
        return self.screen_type_str(self.type, self.boards_update if self.type == ScreenType.Boards else None)

    @property
    def first(self) -> int | None:
        return self.stored_family.first

    @property
    def last(self) -> int | None:
        return self.stored_family.last

    @property
    def parts(self) -> int | None:
        return self.stored_family.parts

    @property
    def number(self) -> int | None:
        return self.stored_family.number

    def _calculate_screens(self) -> bool:
        assert self.parts is None or self.number is None  # already checked on family creation
        # At first get the items
        if not self.tournament_id:
            self.error = f'Le tournoi de la famille n\'est pas défini, famille ignorée.'
            self.event.add_warning(self.error, family_uniq_id=self.uniq_id)
            return False
        try:
            tournament: NewTournament = self.event.tournaments_by_id[self.tournament_id]
        except KeyError:
            self.error = f'Le tournoi [{self.tournament_id}] n\'existe pas, famille ignorée.'
            self.event.add_warning(self.error, family_uniq_id=self.uniq_id)
            return False
        if not tournament.rounds:
            self.error = f'Le tournoi [{self.tournament_id}] ne peut être lu, famille ignorée.'
            self.event.add_warning(self.error, family_uniq_id=self.uniq_id)
            return False
        first_item_number: int
        match ScreenType.from_str(self.type):
            case ScreenType.Boards:
                if tournament.current_round:
                    total_items_number: int = len(tournament.boards)
                    if self.first:
                        if self.first > total_items_number:
                            self.error = f'Le tournoi ne comporte que [{total_items_number}] échiquiers, ' \
                                         f'famille ignorée.'
                            self.event.add_warning(self.error, family_uniq_id=self.uniq_id)
                            return False
                        self.calculated_first = self.first
                    else:
                        self.calculated_first = 1
                    if self.last:
                        self.calculated_last = min(self.last, total_items_number)
                    else:
                        self.calculated_last = total_items_number
                    cut_items_number = self.calculated_last - self.calculated_first + 1
                else:
                    cut_items_number = len(tournament.players_by_name_with_unpaired)
                    self.calculated_first = 1
                    self.calculated_last = cut_items_number
            case ScreenType.Players:
                players_show_unpaired: bool
                if self.players_show_unpaired is None:
                    players_show_unpaired = PapiWebConfig().default_players_show_unpaired
                else:
                    players_show_unpaired = self.players_show_unpaired
                if players_show_unpaired:
                    cut_items_number = len(tournament.players_by_name_with_unpaired)
                else:
                    cut_items_number = len(tournament.players_by_name_without_unpaired)
                self.calculated_first = 1
                self.calculated_last = cut_items_number
            case _:
                raise ValueError(f'type={self.type}')
        if not cut_items_number:
            self.error = f'Il n\'y a aucun élément à afficher pour le tournoi [{tournament.uniq_id}], famille ignorée.'
            self.event.add_warning(self.error, family_uniq_id=self.uniq_id)
            return False
        # OK now we know the number of items and the number of the first item to take
        # Let's go for the number of items by part and the number of parts
        if self.number:
            self.calculated_number = self.number
        elif self.parts:
            self.calculated_number = ceil(cut_items_number / self.parts)
        else:
            self.calculated_number = cut_items_number
        # ensure that the number of items is divisible by the number of columns
        if self.calculated_number % self.columns != 0:
            self.calculated_number = min(
                (self.calculated_number // self.columns + 1) * self.columns,
                cut_items_number)
        # recalculate the number of parts
        # (because the number of items by part may increase to fit the number of columns)
        self.calculated_parts = ceil(cut_items_number / self.calculated_number)
        return True

    def _build_screens(self):
        for family_index in range(1, self.calculated_parts + 1):
            screen: ANewScreenWithSets
            if self.type == ScreenType.Boards:
                screen = NewBoardsScreen(self.event, family=self, family_part=family_index)
            else:
                screen = NewPlayersScreen(self.event, family=self, family_part=family_index)
            self.screens_by_uniq_id[screen.uniq_id] = screen

    @property
    def numbers_str(self):
        name: str = 'échiquiers' if self.type == ScreenType.Boards else 'joueur·euses'
        match (self.first, self.last, self.number, self.parts):
            case (None, None, None, None):
                return 'tous les échiquiers' if self.type == ScreenType.Boards else 'tou·tes les joueur·euses'
            case (first, None, None, None) if first is not None:
                return f'{name} à partir du n°{first}'
            case (None, last, None, None) if last is not None:
                return f"{name} jusqu'à n°{last}"
            case (first, last, None, None) if first is not None and last is not None:
                return f'{name} du n°{first} au n°{last}'
            case (None, None, number, None) if number is not None:
                return f'écrans de {number} {name}'
            case (first, None, number, None) if first is not None and number is not None:
                return f'écrans de {number} {name} à partir du n°{first}'
            case (None, last, number, None) if last is not None and number is not None:
                return f'écrans de {number} {name} jusqu\'au n°{last}'
            case (first, last, number, None) if first is not None and last is not None and number is not None:
                return f'écrans de {number} {name} du n°{first} au n°{last}'
            case (None, None, None, parts) if parts is not None:
                return f'{name} sur {parts} écrans'
            case (first, None, None, parts) if first is not None and parts is not None:
                return f'{name} à partir de n°{first}, sur {parts} écrans'
            case (None, last, None, parts) if last is not None and parts is not None:
                return f'{name} jusqu\'au n°{last}, sur {parts} écrans'
            case (first, last, None, parts) if first is not None and last is not None and parts is not None:
                return f'{name} du n°{first} au n°{last}, sur {parts} écrans'
            case _:
                raise ValueError(
                    f'first={self.first}, last={self.last}, parts={self.parts}, number={self.number}')

    def __str__(self):
        if self.tournament:
            return f'Tournoi {self.tournament.uniq_id} ({self.numbers_str})'
        else:
            return f'Tournoi non défini ({self.numbers_str})'
