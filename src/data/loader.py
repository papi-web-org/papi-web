import re
import shutil
import sqlite3
from time import perf_counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from functools import cached_property
from logging import Logger
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from litestar.plugins.htmx import HTMXRequest
from packaging.version import Version

from common import (
    SHARLY_CHESS_VERSION,
    EVENTS_DIR,
    ARCHIVES_DIR,
    BACKUP_BASE_DIR,
)
from common.exception import SharlyChessException, DatabaseInaccessibleException
from common.i18n.utils import normalized_key
from common.logger import get_logger
from data.event import Event
from data.event_metadata import EventMetadata
from database.sqlite.event.event_database import EventDatabase
from plugins.manager import plugin_manager
from utils import Utils
from utils.date_time import get_date_timestamp, format_datetime
from utils.enum import Extension

logger: Logger = get_logger()


class EventLoader:
    _valid_event_ids: set[str] = set()
    _invalid_uniq_ids: set[str] = set()
    # Event files present on disk but that could not be opened (locked by another
    # program, file sync such as OneDrive, permissions…). Kept apart from
    # _invalid_uniq_ids so they are retried on each scan and recover once the file
    # becomes accessible again.
    _inaccessible_uniq_ids: set[str] = set()
    # Last metadata successfully read for each event, reused to display an event
    # that has become inaccessible with its real name and dates.
    _last_known_metadata: dict[str, EventMetadata] = {}

    @classmethod
    def get(cls, request: HTMXRequest | None):
        if not request:
            return cls()
        event_loader: EventLoader = request.state.get('event_loader', None)
        if not event_loader:
            request.state['event_loader'] = cls()
        return request.state['event_loader']

    @classmethod
    def unload_event(cls, uniq_id: str):
        cls._valid_event_ids.remove(uniq_id)
        cls.load_event_ids()

    @classmethod
    def load_event_ids(cls, uniq_id: str | None = None) -> dict[str, EventMetadata]:
        event_ids = [uniq_id] if uniq_id is not None else cls.all_event_ids()
        cls._clean_not_existing_event_database_files(cls._valid_event_ids)
        cls._clean_not_existing_event_database_files(cls._invalid_uniq_ids)
        cls._clean_not_existing_event_database_files(cls._inaccessible_uniq_ids)
        # Inaccessible ids are deliberately excluded so they are retried: a locked
        # file may become readable again once the lock is released.
        known_event_ids = cls._valid_event_ids | cls._invalid_uniq_ids
        metadata_by_event_id: dict[str, EventMetadata] = {}
        for event_id in event_ids:
            if event_id in known_event_ids:
                continue
            try:
                metadata_by_event_id[event_id] = cls.check_event_database(event_id)
                cls._valid_event_ids.add(event_id)
                cls._inaccessible_uniq_ids.discard(event_id)
                cls._last_known_metadata[event_id] = metadata_by_event_id[event_id]
            except DatabaseInaccessibleException as e:
                logger.debug('Event [%s] could not be opened: %s', event_id, e)
                cls._inaccessible_uniq_ids.add(event_id)
            except SharlyChessException as e:
                logger.debug('Event [%s] could not be loaded: %s', event_id, e)
                cls._invalid_uniq_ids.add(event_id)
        return metadata_by_event_id

    @classmethod
    def inaccessible_events_metadata(cls) -> list[EventMetadata]:
        """Placeholder metadata for event files that exist but could not be opened
        (locked by another program, file sync such as OneDrive, permissions…).
        They are listed but flagged as not accessible so the user can see that they
        exist and have not been lost. As the database can't be read, only the id is
        known; the file modification date is used to place them in the right list."""
        cls.load_event_ids()
        events_metadata: list[EventMetadata] = []
        for uniq_id in sorted(cls._inaccessible_uniq_ids):
            known = cls._last_known_metadata.get(uniq_id)
            if known is not None:
                # Reuse the real name and dates so the event stays in its section.
                events_metadata.append(replace(known, accessible=False))
                continue
            # Never read successfully: fall back to the file modification date.
            try:
                modified = date.fromtimestamp(
                    EventDatabase.event_database_path(uniq_id).stat().st_mtime
                )
            except OSError:
                modified = date.today()
            events_metadata.append(
                EventMetadata(
                    uniq_id=uniq_id,
                    name=uniq_id,
                    federation='',
                    player_rating_type=0,
                    start_date=modified,
                    stop_date=modified,
                    accessible=False,
                )
            )
        return events_metadata

    @classmethod
    def check_event_database(cls, event_uniq_id: str) -> EventMetadata:
        """Check the validity of an event database, raises a SharlyChessError if it is not."""
        database = EventDatabase(event_uniq_id)
        if not database.is_sqlite_file():
            raise SharlyChessException(
                f'File {database.file} is not a SQLite database.'
            )
        try:
            needs_upgrade = not database.check_status()
        except sqlite3.DatabaseError as e:
            raise SharlyChessException(
                f'File {database.file} is a corrupted SQLite database: {e}'
            ) from e
        if needs_upgrade:
            database.upgrade()
        with EventDatabase(event_uniq_id) as database:
            stored_event = database.load_stored_event_metadata()
        for plugin_id in stored_event.enabled_plugins:
            if plugin_id not in plugin_manager.plugins_by_id:
                raise SharlyChessException(
                    f'Event [{event_uniq_id}] - Unknown plugin [{plugin_id}]'
                )
        return stored_event

    def import_event(self, file_path: Path) -> str:
        """Import an event. Raise a SharlyChessException if it fails,
        the event's uniq_id otherwise."""
        uniq_id = self.get_unused_event_uniq_id(self.format_uniq_id(file_path.stem))
        new_path = EventDatabase.event_database_path(uniq_id)
        shutil.move(file_path, new_path)
        try:
            EventLoader.check_event_database(uniq_id)
            # Tag ids are only meaningful within the installation that
            # defined them, so an imported event starts with no tags.
            with EventDatabase(uniq_id, write=True) as database:
                database.delete_all_tags()
            return uniq_id
        except Exception as e:
            new_path.unlink(missing_ok=True)
            raise e

    @staticmethod
    def event_file_path(uniq_id: str) -> Path:
        return EventDatabase.event_database_path(uniq_id)

    @classmethod
    def _clean_not_existing_event_database_files(cls, event_uniq_ids: set[str]):
        to_remove = [
            uniq_id
            for uniq_id in event_uniq_ids
            if not EventDatabase.event_database_path(uniq_id).exists()
        ]
        for uniq_id in to_remove:
            event_uniq_ids.remove(uniq_id)

    @cached_property
    def event_uniq_ids(self) -> list[str]:
        self.load_event_ids()
        return list(self._valid_event_ids)

    @classmethod
    def format_uniq_id(cls, uniq_id: str) -> str:
        return re.sub(r'[^a-zA-Z0-9_\-]', '_', uniq_id)

    @classmethod
    def all_event_ids(cls) -> list[str]:
        ids: list[str] = []
        for file in EVENTS_DIR.glob(f'*.{Extension.EVENT_DB}'):
            uniq_id = cls.format_uniq_id(file.stem)
            if uniq_id != file.stem:
                target_id: str = uniq_id
                index: int = 1
                while cls.event_file_path(target_id).exists():
                    index += 1
                    target_id = f'{uniq_id}-{index}'
                new_file = cls.event_file_path(target_id)
                shutil.move(file, new_file)
                logger.warning(
                    'File [%s] has been renamed [%s]', file.name, new_file.name
                )
                uniq_id = target_id
            ids.append(uniq_id)
        return ids

    def get_unused_event_uniq_id(self, base_uniq_id: str) -> str:
        return Utils.get_unused_item_uniq_id(base_uniq_id, self.all_event_ids())

    def get_unused_event_name(self, base_name: str) -> str:
        return Utils.get_unused_item_name(
            base_name, [event.name for event in self.get_events_metadata()]
        )

    def load_event(self, uniq_id: str) -> Event:
        from web.performance import current_request_performance, record_event_load

        if current_request_performance() is None:
            self.load_event_ids(uniq_id)
            with EventDatabase(uniq_id) as event_database:
                return Event(event_database.load_stored_event())
        start = perf_counter()
        try:
            self.load_event_ids(uniq_id)
            with EventDatabase(uniq_id) as event_database:
                event = Event(event_database.load_stored_event())
            return event
        finally:
            record_event_load(perf_counter() - start)

    @classmethod
    def load_event_metadata(cls, uniq_id: str) -> EventMetadata:
        with EventDatabase(uniq_id) as database:
            event_metadata = database.load_stored_event_metadata()
        return event_metadata

    @classmethod
    def get_events_metadata(
        cls,
        status: Literal['passed', 'current', 'coming'] | None = None,
        public_only: bool = False,
    ) -> list[EventMetadata]:
        return cls.select_events_metadata(
            cls._filter_events_metadata([]), status, public_only=public_only
        )

    @staticmethod
    def select_events_metadata(
        events_metadata: list[EventMetadata],
        status: Literal['passed', 'current', 'coming'] | None = None,
        *,
        public_only: bool = False,
    ) -> list[EventMetadata]:
        """Filter and sort already-loaded metadata without reopening databases."""
        conditions: list[Callable[[EventMetadata], bool]] = []
        if public_only:
            conditions.append(lambda event: event.public)
        today = date.today()
        sort_order = 1
        match status:
            case 'passed':
                conditions.append(lambda event: event.stop_date < today)
                sort_order = -1
            case 'current':
                conditions.append(
                    lambda event: event.start_date <= today <= event.stop_date
                )
            case 'coming':
                conditions.append(lambda event: today < event.start_date)
        return sorted(
            (
                event_metadata
                for event_metadata in events_metadata
                if all(condition(event_metadata) for condition in conditions)
            ),
            key=lambda event: (
                get_date_timestamp(event.stop_date) * sort_order,
                get_date_timestamp(event.start_date) * sort_order,
                normalized_key(event.name),
            ),
        )

    @classmethod
    def _filter_events_metadata(
        cls, conditions: list[Callable[[EventMetadata], bool]]
    ) -> list[EventMetadata]:
        metadata_by_event_id = cls.load_event_ids()
        events_metadata: list[EventMetadata] = []
        # sorted() copies the set so it can be mutated while iterating below.
        for uniq_id in sorted(cls._valid_event_ids):
            metadata = metadata_by_event_id.get(uniq_id)
            if metadata is None:
                try:
                    metadata = cls.load_event_metadata(uniq_id)
                except DatabaseInaccessibleException as e:
                    # An event that was valid but has since become unreadable
                    # (locked, file sync…) is demoted so it is listed as
                    # inaccessible rather than crashing the page.
                    logger.debug('Event [%s] could not be opened: %s', uniq_id, e)
                    cls._valid_event_ids.discard(uniq_id)
                    cls._inaccessible_uniq_ids.add(uniq_id)
                    continue
                except SharlyChessException as e:
                    logger.debug('Event [%s] could not be loaded: %s', uniq_id, e)
                    cls._valid_event_ids.discard(uniq_id)
                    cls._invalid_uniq_ids.add(uniq_id)
                    continue
            cls._last_known_metadata[uniq_id] = metadata
            events_metadata.append(metadata)
        return [
            event_metadata
            for event_metadata in events_metadata
            if all(condition(event_metadata) for condition in conditions)
        ]


