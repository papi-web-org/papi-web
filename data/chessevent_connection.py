from logging import Logger

from common.config_reader import ConfigReader
from common.logger import get_logger

logger: Logger = get_logger()


class ChessEventConnection:
    def __init__(self, connection_id: str, user_id: str, password: str, event_id: str):
        self.connection_id: str = connection_id
        self.user_id: str = user_id
        self.password: str = password
        self.event_id: str = event_id


class ChessEventConnectionBuilder:
    def __init__(self, config_reader: ConfigReader):
        self._config_reader: ConfigReader = config_reader
        self.chessevent_connections: dict[str, ChessEventConnection] = {}
        for chessevent_connection_id in self._read_chessevent_connection_ids():
            self._build_chessevent_connection(chessevent_connection_id)
        if not self.chessevent_connections:
            self._config_reader.add_info('aucune connexion à Chess Event définie')

    def _read_chessevent_connection_ids(self) -> list[str]:
        chessevent_connection_ids: list[str] = self._config_reader.get_subsection_keys_with_prefix('chessevent')
        if 'chessevent' in self._config_reader:
            if chessevent_connection_ids:
                section_keys: str = ', '.join('[chessevent.' + id + ']' for id in chessevent_connection_ids)
                self._config_reader.add_error(
                    f"la rubrique [chessevent] ne doit être utilisée que lorsque l'évènement ne compte "
                    f"qu'une seule connexion à ChessEvent, d'autres rubriques sont présentes ({section_keys})",
                    'tournament.*'
                )
                return []
            default_chessevent_connection_id: str = 'default'
            old_chessevent_connection_section_key: str = 'chessevent'
            new_chessevent_section_key: str = 'chessevent.' + default_chessevent_connection_id
            self._config_reader.rename_section(old_chessevent_connection_section_key, new_chessevent_section_key)
            self._config_reader.add_debug(
                f'une seule connexion à Chess Event, la rubrique [{old_chessevent_connection_section_key}] a '
                f'été renommée [{new_chessevent_section_key}]',
                old_chessevent_connection_section_key
            )
            chessevent_connection_ids.append(default_chessevent_connection_id)
        return chessevent_connection_ids

    def _build_chessevent_connection(self, chessevent_connection_id: str):
        section_key: str = f'chessevent.{chessevent_connection_id}'
        try:
            section = self._config_reader[section_key]
        except KeyError:
            self._config_reader.add_error('Connexion à Chess Event non trouvée', section_key)
            return
        key = ''
        user_id: str
        password: str
        event_id: str
        try:
            key = 'user_id'
            user_id = section[key]
            key = 'password'
            password = section[key]
            key = 'event_id'
            event_id = section[key]
        except KeyError:
            self._config_reader.add_warning('option absente, connexion à Chess Event ignorée', section_key, key)
            return
        except TypeError:
            self._config_reader.add_error(f'La rubrique [{section_key}] est en fait une option', section_key)
            return

        chessevent_connection_section_keys: list[str] = [
            'user_id',
            'password',
            'event_id',
        ]
        for key, _ in section.items():
            if key not in chessevent_connection_section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)

        self.chessevent_connections[chessevent_connection_id] = ChessEventConnection(
            chessevent_connection_id, user_id, password, event_id)
