import atexit
import base64
import json
import shutil
import tempfile
import threading
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from math import floor
from pathlib import Path
from sqlite3 import connect, DatabaseError
from time import time
from typing import override

from packaging.version import Version
from requests import Response, get

from common import SharlyChessException, DEVEL_ENV, TEMPFILE_DIR, DATA_SOURCES_DIR
from common.i18n import _, set_locale
from common.logger import get_logger
from common.network import NetworkMonitor
from common.sharly_chess_config import SharlyChessConfig
from database.sqlite.config.config_database import ConfigDatabase
from database.sqlite.config.config_store import StoredLocalSourceDatabase
from database.sqlite.event.event_store import StoredPlayer
from database.sqlite.local_source_database.actions import (
    OutdatedAction,
    NotifOutdatedAction,
)
from database.sqlite.local_source_database.aes_ecb import AesEcb
from database.sqlite.local_source_database.delays import (
    OutdatedDelay,
    DisabledOutdatedDelay,
)
from database.sqlite.sqlite_database import SQLiteDatabase
from utils.entity import IdentifiableEntity
from utils.enum import Extension
from web.channels import channels_plugin

logger = get_logger()


class FileCredentials:
    def __init__(
        self,
        file: Path,
    ):
        """Reads credentials from the given file, raises SharlyChessException on error."""
        self.password: str
        try:
            with open(file, 'r') as f:
                (self.password,) = json.loads(
                    base64.b64decode(f.read().encode('ascii')).decode('ascii')
                )
        except FileNotFoundError as e:
            if DEVEL_ENV:
                raise SharlyChessException(
                    f'Could not read file credentials [{file}] ({e}), '
                    'please run generate_xxx_credentials.py.'
                ) from e
            else:
                raise SharlyChessException('Could not read file credentials.') from None

    @staticmethod
    def dump(
        credentials_file: Path,
        password: str,
    ):
        """Dumps credentials to the given file.
        The credentials can be read by `creds = FileCredentials(file)`."""
        credentials_file.parent.mkdir(exist_ok=True, parents=True)
        with open(credentials_file, 'w') as f:
            f.write(
                base64.b64encode(json.dumps((password,)).encode('ascii')).decode(
                    'ascii'
                )
            )


class DatabaseLoaderProgress:
    """A utility class to display the progress of database operations."""

    def __init__(
        self,
        log_prefix: str,
        total_count: int,
        delay: int = 10,
    ):
        self.log_prefix = log_prefix
        self.total_count = total_count
        assert self.total_count > 0
        self.delay: int = delay
        assert self.delay > 0
        self.start_time: float = time()
        self.last_message_time: float = self.start_time
        self.last_message_count: int = 0

    def log(
        self,
        count: int,
    ):
        now: float = time()
        if now - self.last_message_time < self.delay:
            return
        remaining_count: int = self.total_count - count
        items_per_second: float = (
            (count - self.last_message_count) / (now - self.last_message_time)
            + count / (now - self.start_time)
        ) / 2
        eta: int = floor(remaining_count / items_per_second)
        logger.info(
            self.log_prefix + '%d%% ETA: %02d:%02d',
            floor(count / self.total_count * 100),
            eta // 60,
            eta % 60,
        )
        self.last_message_count = count
        self.last_message_time = now


