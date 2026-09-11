import importlib.metadata
import os
import re
import shutil
import sys
import time
from collections import namedtuple
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from packaging.version import Version

from common.exception import SharlyChessException
from utils.file import shutil_delete_onerror
from utils.program_variables import MACOS_SUPPORT_DIR, ProgramVar


if sys.platform == 'win32':
    import winreg
else:
    # Avoid winreg mypy errors when not running on windows
    winreg: Any = {}

APP_NAME: str = 'sharly-chess'
SHARLY_CHESS_VERSION: Version = Version(importlib.metadata.version(APP_NAME))

# True when the program is running in a development environment, False if running as an EXE file.
# We also consider Flatpak as a non-development environment.
FLATPAK_ID = os.environ.get('FLATPAK_ID')
DEVEL_ENV: bool = not getattr(sys, 'frozen', False) and not FLATPAK_ID
# ``PYTEST_VERSION`` is set by pytest itself for the whole run, so this
# holds however the suite was started — ``pytest`` puts its own name in
# argv[0], but ``python -m pytest`` puts pytest's __main__.py there, and
# missing the difference means the tests run against the real data
# directory instead of tests/tmp.
TEST_ENV: bool = (
    os.getenv('TEST_ENV') == 'true'
    or os.getenv('PYTEST_VERSION') is not None
    or Path(sys.argv[0]).stem == 'pytest'
)

# True when experimental features are enabled, False otherwise.
_EXPERIMENTAL_FEATURES_ENABLED: bool = False


def enable_experimental_features(enabled: bool):
    global _EXPERIMENTAL_FEATURES_ENABLED
    _EXPERIMENTAL_FEATURES_ENABLED = enabled


def experimental_features_enabled() -> bool:
    global _EXPERIMENTAL_FEATURES_ENABLED
    return _EXPERIMENTAL_FEATURES_ENABLED


REQUEST_TIMEOUT: int = 10

RGB = namedtuple('RGB', ['red', 'green', 'blue'])

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')


def _app_base_dir() -> Path:
    """
    Return the directory that holds bundled resources (project root with pyproject.toml):
      - Dev:      repo/source tree (where pyproject.toml is)
      - Onefile:  sys._MEIPASS
      - macOS .app onedir: .../My.app/Contents/Resources
      - Linux AppImage: AppDir/usr/share (bundled resources)
      - Other frozen onedir: directory next to the executable
    """

    # PyInstaller onefile
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return Path(meipass)

    # macOS .app onedir
    try:
        exe = Path(sys.argv[0]).resolve()
        # .../My.app/Contents/MacOS/<exe>
        contents = exe.parent.parent
        if contents.name == 'Contents' and contents.parent.suffix == '.app':
            resources = contents / 'Resources'
            if resources.is_dir():
                return resources
    except Exception:
        pass

    # Other frozen (non-.app) onedir
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent

    # Dev: project / package root (where pyproject.toml is)
    return Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    if DEVEL_ENV:
        return BASE_DIR / 'dev-data'
    match sys.platform:
        case 'win32':
            doc_reg_key = (
                r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
            )
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, doc_reg_key) as key:
                documents_path = winreg.QueryValueEx(key, 'Personal')[0]
            return Path(documents_path) / 'Sharly Chess'
        case 'darwin':
            return MACOS_SUPPORT_DIR / 'data'
        case 'linux':
            # Packaged linux runs always set the data dir explicitly (--path), so
            # this default is only reached by build tooling that imports this
            # module; return a sane XDG path so that import doesn't fail.
            xdg_data_home = os.getenv('XDG_DATA_HOME')
            base = (
                Path(xdg_data_home)
                if xdg_data_home
                else Path.home() / '.local' / 'share'
            )
            return base / 'Sharly Chess'
        case _:
            raise NotImplementedError(f'{sys.platform=}')


MANUAL_PATH_USED = os.getenv('SC_MANUAL_PATH_USED') == '1'


def _default_snapshots_dir() -> Path:
    """Where the snapshots go when the user has not named a folder of their own.

    Deliberately not under the data directory. On Windows that directory is
    Documents, which OneDrive's Known Folder Move commonly synchronises, and a
    synchronised folder is a poor place to keep backups: the client dehydrates
    the files it thinks are cold — which is exactly what old backups look like
    — and a backup that needs downloading is not there at a venue with no
    network, which is when it is wanted.

    The environments that already point the data directory somewhere
    deliberate keep the snapshots beside it.
    """
    if TEST_ENV or DEVEL_ENV or MANUAL_PATH_USED or FLATPAK_ID:
        return DATA_DIR / 'snapshots'
    match sys.platform:
        case 'win32':
            local_app_data = os.getenv('LOCALAPPDATA')
            if local_app_data:
                return Path(local_app_data) / 'Sharly Chess' / 'snapshots'
        case 'darwin':
            return MACOS_SUPPORT_DIR / 'snapshots'
        case 'linux':
            xdg_state_home = os.getenv('XDG_STATE_HOME')
            base = (
                Path(xdg_state_home)
                if xdg_state_home
                else Path.home() / '.local' / 'state'
            )
            return base / 'Sharly Chess' / 'snapshots'
    return DATA_DIR / 'snapshots'


