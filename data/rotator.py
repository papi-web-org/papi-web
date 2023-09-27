from logging import Logger
from common.logger import get_logger
from data.screen import AScreen
from dataclasses import dataclass

logger: Logger = get_logger()


ROTATOR_DEFAULT_DELAY: int = 15


@dataclass(frozen=True)
class Rotator:
    id: str
    delay: int
    screens: list[AScreen]

