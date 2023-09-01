import logging
import re
import socket
from pathlib import Path
from typing import Optional, Dict
from logging import Logger

from django import get_version

from common.singleton import singleton
from common.config_reader import ConfigReader
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()

PAPI_WEB_VERSION: str = '2.0-rc4'

PAPI_WEB_URL = 'https://github.com/pascalaubry/papi-web'

PAPI_WEB_COPYRIGHT: str = '© Pascal AUBRY 2013-2023'

CONFIG_FILE: Path = Path('papi-web.ini')

DEFAULT_LOG_LEVEL: int = logging.INFO
DEFAULT_WEB_HOST: str = '0.0.0.0'
DEFAULT_WEB_PORT: int = 8080
DEFAULT_WEB_LAUNCH_BROWSER: bool = True


@singleton
class PapiWebConfig(ConfigReader):
    def __init__(self):
        super().__init__(CONFIG_FILE, silent=False)
        self.__log_level: Optional[int] = None
        self.__web_host: Optional[str] = None
        self.__web_port: Optional[int] = None
        self.__web_launch_browser: Optional[bool] = None
        self.__local_ip: Optional[str] = None
        self.__lan_ip: Optional[str] = None
        self.__log_levels: Dict[int, str] = {
            logging.DEBUG: 'DEBUG',
            logging.INFO: 'INFO',
            logging.WARNING: 'WARNING',
            logging.ERROR: 'ERROR',
        }
        if not self.errors and not self.warnings:
            section = 'logging'
            if not self.has_section(section):
                self._add_warning('rubrique introuvable', section=section)
            else:
                key = 'level'
                if not self.has_option(section, key):
                    self._add_warning('option absente, par défaut [{}]'.format(self.__log_levels[DEFAULT_LOG_LEVEL]),
                                      section=section, key=key)
                else:
                    level: str = self.get(section, key)
                    try:
                        self.__log_level = [k for k, v in self.__log_levels.items() if v == level][0]
                    except IndexError:
                        self._add_warning('niveau de log invalide [{}]'.format(level), section=section, key=key)
            section = 'web'
            if not self.has_section(section):
                self._add_warning('rubrique introuvable', section=section)
            else:
                key = 'host'
                if not self.has_option(section, key):
                    self._add_warning('option absente'.format(), section=section, key=key)
                else:
                    self.__web_host = self.get(section, key)
                    matches = re.match('^(\\d+)\\.(\\d+)\\.(\\d+)\\.(\\d+)$', self.__web_host)
                    if matches:
                        for i in range(4):
                            if int(matches.group(i + 1)) > 255:
                                self.__web_host = None
                    else:
                        self.__web_host = None
                    if self.web_host is None:
                        self._add_warning('configuration d\'hôte invalide [{}], par défaut [{}]'.format(
                            self.get(section, key), DEFAULT_WEB_HOST), section=section, key=key)
                key = 'port'
                if not self.has_option(section, key):
                    self._add_warning('option absente, par défaut [{}]'.format(DEFAULT_WEB_PORT), section=section,
                                      key=key)
                else:
                    self.__web_port = self._getint_safe(section, key)
                    if self.web_port is None:
                        self._add_warning('port non valide [{}], par défaut [{}]'.format(
                            self.get(section, key), DEFAULT_WEB_PORT), section=section, key=key)
                key = 'launch_browser'
                if not self.has_option(section, key):
                    self._add_warning('option absente, par défaut [{}]'.format(
                        'on' if DEFAULT_WEB_LAUNCH_BROWSER else 'off'), section=section, key=key)
                else:
                    self.__web_launch_browser = self._getboolean_safe(section, key)
                    if self.__web_launch_browser is None:
                        self._add_error('valeur invalide [{}]'.format(self.get(section, key)), section=section, key=key)
        else:
            self._add_debug('configuration par défaut')
        if self.log_level is None:
            self.__log_level = DEFAULT_LOG_LEVEL
        configure_logger(self.log_level)
        if self.web_host is None:
            self.__web_host = DEFAULT_WEB_HOST
        if self.web_port is None:
            self.__web_port = DEFAULT_WEB_PORT
        if self.web_launch_browser is None:
            self.__web_launch_browser = DEFAULT_WEB_LAUNCH_BROWSER

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
    def django_version(self) -> str:
        return get_version()

    def __url(self, ip: Optional[str]) -> Optional[str]:
        if ip is None:
            return None
        return 'http://' + ip + (':' + str(self.web_port) if self.web_port != 80 else '')

    @property
    def lan_ip(self) -> Optional[str]:
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
