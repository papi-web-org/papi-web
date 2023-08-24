import logging
import os
import re
from typing import Optional, Dict
from logging import Logger
from common.config_reader import ConfigReader
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()

PAPI_WEB_VERSION: str = '2.0-rc1'

PAPI_WEB_URL = 'https://domloup.echecs35.fr/papi-web'

PAPI_WEB_COPYRIGHT: str = '© Pascal AUBRY 2013-2023'

CONFIG_FILE: str = os.path.join('.', 'papi-web.ini')

TMP_DIR: str = os.path.join('.', 'tmp')

DEFAULT_LOG_LEVEL: int = logging.INFO
DEFAULT_WEB_HOST: str = '0.0.0.0'
DEFAULT_WEB_PORT: int = 8080


class PapiWebConfig(ConfigReader):
    def __init__(self):
        super().__init__(CONFIG_FILE)
        self.__log_level: Optional[int] = None
        self.__web_host: Optional[str] = None
        self.__web_port: Optional[int] = None
        log_levels: Dict[int, str] = {
            logging.DEBUG: 'DEBUG',
            logging.INFO: 'INFO',
            logging.WARNING: 'WARNING',
            logging.ERROR: 'ERROR',
        }
        if not self.errors and not self.warnings:
            section = 'logging'
            if not self.has_section(section):
                self._add_warning('section not found'.format(), section=section)
            else:
                key = 'level'
                if not self.has_option(section, key):
                    self._add_warning('key not found'.format(), section=section, key=key)
                else:
                    level: str = self.get(section, key)
                    try:
                        self.__log_level = [k for k, v in log_levels.items() if v == level][0]
                    except IndexError:
                        self._add_warning('invalid log level [{}]'.format(level), section=section, key=key)
            section = 'web'
            if not self.has_section(section):
                self._add_warning('section not found'.format(), section=section)
            else:
                key = 'host'
                if not self.has_option(section, key):
                    self._add_warning('key not found'.format(), section=section, key=key)
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
                        self._add_warning(
                            'invalid host configuration [{}]'.format(self.get(section, key)), section=section, key=key)
                key = 'port'
                if not self.has_option(section, key):
                    self._add_warning('key not found'.format(), section=section, key=key)
                else:
                    self.__web_port = self._getint_safe(section, key)
                    if self.web_port is None:
                        self._add_error(
                            'invalid port configuration [{}]'.format(self.get(section, key)), section=section, key=key)
        else:
            self._add_info('setting default configuration')
        if self.log_level is None:
            self.__log_level = DEFAULT_LOG_LEVEL
        configure_logger(self.log_level)
        self._add_info('log: {}'.format(log_levels[self.log_level]))
        if self.web_host is None:
            self.__web_host = DEFAULT_WEB_HOST
        self._add_info('host: {}'.format(self.web_host))
        if self.web_port is None:
            self.__web_port = DEFAULT_WEB_PORT
        self._add_info('port: {}'.format(self.web_port))

    @property
    def log_level(self) -> int:
        return self.__log_level

    @property
    def web_host(self) -> str:
        return self.__web_host

    @property
    def web_port(self) -> int:
        return self.__web_port
