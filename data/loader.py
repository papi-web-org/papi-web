from contextlib import suppress
from logging import Logger

from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from database.sqlite import EventDatabase
from database.store import StoredEvent
from common.logger import get_logger

logger: Logger = get_logger()


class EventLoader:
    def __init__(self):
        self._event_ids: list[str] | None = None
        self._loaded_stored_events_by_id: dict[str, StoredEvent | None] = {}
        self._stored_events_by_id: dict[str, StoredEvent] | None = None
        self._stored_events_sorted_by_name: list[StoredEvent] | None = None
        self._loaded_events_by_id: dict[str, NewEvent | None] = {}
        self._events_by_id: dict[str, NewEvent] | None = None
        self._events_sorted_by_name: list[NewEvent] | None = None

    def clear_cache(self, uniq_id: str = None):
        self._event_ids = None
        if uniq_id:
            with suppress(KeyError):
                del self._loaded_stored_events_by_id[uniq_id]
        self._stored_events_by_id = None
        self._stored_events_sorted_by_name = None
        if uniq_id:
            with suppress(KeyError):
                del self._loaded_events_by_id[uniq_id]
        self._events_by_id = None
        self._events_sorted_by_name = None

    @staticmethod
    def _load_stored_event(uniq_id: str) -> StoredEvent:
        with EventDatabase(uniq_id) as event_database:
            return event_database.load_stored_event()

    def load_stored_event(self, uniq_id: str) -> StoredEvent:
        try:
            return self._loaded_stored_events_by_id[uniq_id]
        except KeyError:
            self._loaded_stored_events_by_id[uniq_id] = self._load_stored_event(uniq_id)
            return self._loaded_stored_events_by_id[uniq_id]

    @property
    def event_ids(self) -> list[str]:
        if self._event_ids is None:
            self._event_ids = [file.stem for file in PapiWebConfig().db_path.glob(f'*.{PapiWebConfig().db_ext}')]
        return self._event_ids

    @property
    def stored_events_by_id(self) -> dict[str, StoredEvent]:
        if self._stored_events_by_id is None:
            self._stored_events_by_id: dict[str, StoredEvent] = {}
            for uniq_id in self.event_ids:
                self._stored_events_by_id[uniq_id] = self.load_stored_event(uniq_id)
        return self._stored_events_by_id

    @property
    def stored_events_sorted_by_name(self) -> list[StoredEvent]:
        if self._stored_events_sorted_by_name is None:
            self._stored_events_sorted_by_name = sorted(
                self.stored_events_by_id.values(), key=lambda event: event.name)
        return self._stored_events_sorted_by_name

    def _load_event(self, uniq_id: str) -> NewEvent:
        stored_event: StoredEvent = self.load_stored_event(uniq_id)
        event: NewEvent = NewEvent(stored_event)
        return event

    def load_event(self, uniq_id: str, reload: bool = False) -> NewEvent:
        if reload:
            self.clear_cache(uniq_id)
        try:
            return self._loaded_events_by_id[uniq_id]
        except KeyError:
            self._loaded_events_by_id[uniq_id] = self._load_event(uniq_id)
            return self._loaded_events_by_id[uniq_id]

    @property
    def events_by_id(self) -> dict[str, NewEvent]:
        if self._events_by_id is None:
            self._events_by_id: dict[str, NewEvent] = {}
            for uniq_id in self.event_ids:
                self._events_by_id[uniq_id] = self.load_event(uniq_id)
        return self._events_by_id

    @property
    def events_sorted_by_name(self) -> list[NewEvent]:
        if self._events_sorted_by_name is None:
            self._events_sorted_by_name = sorted(
                self.events_by_id.values(), key=lambda event: event.name)
        return self._events_sorted_by_name
