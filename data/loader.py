import time
from contextlib import suppress
from logging import Logger

from litestar.contrib.htmx.request import HTMXRequest

from common.papi_web_config import PapiWebConfig
from data.event import NewEvent
from database.sqlite import EventDatabase
from database.store import StoredEvent
from common.logger import get_logger

logger: Logger = get_logger()


class EventLoader:
    def __init__(self, lazy_load: bool):
        self.lazy_load = lazy_load
        self._event_ids: list[str] | None = None
        self._loaded_stored_events_by_id: dict[str, StoredEvent | None] = {}
        self._stored_events_by_id: dict[str, StoredEvent] | None = None
        self._stored_events_sorted_by_name: list[StoredEvent] | None = None
        self._loaded_events_by_id: dict[str, NewEvent | None] = {}
        self._events_by_id: dict[str, NewEvent] | None = None
        self._events_sorted_by_name: list[NewEvent] | None = None
        self._events_with_tournaments_sorted_by_name: list[NewEvent] | None = None
        self._public_events: list[NewEvent] | None = None
        self._passed_public_events: list[NewEvent] | None = None
        self._current_public_events: list[NewEvent] | None = None
        self._coming_public_events: list[NewEvent] | None = None

    @staticmethod
    def get(request: HTMXRequest | None, lazy_load: bool):
        if not request:
            return EventLoader(lazy_load=lazy_load)
        event_loader: EventLoader = request.state.get('event_loader')
        if event_loader and lazy_load:
            return event_loader
        event_loader = EventLoader(lazy_load=False)
        request.state['event_loader'] = event_loader
        return event_loader

    def clear_cache(self, event_uniq_id: str = None):
        self._event_ids = None
        if event_uniq_id:
            with suppress(KeyError):
                del self._loaded_stored_events_by_id[event_uniq_id]
        self._stored_events_by_id = None
        self._stored_events_sorted_by_name = None
        if event_uniq_id:
            with suppress(KeyError):
                del self._loaded_events_by_id[event_uniq_id]
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
            self._event_ids = [file.stem for file in PapiWebConfig().event_path.glob(f'*.{PapiWebConfig().event_ext}')]
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

    def _load_event(self, uniq_id: str, reload: bool) -> NewEvent:
        if reload:
            self.clear_cache(uniq_id)
        try:
            return self._loaded_events_by_id[uniq_id]
        except KeyError:
            stored_event: StoredEvent = self.load_stored_event(uniq_id)
            self._loaded_events_by_id[uniq_id] = NewEvent(stored_event, lazy_load=self.lazy_load)
            return self._loaded_events_by_id[uniq_id]

    def load_event(self, uniq_id: str) -> NewEvent:
        return self._load_event(uniq_id, reload=False)

    def reload_event(self, uniq_id: str) -> NewEvent:
        return self._load_event(uniq_id, reload=True)

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

    @property
    def events_with_tournaments_sorted_by_name(self) -> list[NewEvent]:
        if self._events_with_tournaments_sorted_by_name is None:
            self._events_with_tournaments_sorted_by_name = [
                event for event in self.events_sorted_by_name if event.tournaments_by_id
            ]
        return self._events_with_tournaments_sorted_by_name

    @property
    def public_events(self) -> list[NewEvent]:
        if self._public_events is None:
            self._public_events = sorted([
                event for event in self.events_by_id.values()
                if event.public
            ], key=lambda event: event.name)
        return self._public_events

    @property
    def passed_public_events(self) -> list[NewEvent]:
        if self._passed_public_events is None:
            self._passed_public_events = sorted([
                event for event in self.events_by_id.values()
                if event.public and event.stop < time.time()
            ], key=lambda event: (-event.stop, -event.start, event.name))
        return self._passed_public_events

    @property
    def current_public_events(self) -> list[NewEvent]:
        if self._current_public_events is None:
            self._current_public_events = sorted([
                event for event in self.events_by_id.values()
                if event.public and event.start < time.time() < event.stop
            ], key=lambda event: (-event.stop, -event.start, event.name))
        return self._current_public_events

    @property
    def coming_public_events(self) -> list[NewEvent]:
        if self._coming_public_events is None:
            self._coming_public_events = sorted([
                event for event in self.events_by_id.values()
                if event.public and time.time() < event.start
            ], key=lambda event: (-event.stop, -event.start, event.name))
        return self._coming_public_events
