import os
import re

from configparser import ConfigParser, DuplicateSectionError, DuplicateOptionError, MissingSectionHeaderError, \
    ParsingError, Error
from typing import List, Optional
from logging import Logger
from common.logger import get_logger

logger: Logger = get_logger()


# https://docs.python.org/3/library/configparser.html
class ConfigReader(ConfigParser):
    def __init__(self, ini_file: str, print_errors: bool = True, print_warnings: bool = True, print_infos: bool = True):
        super().__init__(interpolation=None)
        self.__ini_file: str = ini_file
        self.__infos: List[str] = []
        self.__warnings: List[str] = []
        self.__errors: List[str] = []
        self.__print_infos: bool = print_infos
        self.__print_warnings: bool = print_warnings
        self.__print_errors: bool = print_errors
        if not os.path.exists(self.__ini_file):
            self._add_warning('file not found')
            return
        if not os.path.isfile(self.__ini_file):
            self._add_error('not a file')
            return
        try:
            self.read(self.__ini_file, encoding='utf8')
        except DuplicateSectionError as dse:
            self._add_error('section is duplicated at line {}'.format(dse.lineno, dse.message), section=dse.section)
            return
        except DuplicateOptionError as doe:
            self._add_error(
                'key {} is duplicated at line {}'.format(doe.lineno, doe.message), section=doe.section, key=doe.option)
            return
        except MissingSectionHeaderError as mshe:
            self._add_error('the first section is missing at line {}'.format(mshe.lineno, mshe.message))
            return
        except ParsingError as pe:
            self._add_error('parsing error: {}'.format(pe.message))
            return
        except Error as e:
            self._add_error('error: {}'.format(e.message))
            return

    @property
    def ini_file(self) -> str:
        return self.__ini_file

    def __format_message(self, text: str, section: Optional[str], key: Optional[str]):
        if section is None:
            return '{}: {}'.format(os.path.basename(self.__ini_file), text)
        if key is None:
            return '{}[{}]: {}'.format(os.path.basename(self.__ini_file), section, text)
        return '{}[{}].{}: {}'.format(os.path.basename(self.__ini_file), section, key, text)

    def _add_debug(self, text: str, section: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section, key)
        logger.debug(message)

    @property
    def infos(self) -> List[str]:
        return self.__infos

    def _add_info(self, text: str, section: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section, key)
        logger.info(message)
        self.__infos.append(message)

    @property
    def warnings(self) -> List[str]:
        return self.__warnings

    def _add_warning(self, text: str, section: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section, key)
        logger.warning(message)
        self.__warnings.append(message)

    @property
    def errors(self) -> List[str]:
        return self.__errors

    def _add_error(self, text: str, section: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section, key)
        logger.error(message)
        self.__errors.append(message)

    def _getint_safe(self, section: str, key: str, minimum: int = None, maximum: int = None) -> Optional[int]:
        try:
            val: int = self.getint(section, key)
            if minimum is not None and val < minimum:
                return None
            if maximum is not None and val > maximum:
                return None
            return val
        except ValueError:
            return None

    def _getboolean_safe(self, section: str, key: str) -> Optional[bool]:
        try:
            val: bool = self.getboolean(section, key)
            return val
        except ValueError:
            return None

    def _get_subsections_with_prefix(self, prefix: str, first_level_only: int = True) -> List[str]:
        subsections: List[str] = []
        for section in self.sections():
            if first_level_only:
                pattern = '^{}\\.([^.]+)$'
            else:
                pattern = '^{}\\.([^.]+(\\.[^.]+)*)$'
            matches = re.match(pattern.format(prefix.replace('.', '\\.')), section)
            if matches:
                subsections.append(matches.group(1))
        return subsections
