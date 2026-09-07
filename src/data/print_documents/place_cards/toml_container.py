import logging
from contextlib import suppress
from pathlib import Path

import toml
from toml import TomlDecodeError

from common.logger import get_logger

logger: logging.Logger = get_logger()


class TOMLContainer:
    """A utility class to read TOML files."""

    def __init__(
        self,
        toml_file: Path,
    ):
        self.toml_file = toml_file
        self.data: dict[
            str, str | int | float | bool | dict[str, str | int | float | bool]
        ] = {}
        try:
            self.data = toml.load(self.toml_file)
        except FileNotFoundError:
            # A missing file is treated as an empty container so the editor can
            # build a brand new template before it is written to disk.
            pass
        except TomlDecodeError as tde:
            logger.exception('[%s]: %s.', self.toml_file.name, tde)

    def get_value(
        self,
        prop: str,
        section: str = '',
        *,
        default: str | int | float | bool | None = None,
        values: list[str] | None = None,
    ) -> str | int | float | bool | None:
        if not prop:
            logger.warning(
                '[%s]: no custom section or property provided, defaults to [%s].',
                self.toml_file.name,
                default,
            )
            return default
        value: str | int | float | bool
        if section:
            try:
                section_data = self.data[section]
                if not isinstance(section_data, dict):
                    return default
                try:
                    value = section_data[prop]
                except KeyError:
                    return default
            except KeyError:
                return default
        else:
            try:
                if isinstance(self.data[prop], dict):
                    return default
                value = self.data[prop]  # type: ignore
            except KeyError:
                return default
        if value is None:
            return default
        if values and value not in values:
            if section:
                logger.warning(
                    '[%s]: value [%s] not accepted for custom property [%s] of section [%s] (accepted values: [%s]), defaults to  [%s].',
                    self.toml_file.name,
                    value,
                    prop,
                    section,
                    ', '.join(values),
                    default,
                )
            else:
                logger.warning(
                    '[%s]: value [%s] not accepted for custom property [%s] (accepted values: [%s]), defaults to  [%s].',
                    self.toml_file.name,
                    value,
                    prop,
                    ', '.join(values),
                    default,
                )
            return default
        else:
            return value

    def get_opt_str(
        self,
        prop: str,
        *,
        section: str = '',
        default: str | None = None,
        values: list[str] | None = None,
    ) -> str | None:
        value = self.get_value(
            prop=prop, section=section, default=default, values=values
        )
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)

    def get_str(
        self,
        prop: str,
        *,
        section: str = '',
        default: str | None = None,
        values: list[str] | None = None,
    ) -> str:
        value = self.get_value(
            prop=prop, section=section, default=default, values=values
        )
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        return str(value)

    def get_opt_bool(
        self,
        prop: str,
        *,
        section: str = '',
        default: bool | None = None,
    ) -> bool | None:
        value = self.get_value(prop=prop, section=section, default=default)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        match str(value).lower():
            case 'true' | 'on':
                return True
            case 'false' | 'off':
                return False
            case _:
                logger.warning(
                    '[%s]: value [%s] not accepted for custom property [%s] (bool expected), defaults to [%s].',
                    self.toml_file.name,
                    value,
                    prop,
                    default,
                )
                return default

    def get_bool(
        self,
        prop: str,
        *,
        section: str = '',
        default: bool | None = None,
    ) -> bool:
        return self.get_opt_bool(prop=prop, section=section, default=default) or False

    def get_opt_int(
        self,
        prop: str,
        *,
        section: str = '',
        default: int | None = None,
    ) -> int | None:
        value = self.get_value(prop=prop, section=section, default=default)
        if value is None:
            return None
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except ValueError:
            assert prop is not None
            logger.warning(
                '[%s]: value [%s] not accepted for custom property [%s] (integer expected), defaults to [%s].',
                self.toml_file.name,
                value,
                prop,
                default,
            )
            return default

    def get_int(
        self,
        prop: str,
        *,
        section: str = '',
        default: int | None = None,
    ) -> int:
        return self.get_opt_int(prop=prop, section=section, default=default) or 0

    def get_opt_float(
        self,
        prop: str,
        section: str = '',
        default: float | None = None,
    ) -> float | None:
        value = self.get_value(prop=prop, section=section, default=default)
        if value is None:
            return None
        if isinstance(value, float):
            return value
        try:
            return float(value)
        except ValueError:
            assert prop is not None
            logger.warning(
                'Value [%s] not accepted for custom property [%s] (float expected), defaults to [%s].',
                self.toml_file.name,
                self.data[prop],
                prop,
                default,
            )
            return default

    def get_float(
        self,
        prop: str,
        *,
        section: str = '',
        default: float | None = None,
    ) -> float:
        return self.get_opt_float(prop=prop, section=section, default=default) or 0.0

    def get_section_properties(
        self,
        section: str = '',
    ) -> list[str]:
        if section:
            if section not in self.data:
                return []
            if not isinstance(self.data[section], dict):
                return []
            return [
                key
                for key in self.data[section].keys()  # type: ignore
            ]
        else:
            return [
                key for key in self.data.keys() if not isinstance(self.data[key], dict)
            ]

    def get_sections(
        self,
    ) -> list[str]:
        return [key for key in self.data.keys() if isinstance(self.data[key], dict)]

    def set_value(
        self,
        prop: str,
        *,
        value: str | int | float | bool,
        section: str = '',
    ):
        if section:
            if section not in self.data:
                self.data[section] = {}
            if isinstance(self.data[section], dict):
                self.data[section][prop] = value  # type: ignore
        else:
            self.data[prop] = value

    def delete_properties(
        self,
        properties: list[str],
        section: str = '',
    ):
        for prop in properties:
            with suppress(KeyError):
                if (
                    section
                    and section in self.data
                    and isinstance(self.data[section], dict)
                ):
                    del self.data[section][prop]  # type: ignore
                else:
                    del self.data[prop]

    def save(self) -> None:
        """Write the in-memory data back to the TOML file on disk."""
        self.toml_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.toml_file, 'w', encoding='utf-8') as f:
            toml.dump(self.data, f)
