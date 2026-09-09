import re
import shutil
from pathlib import Path

from packaging.version import Version, InvalidVersion

from common import (
    EVENTS_DIR,
    CHAMPIONSHIPS_DIR,
    CONFIG_FILE,
    ARCHIVES_DIR,
    CUSTOM_DIR,
    DEVEL_ENV,
    DATA_DIR,
    SHARLY_CHESS_VERSION,
    IS_NEW_INSTALL,
    EXAMPLE_EVENTS_DIR,
    DEFAULT_DATA_DIR,
    FLATPAK_ID,
    SETUP_MARKER,
    SETUP_DONE,
)
from common.logger import get_logger, input_interactive_yn
from common.sharly_chess_config import SharlyChessConfig
from data.loader import EventLoader
from database.sqlite.config.config_database import ConfigDatabase
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.local_source_database import LocalSourceDatabaseManager
from plugins.manager import plugin_manager
from utils.enum import Extension
from utils.program_variables import ProgramVar

logger = get_logger()


class DataRecovery:
    RECOVERABLE_VERSIONS: list[Version] = []

    #: Whether the example events are installed on a new installation. None to
    #: ask the question, which the command line answers when it is set.
    install_example_events: bool | None = None

    @classmethod
    def setup(cls):
        """Setup the Data recovery class. Recovers a version if necessary."""
        recovered = False

        stored_version: Version | None = None
        if stored_val := ProgramVar.VERSION.read_value():
            stored_version = Version(stored_val)
        if IS_NEW_INSTALL:
            if stored_version and stored_version != SHARLY_CHESS_VERSION:
                # Version has been updated from a previous version --> recover
                recovered = cls._recover_version(stored_version)

            # The legacy variables are only cleared once the data they point to
            # has been recovered, so a version still holding them together with
            # an empty events directory has nothing to lose and a version to
            # recover, whatever the version recovered just above brought.
            legacy_pending = bool(
                ProgramVar.LEGACY_VERSION_DIR.read_value()
            ) and not any(EVENTS_DIR.iterdir())
            if not recovered or legacy_pending:
                legacy_version_val = ProgramVar.LEGACY_VERSION.read_value()
                legacy_dir_val = ProgramVar.LEGACY_VERSION_DIR.read_value()
                if legacy_dir_val and legacy_version_val:
                    stored_dir = Path(legacy_dir_val)
                    legacy_dir = cls._find_legacy_data_dir(stored_dir)
                    if legacy_dir:
                        cls._recover_legacy_version(
                            Version(legacy_version_val), legacy_dir
                        )
                        recovered = True
                        ProgramVar.LEGACY_VERSION.clear_value()
                        ProgramVar.LEGACY_VERSION_DIR.clear_value()
                    else:
                        logger.warning(
                            'No data to recover found from directory [%s] (canceled)',
                            stored_dir.absolute(),
                        )
                elif FLATPAK_ID:
                    # Flatpak can update directly to version 5 without
                    # passing by versions setting the legacy variables.
                    # Identify and recover the latest version in this case.
                    versions = cls._get_installed_versions()
                    if versions:
                        version = versions[0]
                        cls._recover_legacy_version(
                            version, cls._get_version_dir(version)
                        )

            # Copy all the default data files
            for file in DEFAULT_DATA_DIR.glob('**/*'):
                if not file.is_file():
                    continue
                dst = DATA_DIR / file.relative_to(DEFAULT_DATA_DIR)
                dst.parent.mkdir(exist_ok=True)
                shutil.copy(file, dst)

        if stored_version != SHARLY_CHESS_VERSION:
            ProgramVar.VERSION.write_value(str(SHARLY_CHESS_VERSION))

        if DEVEL_ENV and IS_NEW_INSTALL and not recovered:
            if (Path() / 'events' / '.scc').exists():
                cls._recover_legacy_version(Version('4'), Path())
            else:
                install_example_events = cls.install_example_events
                if install_example_events is None:
                    install_example_events = input_interactive_yn(
                        title='Setup',
                        question='Do you want to install example event databases',
                        yes_is_default=True,
                    )
                if install_example_events:
                    for file in EXAMPLE_EVENTS_DIR.glob(f'*.{Extension.EVENT_DB}'):
                        shutil.copy(file, EVENTS_DIR / file.name)

        cls._recover_legacy_event_db()
        cls._clean_unsupported_version()
        SETUP_MARKER.write_text(SETUP_DONE)

    @staticmethod
    def _get_version_dir(version: Version) -> Path:
        if FLATPAK_ID and version.major < 5:
            return DATA_DIR / f'sharly-chess-{version}'
        return DATA_DIR / f'v{version}'

    @staticmethod
    def _get_installed_versions() -> list[Version]:
        versions: list[Version] = []
        for version_dir in DATA_DIR.glob('*'):
            if not version_dir.is_dir() or not re.match(
                r'^v(\d+\.\d+\.\d+).*$', version_dir.name
            ):
                continue
            try:
                version_str = version_dir.name[1:]
                version = Version(version_str)
                if version.major < 5:
                    logger.warning(
                        'version dir [%s] is a legacy version (ignored)',
                        version_dir.absolute(),
                    )
                elif version_str != str(version):
                    # Only reversible version names are taken into account
                    raise InvalidVersion()
                elif version != SHARLY_CHESS_VERSION:
                    versions.append(version)
            except InvalidVersion:
                logger.warning('invalid version dir [%s]', version_dir.absolute())
        if FLATPAK_ID:
            for version_dir in DATA_DIR.glob('*'):
                if matches := re.match(
                    r'^sharly-chess-(\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?)$',
                    version_dir.name,
                ):
                    versions.append(Version(matches.group(1)))

        return sorted(versions, reverse=True)

    @classmethod
    def _clean_unsupported_version(cls):
        """supported versions are 2 minor releases prior to the current version.
        All the data of versions prior to that can be deleted.
        At least one previous version should be kept."""
        versions = cls._get_installed_versions()
        current = SHARLY_CHESS_VERSION
        max_previous = next(
            (version for version in versions if version < current),
            None,
        )
        if not max_previous:
            return

        def get_min_version(major: int, minor: int) -> Version:
            return Version(f'{major}.{minor}.0.dev0')

        min_version = get_min_version(current.major, max(current.minor - 2, 0))
        if current.minor < 2:
            last_major_minor = next(
                (
                    version.minor
                    for version in versions
                    if version.major == current.major - 1
                ),
                None,
            )
            if last_major_minor is not None:
                sup_minor_count = max(2 - current.minor, 0)
                last_sup_minor = min(last_major_minor - sup_minor_count, 0)
                min_version = get_min_version(current.major - 1, last_sup_minor)
        if max_previous > min_version:
            min_version = max_previous

        for version in versions:
            if version >= min_version:
                continue
            shutil.rmtree(cls._get_version_dir(version), ignore_errors=True)
            logger.info('Data of version [%s] removed (no longer supported)', version)

    @classmethod
    def _recover_version(cls, version: Version) -> bool:
        version_dir = cls._get_version_dir(version)
        if not version_dir.exists():
            return False
        logger.info('Recovering version [%s]...', version)
        cls._recover_config_file(version_dir / CONFIG_FILE.name)
        for file in (version_dir / EVENTS_DIR.name).glob('*'):
            if not file.is_file():
                continue
            shutil.copy(file, EVENTS_DIR / file.name)
            logger.debug('- Event [%s] recovered', file.stem)
        old_championship_dir = version_dir / CHAMPIONSHIPS_DIR.name
        if old_championship_dir.is_dir():
            CHAMPIONSHIPS_DIR.mkdir(parents=True, exist_ok=True)
            for file in old_championship_dir.glob('*'):
                if not file.is_file():
                    continue
                shutil.copy(file, CHAMPIONSHIPS_DIR / file.name)
                logger.debug('- Championship [%s] recovered', file.stem)
        return True

    @classmethod
    def _recover_config_file(cls, old_config_file: Path):
        from gui.server_gui_toga import SharlyChessServerToga

        if not old_config_file.is_file():
            return
        logger.info('Recovering configuration file...')
        # copy the configuration database to its new destination
        shutil.copy(old_config_file, CONFIG_FILE)
        ConfigDatabase.setup()
        config = SharlyChessConfig()
        config.load_and_set_env()
        if SharlyChessServerToga.instance is not None:
            logger.debug('Applying recovered configuration to the Toga app...')
            SharlyChessServerToga.instance.update_from_sharly_chess_config()
        plugin_manager.reload_register()

    # -------------------------------------------------------------------------
    # Legacy
    # -------------------------------------------------------------------------

    @staticmethod
    def _find_legacy_data_dir(stored_dir: Path) -> Path | None:
        """Resolve the data directory of a legacy version from the stored path.

        Versions up to 4.2.8 stored the directory holding the bundled resources
        instead of the working directory holding the data. Under PyInstaller 6
        the former is `_internal` on Windows and `<name>.app/Contents/Frameworks`
        on macOS, while the data respectively sits one level up and beside the
        application bundle. Return None when no candidate holds any data.
        """
        candidates = [stored_dir, stored_dir.parent]
        for parent in stored_dir.parents:
            if parent.suffix == '.app':
                candidates.append(parent.parent)
                break
        for candidate in candidates:
            if (candidate / EVENTS_DIR.name).is_dir():
                if candidate != stored_dir:
                    logger.info(
                        'Data of the version to recover found at [%s] instead of [%s]',
                        candidate.absolute(),
                        stored_dir.absolute(),
                    )
                return candidate
        return None

    @staticmethod
    def _get_legacy_event_files(version_dir: Path) -> list[Path]:
        events_dir = version_dir / EVENTS_DIR.name
        return list(events_dir.glob(f'*.{Extension.EVENT_DB}')) + list(
            events_dir.glob(f'*.{Extension.LEGACY_EVENT_DB}')
        )

    @classmethod
    def _recover_legacy_version(cls, version: Version, version_dir: Path):
        """Recover all the data of a previous version (configuration, events, Papi files and customization files)."""

        logger.info('Recovering version %s at [%s]...', version, version_dir)
        old_events_dir = version_dir / EVENTS_DIR.name
        cls._recover_config_file(old_events_dir / CONFIG_FILE.name)
        logger.info('Recovering events...')
        for file in cls._get_legacy_event_files(version_dir):
            event_uniq_id: str = file.stem
            event_database = EventDatabase(event_uniq_id)
            # copy the event database to its new destination
            shutil.copy(file, event_database.file)
            logger.debug('- Event [%s] recovered', event_uniq_id)
        if version < Version('3.0.0'):
            default_papi_dir = 'papi'
            previous_default_papi_path = version_dir / default_papi_dir
            default_papi_path = Path(default_papi_dir)
            default_papi_path.mkdir(parents=True, exist_ok=True)
            for file in previous_default_papi_path.glob('**/*.papi'):
                destination_file = default_papi_path / file.relative_to(
                    previous_default_papi_path
                )
                destination_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(file, destination_file)
        logger.info('Recovering data sources...')
        for database in LocalSourceDatabaseManager().objects():
            min_version = database.legacy_min_recovery_version
            if not min_version or version < min_version:
                continue
            src_file = version_dir / database.legacy_file_path()
            if not src_file.is_file():
                continue
            dst_file = database.file_path()
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src_file, dst_file)
            logger.debug('- Data source [%s] recovered', database.id)
        logger.info('Recovering custom files...')
        old_custom_dir: Path = version_dir / 'custom'
        if old_custom_dir.is_dir():
            for src_file in old_custom_dir.glob('**/*'):
                if not src_file.is_file():
                    continue
                relative_file = src_file.relative_to(old_custom_dir)
                dst_file = CUSTOM_DIR / relative_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_file, dst_file)
                logger.debug('- Custom file [%s] recovered', relative_file)
        logger.info('Recovering archived events...')
        old_archives_dir = old_events_dir / ARCHIVES_DIR.name
        if old_archives_dir.is_dir():
            for src_file in old_archives_dir.glob(f'*.{Extension.ARCHIVE}'):
                if not src_file.is_file():
                    continue
                relative_file = src_file.relative_to(old_archives_dir)
                dst_file = ARCHIVES_DIR / relative_file
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src_file, dst_file)
                logger.debug('- Archive [%s] recovered', relative_file)

    @staticmethod
    def _recover_legacy_event_db():
        files: list[Path] = list(EVENTS_DIR.glob(f'*.{Extension.LEGACY_EVENT_DB}'))
        loader = EventLoader()
        for file in files:
            event_uniq_id = loader.get_unused_event_uniq_id(file.stem)
            logger.info('Recovering event [%s]...', event_uniq_id)
            # rename the old event database with the new extension
            file.rename(EventDatabase(event_uniq_id).file)
            # now load the new database
            EventLoader().load_event(event_uniq_id)
