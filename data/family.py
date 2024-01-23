import re
from math import ceil

import common.logger
from common.config_reader import ConfigReader
from data.template import Template
from data.tournament import Tournament
from data.util import ScreenType


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
        section_keys = ['template', 'range', 'parts', 'number', ]
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
            self._config_reader.add_warning(f"les options [parts] et [number] ne sont pas compatibles, "
                                            f"famille ignorée", section_key)
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
                    tournament_id: str = properties['tournament']
                    try:
                        tournament = self._tournaments[tournament_id]
                    except KeyError:
                        self._config_reader.add_warning(f'le tournoi [{tournament_id}] du modèle [{template.id}] '
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
                    total_items_number = len(tournament.boards)
                else:
                    total_items_number = ceil(len(tournament.players_by_id) / 2)
            else:  # Players
                # PA: there may be fewer players to show when unpaired players are no listed
                # but there is no simple way to know whether they should be listed or not at this stage
                total_items_number = len(tournament.players_by_id)
            if not total_items_number:
                self._config_reader.add_warning(f'Il n\'y a aucun élément à afficher pour le tournoi '
                                                f'[{tournament.id}], famille ignorée', section_key, key)
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
                self._config_reader.add_warning(f"une des options [parts], [number] ou [range] est obligatoire, "
                                                f"famille ignorée", section_key)
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
