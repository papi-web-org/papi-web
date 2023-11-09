import re

from common.config_reader import ConfigReader
from data.template import Template


class FamilyBuilder:
    def __init__(self, config_reader: ConfigReader, templates: dict[str, Template]):
        self._config_reader: ConfigReader = config_reader
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
        section_keys = ['template', 'range', ]
        for key in family_section:
            if key not in section_keys:
                self._config_reader.add_warning(
                    'option de famille inconnue, ignorée',
                    section_key, key)
        key = 'template'
        try:
            template_id = family_section[key]
        except KeyError:
            self._config_reader.add_warning('option absente, famille ignorée', section_key, key)
            return
        if template_id not in self._templates:
            self._config_reader.add_warning(
                f"le modèle [{template_id}] n'existe pas, famille ignorée",
                section_key, key)
            return
        template: Template = self._templates[template_id]
        key = 'range'
        try:
            range_str = family_section[key]
        except KeyError:
            self._config_reader.add_warning('option absente, famille ignorée', section_key, key)
            return

        family_indices: list[str] | None = None
        # NOTE(Amaras) The walrus operator (:= aka assignment expression)
        # is available since Python 3.8 and this use case is one of the
        # motivational examples for its introduction, so let's use it.
        if matches := re.match(r'^(?P<first>\d+)-(?P<second>\d+)$', range_str):
            first_number = int(matches.group('first'))
            last_number = int(matches.group('second'))
            if first_number <= last_number:
                family_indices = list(
                    map(str, range(first_number, last_number + 1))
                )
        elif matches := re.match('^(?P<first>[A-Z])-(?P<second>[A-Z])$', range_str):
            first_letter = matches.group('first')
            last_letter = matches.group('second')
            if ord(first_letter) <= ord(last_letter):
                family_indices = list(
                    map(chr, range(ord(first_letter), ord(last_letter) + 1))
                )
        elif matches := re.match('^(?P<first>[a-z])-(?P<second>[a-z])$', range_str):
            first_letter = matches.group('first')
            last_letter = matches.group('second')
            if ord(first_letter) <= ord(last_letter):
                family_indices = list(
                    map(chr, range(ord(first_letter), ord(last_letter) + 1))
                )
        if family_indices is None:
            self._config_reader.add_warning(
                f'valeurs [{range_str}] non valides, famille ignorée',
                section_key,
                key
            )
            return
        self._config_reader.add_debug(f"valeurs : {' '.join(family_indices)}", section_key, key)
        for screen_index in family_indices:
            screen_id = f'{section_key.split(".")[1]}-{screen_index}'
            screen_section_key = f'screen.{screen_id}'
            self._config_reader.setdefault(screen_section_key, {})
            self._config_reader[screen_section_key]['__family__'] = family_id
            for sub_section_key, properties in template.data.items():
                if sub_section_key is None:
                    new_section_key = screen_section_key
                else:
                    new_section_key = f'{screen_section_key}.{sub_section_key}'
                # screen_section = self.reader.setdefault(new_section_key, {})
                self._config_reader.setdefault(new_section_key, {})
                self._config_reader.add_debug(f"ajout de la rubrique [{new_section_key}]", section_key)
                for key, value in properties.items():
                    new_value = value.replace('?', screen_index)
                    # NOTE(pascalaubry) I wonder why the previous code did not work...
                    # screen_section.setdefault(key, new_value)
                    self._config_reader[new_section_key][key] = new_value
                    self._config_reader.add_debug(f"ajout de l'option {key} = {new_value}", new_section_key)
            self._config_reader.add_debug(f'écran [{screen_id}] ajouté', section_key)
