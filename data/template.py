from logging import Logger
from dataclasses import dataclass, field

from common.logger import get_logger

logger: Logger = get_logger()


@dataclass
class Template:
    __id: str
    data: dict[str | None, dict[str, str]] = field(default_factory=dict, init=False)

    @property
    def id(self) -> str:
        return self.__id

    def add_data(self, section: str | None, key: str, value: str):
        if section not in self.data:
            self.data[section] = {key: value, }
        else:
            self.data[section][key] = value
