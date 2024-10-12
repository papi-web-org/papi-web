import logging
import re
import socket
from logging import Logger
from pathlib import Path

import jinja2
import litestar
import pyodbc
import uvicorn
from packaging.version import Version

from common.config_reader import ConfigReader
from common.logger import get_logger, configure_logger
from common.singleton import Singleton

logger: Logger = get_logger()

TMP_DIR: Path = Path('tmp')

CONFIG_FILE: Path = Path('papi-web.ini')

DEFAULT_LOG_LEVEL: int = logging.INFO
DEFAULT_WEB_HOST: str = '0.0.0.0'
DEFAULT_WEB_PORT: int = 8080
DEFAULT_WEB_LAUNCH_BROWSER: bool = True
DEFAULT_FFE_UPLOAD_DELAY: int = 180
MIN_FFE_UPLOAD_DELAY: int = 60


class PapiWebConfig(metaclass=Singleton):
    """The configuration for the application.
    Only 5 properties can be configured:
        1. The logging level
        2. The web host IP
        3. The web port
        4. Whether a browser window opens
        5. The delay between FFE uploads."""

    def __init__(self):
        self.reader = ConfigReader(CONFIG_FILE)
        self.__log_level: int | None = None
        self.__web_host: str | None = None
        self.__web_port: int | None = None
        self.__web_launch_browser: bool | None = None
        self.__ffe_upload_delay: int | None = None
        self.__local_ip: str | None = None
        self.__lan_ip: str | None = None
        self.__log_levels: dict[int, str] = {
            logging.DEBUG: 'DEBUG',
            logging.INFO: 'INFO',
            logging.WARNING: 'WARNING',
            logging.ERROR: 'ERROR',
        }
        if not self.reader.errors and not self.reader.warnings:
            section_key = 'logging'
            try:
                options = self.reader[section_key]
                key = 'level'
                try:
                    level = options[key]
                    try:
                        self.__log_level = [k for k, v in self.__log_levels.items() if v == level][0]
                    except IndexError:
                        self.reader.add_warning(f'niveau de log invalide [{level}]', section_key, key)
                except (TypeError, KeyError):
                    self.reader.add_warning(
                        f'option absente, par défaut [{self.__log_levels[DEFAULT_LOG_LEVEL]}]', section_key, key)
            except KeyError:
                self.reader.add_warning('rubrique introuvable', section_key)
            section_key = 'web'
            if section_key not in self.reader:
                self.reader.add_warning('rubrique introuvable', section_key)
            else:
                web_section = self.reader[section_key]
                key = 'host'
                if key not in web_section:
                    self.reader.add_warning('option absente', section_key, key)
                else:
                    self.__web_host = self.reader.get(section_key, key)
                    matches = re.match(r'^(\d+)\.(\d+)\.(\d+)\.(\d+)$', self.__web_host)
                    if matches:
                        for i in range(4):
                            if int(matches.group(i + 1)) > 255:
                                self.__web_host = None
                    else:
                        self.__web_host = None
                    if self.web_host is None:
                        self.reader.add_warning(
                            f'configuration d\'hôte invalide [{self.reader.get(section_key, key)}], par défaut '
                            f'[{DEFAULT_WEB_HOST}]', section_key, key)
                key = 'port'
                if key not in web_section:
                    self.reader.add_warning(f'option absente, par défaut [{DEFAULT_WEB_PORT}]', section_key, key)
                else:
                    self.__web_port = self.reader.getint_safe(section_key, key)
                    if self.web_port is None:
                        self.reader.add_warning(f'port non valide [{self.reader.get(section_key, key)}], par défaut '
                                                f'[{DEFAULT_WEB_PORT}]', section_key, key)
                key = 'launch_browser'
                if key not in web_section:
                    self.reader.add_warning(
                        f'option absente, par défaut [{"on" if DEFAULT_WEB_LAUNCH_BROWSER else "off"}]',
                        section_key, key)
                else:
                    self.__web_launch_browser = self.reader.getboolean_safe(section_key, key)
                    if self.__web_launch_browser is None:
                        self.reader.add_error(
                            f'valeur invalide [{self.reader.get(section_key, key)}]', section_key, key)
            section_key = 'ffe'
            try:
                options = self.reader[section_key]
                key = 'upload_delay'
                if key not in options:
                    self.reader.add_warning(
                        f'option absente, par défaut [{DEFAULT_FFE_UPLOAD_DELAY}]', section_key, key)
                else:
                    self.__ffe_upload_delay = self.reader.getint_safe(section_key, key)
                    if self.ffe_upload_delay is None or self.ffe_upload_delay < MIN_FFE_UPLOAD_DELAY:
                        self.reader.add_warning(f'délai non valide [{self.reader.get(section_key, key)}], par défaut '
                                                f'[{DEFAULT_FFE_UPLOAD_DELAY}]', section_key, key)
            except KeyError:
                self.reader.add_warning('rubrique introuvable, configuration par défaut', section_key)
        else:
            self.reader.add_debug('configuration par défaut')
        if self.log_level is None:
            self.__log_level = DEFAULT_LOG_LEVEL
        configure_logger(self.log_level)
        if self.web_host is None:
            self.__web_host = DEFAULT_WEB_HOST
        if self.web_port is None:
            self.__web_port = DEFAULT_WEB_PORT
        if self.web_launch_browser is None:
            self.__web_launch_browser = DEFAULT_WEB_LAUNCH_BROWSER
        if self.ffe_upload_delay is None:
            self.__ffe_upload_delay = DEFAULT_FFE_UPLOAD_DELAY

    @property
    def log_level(self) -> int:
        return self.__log_level

    @property
    def log_level_str(self) -> str:
        return self.__log_levels[self.__log_level]

    @property
    def web_host(self) -> str:
        return self.__web_host

    @property
    def web_port(self) -> int:
        return self.__web_port

    @property
    def web_launch_browser(self) -> bool:
        return self.__web_launch_browser

    @property
    def ffe_upload_delay(self) -> int:
        return self.__ffe_upload_delay

    version: Version = Version('2.4rc10')

    url: str = 'https://github.com/papi-web-org/papi-web'

    copyright: str = '© Pascal AUBRY 2013-2024'

    event_path: Path = Path() / 'events'

    event_ext: str = 'db'

    custom_path: Path = Path().absolute() / 'custom'

    default_papi_path: Path = Path() / 'papi'

    papi_ext: str = 'papi'

    _database_path: Path = Path(__file__).resolve().parent / '..' / 'database'

    database_sql_path: Path = _database_path / 'sql'

    database_yml_path: Path = _database_path / 'yml'

    yml_ext: str = 'yml'

    litestar_version: Version = litestar.__version__.formatted(short=True)

    jinja2_version: Version = jinja2.__version__

    uvicorn_version: Version = uvicorn.__version__

    pyodbc_version: Version = Version(pyodbc.version)

    bootstrap_version: Version = Version('5.3.3')

    bootstrap_icons_version: Version = Version('1.11.3')

    htmx_version: Version = Version('1.9.12')

    jquery_version: Version = Version('3.7.1')

    sortable_version: Version = Version('1.15.2')

    jstree_version: Version = Version('3.3.17')

    def __url(self, ip: str | None) -> str | None:
        if ip is None:
            return None
        return f'http://{ip}{f":{self.web_port}" if self.web_port != 80 else ""}'

    @property
    def lan_ip(self) -> str | None:
        if self.__lan_ip is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            try:
                s.connect(('10.254.254.254', 1))  # doesn't even have to be reachable
                self.__lan_ip = s.getsockname()[0]
            except Exception:  # pylint: disable=broad-exception-caught
                pass
            finally:
                s.close()
        return self.__lan_ip

    @property
    def local_ip(self) -> str:
        if self.__local_ip is None:
            self.__local_ip = '127.0.0.1'
        return self.__local_ip

    @property
    def lan_url(self) -> str:
        return self.__url(self.lan_ip)

    @property
    def local_url(self) -> str:
        return self.__url(self.local_ip)

    default_record_illegal_moves_number: int = 0

    default_allow_results_deletion_on_input_screens: bool = False

    default_timer_colors: dict[int, str] = {
            1: '#00FF00',
            2: '#FF7700',
            3: '#FF0000',
        }

    default_timer_delays: dict[int, int] = {
            1: 15,
            2: 5,
            3: 10,
        }

    default_players_show_unpaired: bool = True

    default_rotator_delay: int = 15

    default_rotator_show_menus: bool = False

    default_timer_round_text_before: str = 'Début de la ronde {} dans %s'

    default_timer_round_text_after: str = 'Ronde {} commencée depuis %s'

    user_index_update_delay: int = 10

    user_event_update_delay: int = 10

    user_screen_update_delay: int = 10

    user_screen_set_update_delay: int = 10

    allowed_columns: list[int] = [1, 2, 3, 4, 6]

    default_columns: int = 4

    default_background_image: str = '/static/images/papi-web-background.png'

    error_background_image: str = '/static/images/papi-web-error.png'

    default_background_color: str = '#e9ecef'

    admin_background_color: str = '#dbcdff'

    user_background_color: str = default_background_color

    @staticmethod
    def default_boards_screen_menu_text(single_tournament: bool, first_last: bool) -> str:
        if single_tournament:
            if first_last:
                return 'Éch. %f-%l'
            else:
                return 'Par échiquier'
        else:
            if first_last:
                return '%t [Éch. %f-%l]'
            else:
                return '%t (par échiquier)'

    @staticmethod
    def default_players_screen_menu_text(single_tournament: bool, first_last: bool) -> str:
        if single_tournament:
            if first_last:
                return '%f-%l'
            else:
                return 'Par ordre alpha.'
        else:
            if first_last:
                return '%t [Éch. %f-%l]'
            else:
                return '%t (par ordre alpha.)'

    default_results_screen_menu_text: str = 'Derniers résultats'

    chessevent_download_url: str = 'https://chessevent.echecs-bretagne.fr/download'
