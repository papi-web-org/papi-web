import re
from pathlib import Path

import chardet
from configparser import (
        ConfigParser, DuplicateSectionError, DuplicateOptionError,
        MissingSectionHeaderError, ParsingError, Error
    )
from typing import List, Optional
from logging import Logger
from common.logger import get_logger

logger: Logger = get_logger()

TMP_DIR: Path = Path('tmp')


# https://docs.python.org/3/library/configparser.html
class ConfigReader(ConfigParser):
    def __init__(self, ini_file: Path, silent: bool):
        super().__init__(interpolation=None, empty_lines_in_values=False)
        self.__ini_file: Path = ini_file
        ini_marker_dir: Path = TMP_DIR / self.ini_file.parent
        ini_marker_file: Path = ini_marker_dir / f'{self.ini_file.name}.read'
        self.__infos: List[str] = []
        self.__warnings: List[str] = []
        self.__errors: List[str] = []
        self.__silent: bool = False
        if not self.ini_file.exists():
            self._add_warning('file not found')
            return
        if not self.ini_file.is_file():
            self._add_error('not a file')
            return
        if silent:
            if not ini_marker_file.is_file():
                logger.info(f'New configuration file [{self.ini_file}] found, loading...')
            elif ini_marker_file.lstat().st_mtime > self.ini_file.lstat().st_mtime:
                self.__silent = True
            else:
                logger.info(f'Configuration file [{self.ini_file}] has been modified, reloading...')
        try:
            encoding: str
            with open(self.__ini_file, "rb") as f:
                encoding = chardet.detect(f.read())['encoding']
            files_read = self.read(self.__ini_file, encoding=encoding)
            # NOTE(Amaras) There could still be a problem leading to not
            # getting a configuration.
            # Since a file raising an OSError is ignored, a file not existing
            # (due to a TOC/TOU bug), a file being changed to a directory
            # (e.g. by symlink switching), or a permission error (not accounted
            # for by previous checks)
            if str(self.__ini_file) not in files_read:
                self._add_error(f'Could not read: {self.__ini_file}')
                return
            if not ini_marker_dir.is_dir():
                ini_marker_dir.mkdir(parents=True)
            ini_marker_file.touch()
        except DuplicateSectionError as dse:
            self.__silent = False
            self._add_error(f'section is duplicated at line {dse.lineno}', dse.section)
            return
        except DuplicateOptionError as doe:
            self.__silent = False
            self._add_error(f'key is duplicated at line {doe.lineno}', doe.section, doe.option)
            return
        except MissingSectionHeaderError as mshe:
            self.__silent = False
            self._add_error(f'the first section is missing at line {mshe.lineno}')
            return
        except ParsingError as pe:
            self.__silent = False
            self._add_error(f'parsing error: {pe.message}')
            return
        except Error as e:
            self.__silent = False
            self._add_error(f'error: {e.message}')
            return

    @property
    def ini_file(self) -> Path:
        return self.__ini_file

    def __format_message(self, text: str, section_key: Optional[str], key: Optional[str]):
        if section_key is None:
            return f'{self.ini_file.name}: {text}'
        elif key is None:
            return f'{self.ini_file.name}[{section_key}]: {text}'
        else: 
            return f'{self.ini_file.name}[{section_key}].{key}: {text}'

    def _add_debug(self, text: str, section_key: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.debug(message)

    @property
    def infos(self) -> List[str]:
        return self.__infos

    def _add_info(self, text: str, section_key: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.info(message)
        self.__infos.append(message)

    @property
    def warnings(self) -> List[str]:
        return self.__warnings

    def _add_warning(self, text: str, section_key: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.warning(message)
        self.__warnings.append(message)

    @property
    def errors(self) -> List[str]:
        return self.__errors

    def _add_error(self, text: str, section_key: Optional[str] = None, key: Optional[str] = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.error(message)
        self.__errors.append(message)

    def _getint_safe(self, section_key: str, key: str, minimum: int = None, maximum: int = None) -> Optional[int]:
        try:
            val: int = self.getint(section_key, key)
            if minimum is not None and val < minimum:
                return None
            if maximum is not None and val > maximum:
                return None
            return val
        except ValueError:
            return None

    def _getboolean_safe(self, section_key: str, key: str) -> Optional[bool]:
        try:
            val: bool = self.getboolean(section_key, key)
            return val
        except ValueError:
            return None

    def _get_subsection_keys_with_prefix(self, prefix: str, first_level_only: int = True) -> List[str]:
        subsection_keys: List[str] = []
        for section_key in self.sections():
            if first_level_only:
                pattern = r'^{}\.([^.]+)$'
            else:
                pattern = r'^{}\.([^.]+(\.[^.]+)*)$'
            matches = re.match(pattern.format(prefix.replace('.', '\\.')), section_key)
            if matches:
                subsection_keys.append(matches.group(1))
        return subsection_keys