def _app_data_dir() -> Path:
    if TEST_ENV:
        # Tests run against their own tree, and each pytest-xdist worker
        # against a subtree of its own: the data directory is emptied on
        # import (below), so workers sharing one would delete the events,
        # the configuration and the session store out from under each
        # other mid-run.
        worker = os.getenv('PYTEST_XDIST_WORKER')
        return TEST_DATA_DIR / worker if worker else TEST_DATA_DIR
    if MANUAL_PATH_USED:
        return Path()
    data_dir = ProgramVar.DATA_DIR.read_path_value()
    if data_dir:
        return data_dir
    default = _default_data_dir()
    ProgramVar.DATA_DIR.write_value(str(default))
    return default


BASE_DIR = _app_base_dir()
TEST_DATA_DIR = BASE_DIR / 'tests' / 'tmp'

# Architecture of the directory containing the app's data.
DATA_DIR = _app_data_dir()
BACKUP_BASE_DIR = DATA_DIR / 'backup'  # Dev only
ARCHIVES_DIR = DATA_DIR / 'archives'
#: Default location of the event snapshots, which the configuration overrides
#: with a folder of the user's own. The snapshots share that folder with
#: whatever else is in it, so nothing here ever removes a file it did not
#: write nor a directory it did not create.
SNAPSHOTS_DIR = _default_snapshots_dir()
CUSTOM_DIR = DATA_DIR / 'custom'
CUSTOM_PLACE_CARDS_DIR = CUSTOM_DIR / 'place_cards'
DATA_SOURCES_DIR = DATA_DIR / 'data_sources'
VERSION_DATA_DIR = DATA_DIR / f'v{SHARLY_CHESS_VERSION}'
EVENTS_DIR = VERSION_DATA_DIR / 'events'
CHAMPIONSHIPS_DIR = VERSION_DATA_DIR / 'championships'
LOG_DIR = VERSION_DATA_DIR / 'logs'
TMP_DIR = VERSION_DATA_DIR / 'tmp'
CONFIG_FILE = VERSION_DATA_DIR / '.scc'
SETUP_MARKER = VERSION_DATA_DIR / '.setup'
SETUP_PENDING = 'pending'
SETUP_DONE = 'done'
# Add a log prefix in testing env to avoid concurrency
_LOG_PREFIX = f'-{time.time()}' if TEST_ENV else ''
LOG_FILE = LOG_DIR / f'{APP_NAME}{_LOG_PREFIX}.log'

# Embedded paths
WEB_TEMPLATES_DIR = BASE_DIR / 'src' / 'web' / 'templates'
EMBEDDED_PLACE_CARDS_DIR = WEB_TEMPLATES_DIR / 'admin' / 'print' / 'place_cards'
DEFAULT_FILES_DIR = BASE_DIR / 'default-files'
DEFAULT_PROGRAM_DIR = DEFAULT_FILES_DIR / 'program'
DEFAULT_DATA_DIR = DEFAULT_FILES_DIR / 'data'
LOCALE_DIR = BASE_DIR / 'locale'

# Dev paths
EXPORT_DIR = BASE_DIR / 'export'
DIST_DIR = BASE_DIR / 'dist'
BUILD_DIR = BASE_DIR / 'build'
SRC_DIR = BASE_DIR / 'src'
EXAMPLES_DIR = BASE_DIR / 'examples'
EXAMPLE_EVENTS_DIR = EXAMPLES_DIR / 'events'
EXAMPLE_PLACE_CARDS_DIR = EXAMPLES_DIR / 'place_cards'

# On Flatpak, large downloads must land in TMP_DIR (within the sandbox's writable area)
# rather than the system /tmp (a small tmpfs). On other platforms, None lets tempfile
# use the OS default so behaviour is unchanged.
TEMPFILE_DIR: Path | None = TMP_DIR if FLATPAK_ID else None

if TEST_ENV and DATA_DIR.exists() and not MANUAL_PATH_USED:
    # Clear the test data directory when the test run (not in server mode).
    # DATA_DIR rather than TEST_DATA_DIR: under pytest-xdist that is the
    # worker's own subtree, and a worker must only empty its own.
    shutil.rmtree(DATA_DIR, onerror=shutil_delete_onerror)