@dataclass
class Archive:
    """This class implements archives (deleted events)."""

    file: Path
    name: str
    date: datetime

    @property
    def date_str(self):
        return format_datetime(self.date)

    @property
    def url_name(self) -> str:
        return quote(self.name)

    def restore(self) -> str | None:
        event_uniq_id = EventLoader().get_unused_event_uniq_id(self.name.split('#')[0])
        new_path = EventDatabase.event_database_path(event_uniq_id)
        shutil.copy(self.file, new_path)
        try:
            EventLoader.check_event_database(event_uniq_id)
            self.file.unlink()
            return event_uniq_id
        except SharlyChessException as exception:
            logger.exception(exception)
            new_path.unlink()
            return None


class ArchiveLoader:
    """This class help loading archives (deleted events) efficiently."""

    @staticmethod
    def get_sorted_archives() -> list[Archive]:
        return sorted(
            [
                Archive(file, file.stem, datetime.fromtimestamp(file.lstat().st_ctime))
                for file in ARCHIVES_DIR.glob(f'*.{Extension.ARCHIVE}')
            ],
            key=lambda archive: archive.date,
        )

    @classmethod
    def get_archive(cls, archive_name: str) -> Archive | None:
        """Get an archive by its name if it exists, None if it does not."""
        arch_file = cls.get_archive_path(archive_name)
        if not arch_file.exists():
            return None
        return Archive(
            arch_file,
            arch_file.stem,
            datetime.fromtimestamp(arch_file.lstat().st_ctime),
        )

    @staticmethod
    def get_archive_path(archive_name: str) -> Path:
        return ARCHIVES_DIR / f'{archive_name}.{Extension.ARCHIVE}'


