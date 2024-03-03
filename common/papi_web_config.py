import logging
import os
import socket
from pathlib import Path
from logging import Logger

import jinja2
import litestar
import pyodbc

from common.singleton import singleton
from common.config_reader import ConfigReader, TMP_DIR
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()

PAPI_WEB_VERSION: str = '2.2.0-rc2'

PAPI_WEB_URL = 'https://github.com/papi-web-org/papi-web'

PAPI_WEB_COPYRIGHT: str = '© Pascal AUBRY 2013-2024'

CONFIG_FILE: Path = Path('papi-web.ini')

DEFAULT_LOG_LEVEL: int = logging.INFO
DEFAULT_WEB_PORT: int = 8080
DEFAULT_WEB_LAUNCH_BROWSER: bool = True
DEFAULT_FFE_UPLOAD_DELAY: int = 180
MIN_FFE_UPLOAD_DELAY: int = 60


@singleton
class PapiWebConfig:
    def __init__(self):
        self.reader = ConfigReader(CONFIG_FILE, TMP_DIR / 'config' / f'papi-web.ini.{os.getpid()}.read', silent=False)
        self.__log_level: int | None = None
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
                self.reader.add_warning(f'rubrique introuvable', section_key)
            section_key = 'web'
            if section_key not in self.reader:
                self.reader.add_warning(f'rubrique introuvable', section_key)
            else:
                web_section = self.reader[section_key]
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
                self.reader.add_warning(f'rubrique introuvable, configuration par défaut', section_key)
        else:
            self.reader.add_debug(f'configuration par défaut')
        if self.log_level is None:
            self.__log_level = DEFAULT_LOG_LEVEL
        configure_logger(self.log_level)
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
    def web_port(self) -> int:
        return self.__web_port

    @property
    def web_launch_browser(self) -> bool:
        return self.__web_launch_browser

    @property
    def ffe_upload_delay(self) -> int:
        return self.__ffe_upload_delay

    @property
    def litestar_version(self) -> str:
        return litestar.__version__.formatted(short=True)

    @property
    def jinja2_version(self) -> str:
        return jinja2.__version__

    @property
    def pyodbc_version(self) -> str:
        return pyodbc.version

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
            except Exception:
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
