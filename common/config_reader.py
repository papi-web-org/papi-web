import re
from pathlib import Path

import chardet
from configparser import (
    ConfigParser, DuplicateSectionError, DuplicateOptionError,
    MissingSectionHeaderError, ParsingError, Error, SectionProxy
)
from logging import Logger
from common.logger import get_logger

logger: Logger = get_logger()

TMP_DIR: Path = Path('tmp')

EVENTS_PATH: Path = Path('events')


# https://docs.python.org/3/library/configparser.html
class ConfigReader(ConfigParser):

    screen_set_keys = ['tournament', 'name', 'first', 'last', 'part', 'parts', 'number', ]

    screen_keys: list[str] = [
        'type',
        'name',
        'columns',
        'menu_text',
        'show_timer',
        'menu',
        'update',
        'limit',
    ]

    def __init__(self, ini_file: Path, ini_marker_file: Path, silent: bool):
        super().__init__(interpolation=None, empty_lines_in_values=False)
        self.__ini_file: Path = ini_file
        self.__infos: list[str] = []
        self.__warnings: list[str] = []
        self.__errors: list[str] = []
        self.__silent: bool = False
        if not self.ini_file.exists():
            self.add_warning('fichier non trouvé')
            return
        if not self.ini_file.is_file():
            self.add_error(f'{self.ini_file} n\'est pas un fichier')
            return
        if silent:
            try:
                if ini_marker_file.lstat().st_mtime > self.ini_file.lstat().st_mtime:
                    self.__silent = True
                else:
                    logger.info(f'le fichier de configuration [{self.ini_file}] a été modifié, rechargement...')
            except FileNotFoundError:
                logger.info(f'nouveau fichier de configuration [{self.ini_file}], chargement...')
        try:
            files_read: list[str] = []
            encoding: str = 'utf-8'
            try:
                if not self.__silent:
                    logger.debug(f'lecture de {self.__ini_file} en {encoding}...')
                files_read = self.read(self.__ini_file, encoding=encoding)
            except UnicodeDecodeError:
                logger.debug(f'la lecture de {self.__ini_file} en {encoding} a échoué, recherche de l\'encodage...')
                detected_encoding: str
                with open(self.__ini_file, "rb") as f:
                    detected_encoding: str = chardet.detect(f.read())['encoding']
                logger.debug(f'encodage détecté : {detected_encoding}')
                if detected_encoding != 'utf-8':
                    logger.debug(f'lecture de {self.__ini_file} en {detected_encoding}...')
                    files_read = self.read(self.__ini_file, encoding=detected_encoding)
            if str(self.__ini_file) not in files_read:
                self.add_error(f'impossible de lire {self.__ini_file}')
                return
            ini_marker_file.parents[0].mkdir(parents=True, exist_ok=True)
            ini_marker_file.touch()
        except DuplicateSectionError as dse:
            self.__silent = False
            self.add_error(f'rubrique dupliquée à la ligne {dse.lineno}', dse.section)
            return
        except DuplicateOptionError as doe:
            self.__silent = False
            self.add_error(f'option dupliquée à la ligne {doe.lineno}', doe.section, doe.option)
            return
        except MissingSectionHeaderError as mshe:
            self.__silent = False
            self.add_error(f'la première rubrique manque à la ligne {mshe.lineno}')
            return
        except ParsingError as pe:
            self.__silent = False
            self.add_error(f'erreur de parsing: {pe.message}')
            return
        except Error as e:
            self.__silent = False
            self.add_error(f'erreur: {e.message}')
            return

    @property
    def ini_file(self) -> Path:
        return self.__ini_file

    def __format_message(self, text: str, section_key: str | None, key: str | None):
        if section_key is None:
            return f'{self.ini_file.name}: {text}'
        elif key is None:
            return f'{self.ini_file.name}[{section_key}]: {text}'
        else: 
            return f'{self.ini_file.name}[{section_key}].{key}: {text}'

    def add_debug(self, text: str, section_key: str | None = None, key: str | None = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.debug(message)

    @property
    def infos(self) -> list[str]:
        return self.__infos

    def add_info(self, text: str, section_key: str | None = None, key: str | None = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.info(message)
        self.__infos.append(message)

    @property
    def warnings(self) -> list[str]:
        return self.__warnings

    def add_warning(self, text: str, section_key: str | None = None, key: str | None = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.warning(message)
        self.__warnings.append(message)

    @property
    def errors(self) -> list[str]:
        return self.__errors

    def add_error(self, text: str, section_key: str | None = None, key: str | None = None):
        message = self.__format_message(text, section_key, key)
        if not self.__silent:
            logger.error(message)
        self.__errors.append(message)

    def getint_safe(self, section_key: str, key: str, minimum: int = None, maximum: int = None) -> int | None:
        try:
            val: int = self.getint(section_key, key)
            if minimum is not None and val < minimum:
                return None
            if maximum is not None and val > maximum:
                return None
            return val
        except ValueError:
            return None

    def getboolean_safe(self, section_key: str, key: str) -> bool | None:
        try:
            val: bool = self.getboolean(section_key, key)
            return val
        except ValueError:
            return None

    def get_subsection_keys_with_prefix(self, prefix: str, first_level_only: int = True) -> list[str]:
        subsection_keys: list[str] = []
        for section_key in self.sections():
            if first_level_only:
                pattern = r'^{}\.([^.]+)$'
            else:
                pattern = r'^{}\.([^.]+(\.[^.]+)*)$'
            matches = re.match(pattern.format(prefix.replace('.', '\\.')), section_key)
            if matches:
                subsection_keys.append(matches.group(1))
        return subsection_keys

    def rename_section(self, old_section_key: str, new_section_key: str):
        # NOTE(Amaras) this can add values that are in DEFAULTSEC if any.
        # This can also cause a crash if we're trying to delete DEFAULTSEC,
        # as deleting DEFAUTLSEC causes a ValueError.
        self[new_section_key] = self[old_section_key]
        del self[old_section_key]

    def get_value_with_warning(
        self,
        section: SectionProxy,
        section_key: str,
        key: str,
        target_type: type,
        predicate,
        default_value,
        *messages,
    ):
        try:
            value = target_type(section[key])
            assert predicate(value)
            return value
        except TypeError:
            self.add_error(messages[0], section_key)
            return default_value
        except KeyError:
            self.add_warning(messages[1], section_key, key)
            return default_value
        except ValueError:
            self.add_warning(messages[2], section_key, key)
            return default_value
        except AssertionError:
            self.add_warning(messages[3], section_key, key)
            return default_value