class LocalSourceDatabase(SQLiteDatabase, IdentifiableEntity, ABC):
    """Represents the local databases used as data sources.
    These databases are downloaded and stored locally as SQLite databases.
    They can be periodically updated, or notify the user when outdated."""

    UPDATE_TIMEOUT = 10

    is_updating: bool = False
    update_status: bool | None = None
    max_update_time: datetime | None = None
    _stored_source_database: StoredLocalSourceDatabase | None = None

    def __init__(self, write: bool = False):
        super().__init__(self.file_path(), write)
        self.stop_event = threading.Event()
        self.outdated_warning: bool = False
        if self.max_update_time and datetime.now() > self.max_update_time:
            logger.error(self.log_prefix + 'Update failed (timeout).')
            self.stop_update(False)

    @property
    def stored_source_database(self) -> StoredLocalSourceDatabase:
        cls = self.__class__
        if cls._stored_source_database is None:
            self._load_stored_source_database()
        assert cls._stored_source_database is not None
        return cls._stored_source_database

    def _load_stored_source_database(self):
        cls = self.__class__
        with ConfigDatabase() as database:
            cls._stored_source_database = database.load_stored_local_source_database(
                self.id
            )
        if not cls._stored_source_database:
            self.file.unlink(missing_ok=True)
            self.update_stored_source_database(
                self.default_stored_database, exists=False
            )

    @classmethod
    def update_stored_source_database(
        cls,
        stored_source_database: StoredLocalSourceDatabase,
        exists: bool = True,
    ):
        with ConfigDatabase(write=True) as database:
            if exists:
                database.update_stored_local_source_database(stored_source_database)
            else:
                database.insert_stored_local_source_database(stored_source_database)
        cls._stored_source_database = stored_source_database

    @staticmethod
    @abstractmethod
    def version() -> Version:
        """The version of the database. Change to force an update."""
        # TODO (Molrn) Add matching GH releases versioning
        # to allow source structure changes (if ever required)

    @classmethod
    def file_path(cls):
        id_ = cls.static_id()
        return DATA_SOURCES_DIR / id_ / f'{id_}-{cls.version()}.{Extension.SOURCE_DB}'

    @staticmethod
    def _legacy_dir() -> Path:
        """LEGACY: Dir of the SQlite file in versions < 5."""
        return Path('tmp')

    @classmethod
    def legacy_file_path(cls) -> Path:
        """LEGACY: Path to the SQlite file in versions < 5."""
        return cls._legacy_dir() / f'{cls.static_id()}.db'

    @property
    def legacy_min_recovery_version(self) -> Version | None:
        """LEGACY: Only used to recover < 5 versions.
        Increase the `version` property instead.
        If < version 5 databases can't be recovered, set to None."""
        return None

    @property
    def _schema_file_path(self) -> Path:
        """Path to the SQL file describing the schema of the database."""
        # Default implementation - subclasses should override this if they don't use external generation
        raise NotImplementedError(
            'Subclass must implement _schema_file_path if _use_external_generator returns False'
        )

    @property
    @abstractmethod
    def _source_file_name(self) -> str:
        """Name of the file containing the sources."""

    @abstractmethod
    def _download_source_file(self, source_file_dir: Path) -> bool:
        """Download the source file to *source_file_dir*.
        Returns True if it succeeds and False if it fails."""

    def _use_external_generator(self) -> bool:
        """Determines of the database in generated by an external tool.
        If not, the database structure will be created then populated."""
        # Default implementation - subclasses can override this
        return False

    def _generate_from_source_file(
        self, source_file_path: Path, tmp_file: Path
    ) -> bool:
        """Creates the database at *tmp_file* from *source_file_path*."""
        # Default implementation - subclasses should override this if they use external generation
        raise NotImplementedError(
            'Subclass must implement _generate_from_source_file if _use_external_generator returns True'
        )

    def _populate_from_source_file(
        self, source_file_path: Path, database: SQLiteDatabase
    ) -> bool:
        """Populate the database from the source file at *source_file_path*.
        Database matches schema described at *schema_file_path*."""
        # Default implementation - subclasses should override this if they don't use external generation
        raise NotImplementedError(
            'Subclass must implement _populate_from_source_file if _use_external_generator returns False'
        )

    def _post_generation(self, tmp_file: Path) -> bool:
        """Perform post operations after the database has been populated."""
        # Default implementation - subclasses should override this if needed
        return True

    @classmethod
    @abstractmethod
    def _create_indexes(cls, database: SQLiteDatabase):
        """Create the indexes for the databases."""

    @property
    def outdate_delay(self) -> OutdatedDelay:
        from database.sqlite.local_source_database import OutdatedDelayManager

        return OutdatedDelayManager().get_object(
            self.stored_source_database.outdate_delay
        )

    @property
    def outdate_action(self) -> OutdatedAction:
        from database.sqlite.local_source_database import OutdatedActionManager

        return OutdatedActionManager().get_object(
            self.stored_source_database.outdate_action
        )

    @property
    def updated_at_timestamp(self) -> float | None:
        return self.stored_source_database.updated_at

    @property
    def updated_at(self) -> datetime | None:
        if self.updated_at_timestamp:
            return datetime.fromtimestamp(self.updated_at_timestamp)
        return None

    @property
    def is_outdated(self) -> bool:
        if not self.updated_at:
            return False
        return self.outdate_delay.is_expired(self.updated_at)

    @property
    def default_stored_database(self) -> StoredLocalSourceDatabase:
        return StoredLocalSourceDatabase(
            name=self.id,
            outdate_delay=DisabledOutdatedDelay.static_id(),
            outdate_action=NotifOutdatedAction.static_id(),
        )

    @property
    def log_prefix(self) -> str:
        return f'Database [{self.name}] - '

    @classmethod
    def publish_database_status_updated(cls):
        # The auto-update can start before the channels plugin is initialized,
        # so we check if it exists before trying to publish.
        if channels_plugin and channels_plugin._pub_queue is not None:
            channels_plugin.publish(
                {
                    'event': 'database-status-updated',
                    'data': '',
                },
                ['ws'],
            )
            channels_plugin.publish(
                {
                    'event': f'database-status-updated|{cls.static_id()}',
                    'data': '',
                },
                ['ws'],
            )

    def on_outdated(self):
        self.outdate_action.on_outdated(self)
        self.publish_database_status_updated()

    @property
    def updated_at_str(self) -> str:
        if self.is_updating:
            return _('Ongoing')
        if not self.updated_at:
            return ''

        days_since_update = (datetime.now() - self.updated_at).days
        match days_since_update:
            case 0:
                return _('Today')
            case 1:
                return _('Yesterday')
            case _:
                return _('{days} days ago').format(days=days_since_update)

    def stop_update(self, status: bool) -> None:
        cls = self.__class__
        cls.is_updating = False
        cls.update_status = status
        cls.max_update_time = None
        logger.debug(self.log_prefix + f'Update stopped with status {int(status)}')
        # Only push the SSE event if the server is connected, otherwise we enter a loop where the client gets the SSE event,
        # re-requests the updated badge, fails dues to the lack of internet, and so on.
        if NetworkMonitor.connected():
            self.publish_database_status_updated()

    @override
    def delete(self):
        super().delete()
        self.update_stored_source_database(self.default_stored_database)
        self.publish_database_status_updated()

    def check(self) -> bool:
        """Checks if the database exists and is up-to-date.
        If it exists and is outdated, execute the 'on_outdated' process.
        Returns True if the database is available after the call."""
        if not self.exists():
            if self.updated_at:
                logger.error(
                    'Database [%s] unexpectedly not found at path [%s].',
                    self.name,
                    self.file,
                )
                self.delete()
            return False
        if self.is_outdated:
            self.outdate_action.on_outdated(self)
        return True

    def update(self):
        """Start a thread updating the database."""
        update_thread = threading.Thread(target=self._update, daemon=True)
        update_thread.start()
        atexit.register(self._stop_background_thread, update_thread)

    def _stop_background_thread(self, thread: threading.Thread):
        self.stop_event.set()
        thread.join()

    def _update(self):
        """Update the source database:
        1. Download the source file
        2. Create a temp database
        3. Populate the temp database from the source file
        4. Copy the temp file to the correct file location"""

        # Set the locale (called in a new thread)
        set_locale(SharlyChessConfig().locale)

        self.__class__.is_updating = True
        self.__class__.max_update_time = datetime.now() + timedelta(
            minutes=self.UPDATE_TIMEOUT
        )

        if not NetworkMonitor.connected():
            logger.warning(self.log_prefix + 'Not connected, impossible to update.')
            return self.stop_update(False)
        self.publish_database_status_updated()
        with tempfile.TemporaryDirectory(dir=TEMPFILE_DIR) as tmpdir:
            tmp_dir: Path = Path(tmpdir)
            logger.info(self.log_prefix + 'Downloading source file…')
            if not self._download_source_file(tmp_dir):
                return self.stop_update(False)
            if self.stop_event.is_set():
                return self.stop_update(False)
            logger.info(self.log_prefix + 'Storing data…')
            tmp_file = tmp_dir / 'db.tmp'
            new_database = SQLiteDatabase(tmp_file, write=True)
            source_file_path: Path = tmp_dir / self._source_file_name

            try:
                success: bool
                if self._use_external_generator():
                    success = self._generate_from_source_file(
                        source_file_path, tmp_file
                    )
                else:
                    with open(self._schema_file_path, encoding='utf-8') as file:
                        new_database._create(file.read())
                    success = self._populate_from_source_file(
                        source_file_path, new_database
                    )
                if not success:
                    return self.stop_update(False)
            except (DatabaseError, SharlyChessException) as ex:
                logger.exception(
                    self.log_prefix + 'Error while creating the database: %s.', ex
                )
                return self.stop_update(False)

            # Validate that the database file is actually a SQLite database before creating indexes
            try:
                # Test if we can open the database
                test_conn = connect(tmp_file)
                test_conn.execute('SELECT 1')  # Simple test query
                test_conn.close()
            except DatabaseError as e:
                logger.exception(
                    self.log_prefix
                    + 'Generated database file is not a valid SQLite database: %s.',
                    e,
                )
                self.file.unlink(missing_ok=True)
                return self.stop_update(False)

            try:
                if not self._post_generation(tmp_file):
                    return self.stop_update(False)
            except (DatabaseError, SharlyChessException) as e:
                logger.exception(
                    self.log_prefix + 'Could not perform post operations: %s.',
                    e,
                )
                return self.stop_update(False)

            try:
                logger.debug(self.log_prefix + 'Creating indices…')
                with SQLiteDatabase(tmp_file, True) as database:
                    self._create_indexes(database)
            except DatabaseError as e:
                logger.exception(
                    self.log_prefix + 'Could not create database indices: %s.',
                    e,
                )
                return self.stop_update(False)

            try:
                # Copy the new database to its proper location
                self.file.unlink(missing_ok=True)
                self.file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(tmp_file, self.file)
                logger.debug(self.log_prefix + f'file copied to [{self.file}].')
            except OSError as e:
                logger.exception(
                    self.log_prefix
                    + 'Could not copy generated database file to [%s]: %s.',
                    self.file,
                    e,
                )
                return self.stop_update(False)

        self.stored_source_database.updated_at = time()
        self.update_stored_source_database(self.stored_source_database)
        logger.info(self.log_prefix + 'Database successfully updated.')
        return self.stop_update(True)


