import re
from collections import namedtuple
from logging import Logger

from common.logger import get_logger

RGB = namedtuple('RGB', ['red', 'green', 'blue'])

logger: Logger = get_logger()


def check_rgb_str(color: str) -> str:
    rgb: RGB = hexa_to_rgb(color)
    if rgb:
        return rgb_to_hexa(hexa_to_rgb(color))
    raise ValueError(f'check_rgb_str(color={color})')


def hexa_to_rgb(color: str) -> RGB | None:
    hex_pattern = re.compile('^#?(?P<R>[0-9a-f]{2})(?P<G>[0-9a-f]{2})(?P<B>[0-9a-f]{2})$')
    if matches := hex_pattern.match(color.strip().lower()):
        return (
            int(matches.group('R'), 16),
            int(matches.group('G'), 16),
            int(matches.group('B'), 16),
        )
    return None


def rgb_to_hexa(rgb: RGB) -> str:
    return '#' + ''.join(f'{max(0, min(255, i)):02X}' for i in rgb)