DATA_DIR.mkdir(parents=True, exist_ok=True)
if not os.access(DATA_DIR, os.W_OK):
    raise SharlyChessException(f'Data path [{DATA_DIR.absolute()}] is not writable.')

previous_dir = ProgramVar.PREVIOUS_DATA_DIR.read_path_value()
if previous_dir and not MANUAL_PATH_USED:
    if previous_dir.exists() and not any(DATA_DIR.iterdir()):
        # The data dir changed: move the previous content over
        try:
            # Remove the dir so it's copied at the location instead of in a subfolder
            DATA_DIR.rmdir()
            shutil.move(previous_dir, DATA_DIR)
            # Only load the logger after the move (active logger fails the move)
            from common.logger import get_logger

            logger = get_logger()
            logger.info(
                'Data directory moved from "%s" to "%s"',
                previous_dir,
                DATA_DIR,
            )
            ProgramVar.PREVIOUS_DATA_DIR.clear_value()
        except OSError as e:
            ProgramVar.DATA_DIR.write_value(str(previous_dir))
            ProgramVar.PREVIOUS_DATA_DIR.clear_value()
            raise SharlyChessException(
                'An error occurred while moving the data directory '
                f'from "{previous_dir}" to "{DATA_DIR}". '
                f'The move has been canceled.\n\nError: {e}',
            )

_VERSION_DATA_DIR_CREATED = not VERSION_DATA_DIR.exists()

for directory in (
    ARCHIVES_DIR,
    CUSTOM_DIR,
    DATA_SOURCES_DIR,
    EVENTS_DIR,
    CHAMPIONSHIPS_DIR,
    LOG_DIR,
    TMP_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)

# The directories above are created on import, before the setup has done
# anything, so their presence tells nothing about the setup having gone through:
# a first run canceled, crashed or stopped by a failed installation check leaves
# them behind with no data. A version directory created here is marked pending
# and marked done by the setup, so an interrupted run is resumed on the next
# start. A directory left by a version predating the marker is taken as done.
if _VERSION_DATA_DIR_CREATED:
    SETUP_MARKER.write_text(SETUP_PENDING)
IS_NEW_INSTALL = SETUP_MARKER.is_file() and SETUP_MARKER.read_text() == SETUP_PENDING

try:
    with open(LOG_FILE, 'a'):
        pass
except OSError as error:
    raise SharlyChessException(
        f'Log file [{LOG_FILE.absolute()}] could not be opened: {error}'
    )

if DEVEL_ENV:
    import tomllib
    from contextlib import suppress

    with suppress(KeyError):
        with open(BASE_DIR / 'pyproject.toml', 'rb') as f:
            version = tomllib.load(f)['project']['version']
        if Version(version) != SHARLY_CHESS_VERSION:
            from common.logger import get_logger

            get_logger().critical(
                'Installed %s version %s does not match defined '
                'version %s. Run `pip install -e .` then run %s again.',
                APP_NAME,
                SHARLY_CHESS_VERSION,
                version,
                APP_NAME,
            )
            raise ValueError(f'{SHARLY_CHESS_VERSION=}, {version=}')


def check_rgb_str(color: str) -> str:
    """Checks if a string is in #rrggbb format
    returns it back if it is, raises ValueError otherwise."""
    rgb: RGB | None = hexa_to_rgb(color)
    if rgb:
        return rgb_to_hexa(rgb)
    raise ValueError(f'check_rgb_str(color={color})')


def hexa_to_rgb(color: str) -> RGB | None:
    """Converts a string from #rrggbb to RGB(red, green, blue) format."""
    hex_pattern = re.compile(
        '^#?(?P<R>[0-9a-f]{2})(?P<G>[0-9a-f]{2})(?P<B>[0-9a-f]{2})$'
    )
    if matches := hex_pattern.match(color.strip().lower()):
        return RGB(
            int(matches.group('R'), 16),
            int(matches.group('G'), 16),
            int(matches.group('B'), 16),
        )
    return None


def rgb_to_hexa(rgb: RGB) -> str:
    """Converts a color in RGB(red, green, blue) format to #rrggbb format."""
    return '#' + ''.join(f'{max(0, min(255, i)):02X}' for i in rgb)


def is_valid_email(email: str) -> bool:
    return EMAIL_RE.match(email) is not None


def is_http_url(url: str) -> bool:
    try:
        r = urlparse(url)
        return r.scheme in {'http', 'https'} and bool(r.netloc)
    except ValueError:
        return False
