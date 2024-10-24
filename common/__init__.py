import re
import time
from collections import namedtuple
from datetime import datetime
from functools import wraps
from logging import Logger

from common.logger import get_logger

RGB = namedtuple('RGB', ['red', 'green', 'blue'])

logger: Logger = get_logger()


def check_rgb_str(color: str) -> str:
    """Checks if a string is in #rrggbb format
    returns it back if it is, raises ValueError otherwise."""
    rgb: RGB = hexa_to_rgb(color)
    if rgb:
        return rgb_to_hexa(rgb)
    raise ValueError(f'check_rgb_str(color={color})')


def hexa_to_rgb(color: str) -> RGB | None:
    """Converts a string from #rrggbb to RGB(red, green, blue) format."""
    hex_pattern = re.compile('^#?(?P<R>[0-9a-f]{2})(?P<G>[0-9a-f]{2})(?P<B>[0-9a-f]{2})$')
    if matches := hex_pattern.match(color.strip().lower()):
        return (
            int(matches.group('R'), 16),
            int(matches.group('G'), 16),
            int(matches.group('B'), 16),
        )
    return None


def rgb_to_hexa(rgb: RGB) -> str:
    """Converts a color in RGB(red, green, blue) format to #rrggbb format."""
    return '#' + ''.join(f'{max(0, min(255, i)):02X}' for i in rgb)


def format_timestamp_date_time(ts: float | None = None) -> str:
    """Formats the given timestamp (now if None) to YYYY-mm-dd HH:MM format."""
    return datetime.strftime(datetime.fromtimestamp(ts if ts is not None else time.time()), '%Y-%m-%d %H:%M')


def format_timestamp_date(ts: float | None = None) -> str:
    """Formats the given timestamp (now if None) to YYYY-mm-dd format."""
    return datetime.strftime(datetime.fromtimestamp(ts if ts is not None else time.time()), '%Y-%m-%d')


def format_timestamp_time(ts: float | None = None) -> str:
    """Formats the given timestamp (now if None) to HH:MM format."""
    return datetime.strftime(datetime.fromtimestamp(ts if ts is not None else time.time()), '%H:%M')


def show_duration(func):
    """This decorator prints the duration of methods."""
    @wraps(func)
    def show_duration_wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        total_time = end_time - start_time
        # first item in the args, ie `args[0]` is `self`
        logger.warning(f'{total_time:.4f}s {args[0].__class__.__name__}.{func.__name__}({args[1:]} {kwargs})')
        return result
    return show_duration_wrapper
