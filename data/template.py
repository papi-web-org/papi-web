from logging import Logger
from dataclasses import dataclass, field

from common.config_reader import ConfigReader
from common.logger import get_logger
from data.util import ScreenType

logger: Logger = get_logger()


@dataclass
class Template:
    __id: str
    data: dict[str | None, dict[str, str]] = field(default_factory=dict, init=False)

    @property
    def id(self) -> str:
        return self.__id

    def add_data(self, section: str | None, key: str, value: str):
        if section not in self.data:
            self.data[section] = {key: value, }
        else:
            self.data[section][key] = value


class TemplateBuilder:
    def __init__(self, config_reader: ConfigReader):
        self._config_reader: ConfigReader = config_reader
        self._templates: dict[str, Template] = {}
        template_ids: list[str] = self._read_template_ids()
        if not template_ids:
            self._config_reader.add_debug('aucun modèle déclaré', 'template.*')
            return
        for template_id in template_ids:
            self._build_template(template_id)
        if not self._templates:
            self._config_reader.add_debug('aucun modèle initialisé')

    @property
    def templates(self) -> dict[str, Template]:
        return self._templates

    def _read_template_ids(self) -> list[str]:
        return self._config_reader.get_subsection_keys_with_prefix('template')

    def _build_template(self, template_id: str):
        template: Template = Template(template_id)
        section_key = f'template.{template_id}'
        template_section = self._config_reader[section_key]
        for key, value in template_section.items():
            if key not in ConfigReader.screen_keys:
                self._config_reader.add_warning(
                    'option de modèle inconnue, ignorée',
                    section_key,
                    key
                )
            else:
                template.add_data(None, key, value)
                self._config_reader.add_debug(f'option {key} = {value}', section_key)
        subsection_keys = self._config_reader.get_subsection_keys_with_prefix(
            section_key,
            first_level_only=False
        )
        for sub_section_key in subsection_keys:
            splitted = sub_section_key.split('.')
            if splitted[0] not in ScreenType.names() or len(splitted) > 2:
                self._config_reader.add_warning(
                    'rubrique de modèle non valide, ignorée',
                    f'{section_key}.{sub_section_key}'
                )
                continue
            # NOTE(Amaras) Nesting subsections in the Python INI parser
            # (ConfigParser) only works because nested subsections have
            # unique names. Is this behaviour expected?
            subsection_key = f'{section_key}.{sub_section_key}'
            for key, value in self._config_reader.items(subsection_key):
                if key not in ConfigReader.screen_set_keys:
                    self._config_reader.add_warning(
                        'option de modèle inconnue, ignorée',
                        subsection_key,
                        key
                    )
                else:
                    template.add_data(sub_section_key, key, value)
                    self._config_reader.add_debug(f'option [{sub_section_key}].{key} = {value}', section_key)
        self._templates[template_id] = template
