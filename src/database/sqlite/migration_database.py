from abc import abstractmethod, ABC
from functools import cached_property
from sqlite3 import OperationalError
from typing import Self, TYPE_CHECKING, Any

from packaging.version import Version

from common import SHARLY_CHESS_VERSION
from common.exception import SharlyChessException, DatabaseInaccessibleException
from database.sqlite.sqlite_database import SQLiteDatabase

if TYPE_CHECKING:
    from database.sqlite.migration import DatabaseMigrationManager, PostUpgradeTask


class MigrationDatabase(SQLiteDatabase, ABC):
    """Abstract class representing databases which
    can handle one or more timelines of migrations."""

    @property
    def migration_instance_kwargs(self) -> dict[str, Any]:
        """Get the kwargs required to initiate a new instance of the class,
        used in the context of migrating the database."""
        return {}

    def get_migration_instance(
        self, write: bool = False, enable_foreign_keys: bool = True
    ) -> Self:
        kwargs: dict[str, Any] = self.migration_instance_kwargs | {
            'write': write,
            'enable_foreign_keys': enable_foreign_keys,
        }
        return self.__class__(**kwargs)

    @cached_property
    @abstractmethod
    def migration_managers(self) -> list['DatabaseMigrationManager']:
        """Managers to use for migrations.
        The order determines which migration timeline is migrated first."""

    @property
    @abstractmethod
    def migration_by_legacy_version(self) -> dict[Version, str]:
        """Name of migration by version
        according to the legacy migration system."""

    @property
    @abstractmethod
    def log_prefix(self) -> str:
        """Prefix identifying the database in the logs."""

    # ---------------------------------------------------------------------------------
    # Metadata
    # ---------------------------------------------------------------------------------

    def create_metadata_table(self):
        self.execute(
            'CREATE TABLE IF NOT EXISTS `metadata` ('
            '   `version` TEXT NOT NULL,'
            "   `migration` TEXT NOT NULL DEFAULT 'm000_no_migration'"
            ')'
        )
        self.execute(
            'INSERT INTO `metadata` (`version`) VALUES (?)',
            (str(SHARLY_CHESS_VERSION),),
        )

    def is_metadata_table_installed(self) -> bool:
        try:
            self.execute('SELECT 1 FROM `metadata`')
            return '1' in self.fetchone()
        except OperationalError:
            return False

    def get_migration(self) -> str:
        self.execute('SELECT `migration` FROM `metadata`')
        return self.fetchone()['migration']

    def set_migration(self, migration: str):
        self.execute('UPDATE `metadata` SET `migration` = ?', (migration,))

    def get_version(self) -> Version:
        self.execute('SELECT `version` FROM `metadata`')
        return Version(self.fetchone()['version'])

    def set_version(self, version: Version):
        self.execute('UPDATE `metadata` SET `version` = ?', (str(version),))

    def get_migration_from_legacy_version(self) -> str | None:
        try:
            self.execute('SELECT `version` FROM `info`')
        except OperationalError:
            return None
        database_version = Version(self.fetchone()['version'])
        ordered_versions = sorted(self.migration_by_legacy_version.keys())
        migration_version = next(
            (
                version
                for version in reversed(ordered_versions)
                if version <= database_version
            ),
            None,
        )
        if migration_version is None:
            raise SharlyChessException(
                f'Database [{self.file.name}] - Unsupported version '
                f'[{database_version}], impossible to migrate '
                f'(min supported version: {ordered_versions[0]})'
            )
        return self.migration_by_legacy_version[migration_version]

    # ---------------------------------------------------------------------------------
    # Database management
    # ---------------------------------------------------------------------------------

    def check_status(self) -> bool:
        """Checks if the database can be used
        in the current version the application.
        Returns True if it can, False if it needs an upgrade.
        If it can't be upgraded, raises a *SharlyChessException*."""
        with self.get_migration_instance() as database:
            return all(
                manager.check_status(database) for manager in self.migration_managers
            )

    def upgrade(self):
        """Upgrades the database to the latest version.
        This may change the structure of the database."""
        post_upgrade_tasks: list[PostUpgradeTask] = []
        for manager in self.migration_managers:
            manager.migrate()
            post_upgrade_tasks += manager.post_upgrade_tasks

        for task in post_upgrade_tasks:
            task.execute()

    def create(self):
        """Create a database by running the migrations from scratch.
        The file associated to this database must not already exist.
        """
        if self.exists():
            raise SharlyChessException(
                f'The database can not be created because the '
                f'file [{self.file.resolve()}] already exists.'
            )

        self._create()
        for manager in self.migration_managers:
            manager.migrate()

    def __enter__(self) -> Self:
        if not self.exists():
            raise SharlyChessException(
                'Database could not be opened because file '
                f'[{self.file.resolve()}] does not exist.'
            )
        try:
            return super().__enter__()
        except OperationalError as e:
            raise DatabaseInaccessibleException(
                'Database could not be opened, the file '
                f'[{self.file.resolve()}] exists but is not accessible: {e}'
            ) from e
