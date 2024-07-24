from logging import Logger

from common.config_reader import ConfigReader
from common.logger import get_logger
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from data.event import NewEvent
from database.store import StoredChessEvent

logger: Logger = get_logger()


class ChessEvent:
    def __init__(self, uniq_id: str, user_id: str, password: str, event_id: str):
        self.uniq_id: str = uniq_id
        self.user_id: str = user_id
        self.password: str = password
        self.event_id: str = event_id


class ChessEventBuilder:
    def __init__(self, config_reader: ConfigReader):
        self._config_reader: ConfigReader = config_reader
        self.chessevents: dict[str, ChessEvent] = {}
        for chessevent_uniq_id in self._read_chessevent_uniq_ids():
            self._build_chessevent(chessevent_uniq_id)
        if not self.chessevents:
            self._config_reader.add_info('aucune connexion à Chess Event définie')

    def _read_chessevent_uniq_ids(self) -> list[str]:
        chessevent_uniq_ids: list[str] = self._config_reader.get_subsection_keys_with_prefix('chessevent')
        if 'chessevent' in self._config_reader:
            if chessevent_uniq_ids:
                section_keys: str = ', '.join('[chessevent.' + id + ']' for id in chessevent_uniq_ids)
                self._config_reader.add_error(
                    f"la rubrique [chessevent] ne doit être utilisée que lorsque l'évènement ne compte "
                    f"qu'une seule connexion à ChessEvent, d'autres rubriques sont présentes ({section_keys})",
                    'tournament.*'
                )
                return []
            default_chessevent_uniq_id: str = 'default'
            old_chessevent_section_key: str = 'chessevent'
            new_chessevent_section_key: str = 'chessevent.' + default_chessevent_uniq_id
            self._config_reader.rename_section(old_chessevent_section_key, new_chessevent_section_key)
            self._config_reader.add_debug(
                f'une seule connexion à Chess Event, la rubrique [{old_chessevent_section_key}] a '
                f'été renommée [{new_chessevent_section_key}]',
                old_chessevent_section_key
            )
            chessevent_uniq_ids.append(default_chessevent_uniq_id)
        return chessevent_uniq_ids

    def _build_chessevent(self, chessevent_uniq_id: str):
        section_key: str = f'chessevent.{chessevent_uniq_id}'
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

        chessevent_section_keys: list[str] = [
            'user_id',
            'password',
            'event_id',
        ]
        for key in section:
            if key not in chessevent_section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)

        self.chessevents[chessevent_uniq_id] = ChessEvent(
            chessevent_uniq_id, user_id, password, event_id)


class NewChessEvent:
    def __init__(self, event: 'NewEvent', stored_chessevent: StoredChessEvent, ):
        self.id: int = stored_chessevent.id
        self.event: 'NewEvent' = event
        self.uniq_id: str = stored_chessevent.uniq_id
        if not self.uniq_id:
            event.add_error(
                f'L\'identifiant unique de la connexion à ChessEvent [{stored_chessevent.id}] n\'est pas défini')
        self.user_id: str = stored_chessevent.user_id
        if not self.user_id:
            event.add_error(f'L\'identifiant de connexion n\'est pas défini', chessevent_uniq_id=self.uniq_id)
        self.password: str = stored_chessevent.password
        if not self.password:
            event.add_error(f'Le mot de passe de connexion n\'est pas défini', chessevent_uniq_id=self.uniq_id)
        self.event_id: str = stored_chessevent.event_id
        if not self.event_id:
            event.add_error(f'L\'identifiant du tournoi n\'est pas défini', chessevent_uniq_id=self.uniq_id)

