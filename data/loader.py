import time
from contextlib import suppress
from functools import cached_property
from logging import Logger
from operator import attrgetter

from litestar.contrib.htmx.request import HTMXRequest

from common.papi_web_config import PapiWebConfig
from data.event import Event
from database.sqlite import EventDatabase
from database.store import StoredEvent
from common.logger import get_logger

logger: Logger = get_logger()


class EventLoader:
    def __init__(self, lazy_load: bool):
        self.lazy_load = lazy_load
        self._loaded_stored_events_by_id: dict[str, StoredEvent | None] = {}
        self._loaded_events_by_id: dict[str, Event | None] = {}

    @classmethod
    def get(cls, request: HTMXRequest | None, lazy_load: bool):
        if not request:
            return cls(lazy_load=lazy_load)
        event_loader: EventLoader = request.state.get('event_loader')
        if not event_loader or event_loader.lazy_load and not lazy_load:
            request.state['event_loader'] = cls(lazy_load=lazy_load)
        return request.state['event_loader']

    def clear_cache(self, event_uniq_id: str | None = None):
        with suppress(AttributeError):
            del self.event_uniq_ids
        if event_uniq_id:
            with suppress(KeyError):
                del self._loaded_stored_events_by_id[event_uniq_id]
        with suppress(AttributeError):
            del self.stored_events_by_id
        with suppress(AttributeError):
            del self.stored_events_sorted_by_name
        if event_uniq_id:
            with suppress(KeyError):
                del self._loaded_events_by_id[event_uniq_id]
        with suppress(AttributeError):
            del self.events_by_id
        with suppress(AttributeError):
            del self.events_sorted_by_name

    def load_stored_event(self, uniq_id: str) -> StoredEvent:
        try:
            return self._loaded_stored_events_by_id[uniq_id]
        except KeyError:
            with EventDatabase(uniq_id) as event_database:
                self._loaded_stored_events_by_id[uniq_id] = event_database.load_stored_event()
            return self._loaded_stored_events_by_id[uniq_id]

    @cached_property
    def event_uniq_ids(self) -> list[str]:
        return [file.stem for file in PapiWebConfig.event_path.glob(f'*.{PapiWebConfig.event_ext}')]

    @cached_property
    def stored_events_by_id(self) -> dict[str, StoredEvent]:
        return {uniq_id: self.load_stored_event(uniq_id) for uniq_id in self.event_uniq_ids}

    @cached_property
    def stored_events_sorted_by_name(self) -> list[StoredEvent]:
        return sorted(self.stored_events_by_id.values(), key=lambda event: event.name)

    def _load_event(self, uniq_id: str, reload: bool) -> Event:
        if reload:
            self.clear_cache(uniq_id)
        try:
            return self._loaded_events_by_id[uniq_id]
        except KeyError:
            stored_event: StoredEvent = self.load_stored_event(uniq_id)
            self._loaded_events_by_id[uniq_id] = Event(stored_event, lazy_load=self.lazy_load)
            return self._loaded_events_by_id[uniq_id]

    def load_event(self, uniq_id: str) -> Event:
        return self._load_event(uniq_id, reload=False)

    def reload_event(self, uniq_id: str) -> Event:
        return self._load_event(uniq_id, reload=True)

    @cached_property
    def events_by_id(self) -> dict[str, Event]:
        return {uniq_id: self.load_event(uniq_id) for uniq_id in self.event_uniq_ids}

    @cached_property
    def events_sorted_by_name(self) -> list[Event]:
        return sorted(self.events_by_id.values(), key=lambda event: event.name)

    @cached_property
    def events_with_tournaments_sorted_by_name(self) -> list[Event]:
        return [event for event in self.events_sorted_by_name if event.tournaments_by_id]

    @cached_property
    def passed_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.stop < time.time()
        ], key=lambda event: (-event.stop, -event.start, event.name))

    @cached_property
    def current_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.start < time.time() < event.stop
        ], key=lambda event: (-event.stop, -event.start, event.name))

    @cached_property
    def coming_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.public and time.time() < event.start
        ], key=lambda event: (-event.stop, -event.start, event.name))

    @cached_property
    def public_events(self) -> list[Event]:
        return sorted(filter(attrgetter('public'), self.events_by_id.values()), key=attrgetter('name'))

    @cached_property
    def passed_public_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.public and event.stop < time.time()
        ], key=lambda event: (-event.stop, -event.start, event.name))

    @cached_property
    def current_public_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.public and event.start < time.time() < event.stop
        ], key=lambda event: (-event.stop, -event.start, event.name))

    @cached_property
    def coming_public_events(self) -> list[Event]:
        return sorted([
            event for event in self.events_by_id.values()
            if event.public and time.time() < event.start
        ], key=lambda event: (-event.stop, -event.start, event.name))