class GitHubLocalSourceDatabase(LocalSourceDatabase, ABC):
    @classmethod
    @abstractmethod
    def credentials_file(cls) -> Path:
        pass

    @classmethod
    def dump_credentials(
        cls,
        password: str,
    ):
        FileCredentials.dump(
            cls.credentials_file(),
            password,
        )

    @classmethod
    @abstractmethod
    def github_tag(cls) -> str:
        pass

    def _download_from_github(
        self,
        source_file_dir: Path,
        remote_filename: str,
    ) -> bool:
        target: Path = source_file_dir / remote_filename
        url: str = f'https://github.com/Sharly-Chess/databases/releases/download/{self.github_tag()}/{remote_filename}'
        logger.info(self.log_prefix + 'Downloading [%s]...', url)
        try:
            response: Response = get(url, allow_redirects=True, timeout=60, stream=True)
            if response.status_code != 200:
                logger.error(
                    self.log_prefix + 'Could not download [%s], error code [%d].',
                    url,
                    response.status_code,
                )
                return False
            total = int(response.headers.get('content-length', 0))
            logger.info(self.log_prefix + 'Receiving %.1f MB...', total / 1_048_576)
            received = 0
            with open(target, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    received += len(chunk)
                    logger.debug(
                        self.log_prefix + 'Downloaded %d / %d bytes.', received, total
                    )
        except ConnectionError as ex:
            logger.exception(
                self.log_prefix + 'Could not download [%s]: %s.',
                url,
                ex,
            )
            return False
        logger.info(
            self.log_prefix + 'Download complete (%.1f MB).', received / 1_048_576
        )
        return True

    def _download_zip_source_file(self, source_file_dir: Path) -> bool:
        zip_filename = self._source_file_name.replace('.db', '.zip')
        if not self._download_from_github(source_file_dir, zip_filename):
            return False
        zip_target: Path = source_file_dir / zip_filename
        credentials: FileCredentials = FileCredentials(self.credentials_file())
        logger.info(self.log_prefix + 'Extracting zip archive...')
        try:
            with zipfile.ZipFile(zip_target, 'r') as zf:
                zf.extractall(source_file_dir, pwd=credentials.password.encode())
        except Exception as ex:
            logger.exception(self.log_prefix + 'Could not extract zip archive: %s.', ex)
            return False
        finally:
            zip_target.unlink(missing_ok=True)
        logger.info(self.log_prefix + 'Extraction complete.')
        return True

    def _download_enc_source_file(self, source_file_dir: Path) -> bool:
        enc_filename = self._source_file_name.replace('.db', '.enc')
        if not self._download_from_github(source_file_dir, enc_filename):
            return False
        enc_target: Path = source_file_dir / enc_filename
        credentials: FileCredentials = FileCredentials(self.credentials_file())
        logger.info(self.log_prefix + 'Decrypting archive...')
        try:
            AesEcb.decrypt_file(
                enc_target,
                source_file_dir / self._source_file_name,
                credentials.password,
            )
        except Exception as ex:
            logger.exception(self.log_prefix + 'Could not decrypt archive: %s.', ex)
            return False
        finally:
            enc_target.unlink(missing_ok=True)
        logger.info(self.log_prefix + 'Decryption complete.')
        return True

    def _use_external_generator(self):
        return True

    def _generate_from_source_file(
        self, source_file_path: Path, tmp_file: Path
    ) -> bool:
        logger.info(self.log_prefix + 'Copying downloaded database to temp file...')
        shutil.copy(source_file_path, tmp_file)
        logger.info(self.log_prefix + 'Copy done.')
        return True

    @classmethod
    def _create_indexes(cls, database: SQLiteDatabase):
        # Indices are created by GitHub.
        pass


class LocalSourcePlayerDatabase(GitHubLocalSourceDatabase):
    """Represents a local database that provides player search functionality."""

    @abstractmethod
    def search_player(
        self,
        string: str,
        federation: str,
        page: int = 0,
        limit: int | None = None,
        filters: dict | None = None,
    ) -> list[StoredPlayer]:
        """Search a player in the database.
        Returns maximum *limit* results (no limit if *limit* is None)."""