@dataclass
class EventBackup:
    """This class implements backups (copies of event databases)."""

    name: str
    version: Version

    @property
    def file(self) -> Path:
        return BACKUP_BASE_DIR / self.version.public / f'{self.name}.{Extension.BACKUP}'

    @property
    def exists(self) -> bool:
        return self.file.exists()

    def restore(self):
        """Restores the backup of the event. If another event
        with the same name exists, overwrites it"""
        assert self.exists
        shutil.copy(self.file, EventDatabase.event_database_path(self.name))


class EventBackupLoader:
    """This class helps loading backups (copied events)."""

    def __init__(self):
        BACKUP_BASE_DIR.mkdir(exist_ok=True, parents=True)

    @staticmethod
    def event_backups(event_id: str) -> list[EventBackup]:
        backups: list[EventBackup] = []
        for version_dir in BACKUP_BASE_DIR.iterdir():
            if not version_dir.is_dir():
                continue
            backup = EventBackup(event_id, Version(version_dir.name))
            if backup.exists:
                backups.append(backup)
        return backups

    @staticmethod
    def version_backups(version: Version) -> list[EventBackup]:
        version_dir = BACKUP_BASE_DIR / version.public
        return [
            EventBackup(file.stem, version)
            for file in version_dir.glob(f'*.{Extension.BACKUP}')
        ]

    def versions(self, event_id: str | None = None) -> list[Version]:
        if not BACKUP_BASE_DIR.exists():
            return []
        if event_id:
            return [backup.version for backup in self.event_backups(event_id)]
        return [
            Version(version_dir.name)
            for version_dir in BACKUP_BASE_DIR.iterdir()
            if version_dir.is_dir()
        ]

    def latest_compatible_version(self, event_id: str | None = None) -> Version | None:
        compatible_versions = [
            version
            for version in self.versions(event_id)
            if version <= SHARLY_CHESS_VERSION
        ]
        if not compatible_versions:
            return None
        return max(compatible_versions)
