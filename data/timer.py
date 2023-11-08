import datetime as dt
from logging import Logger
from dataclasses import dataclass, field
from collections import namedtuple
import warnings

from common.logger import get_logger

logger: Logger = get_logger()

ROUND_DEFAULT_TEXT_BEFORE: str = 'Début de la ronde {} dans %s'
ROUND_DEFAULT_TEXT_AFTER: str = 'Ronde {} commencée depuis %s'


def timestamp_to_datetime(ts: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts)


def datetime_to_str(dt: dt.datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M')


def timestamp_to_str(ts: int) -> str:
    return datetime_to_str(timestamp_to_datetime(ts))


@dataclass
class TimerHour:
    _id: int | str
    timestamp: int
    round: int | None = None
    text_before: str | None = None
    text_after: str | None = None
    datetime: dt.datetime = field(init=False)
    timestamp_1: int | None = field(default=None, init=False)
    timestamp_2: int | None = field(default=None, init=False)
    timestamp_3: int | None = field(default=None, init=False)
    timestamp_next: int | None = field(default=None, init=False)
    last: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.text_before is None and self.round is not None:
            self.text_before = ROUND_DEFAULT_TEXT_BEFORE.format(self.round)
        if self.text_after is None and self.round is not None:
            self.text_after = ROUND_DEFAULT_TEXT_AFTER.format(self.round)
        self.datetime = timestamp_to_datetime(self.timestamp)

    @property
    def id(self) -> int | str:
        return self._id

    @property
    def datetime_str(self) -> str:
        return self.datetime.strftime('%Y-%m-%d %H:%M')

    @property
    def date_str(self) -> str:
        return self.datetime.strftime('%Y-%m-%d')

    @property
    def time_str(self) -> str:
        return self.datetime.strftime('%H:%M')

    def set_text_before(self, text: str):
        warnings.warn("Use direct assignment to text_before instead")
        self.text_before = text

    def set_text_after(self, text: str):
        warnings.warn("Use direct assignment to text_after instead")
        self.text_after = text

    def set_round(self, round: int):
        self.text_before = ROUND_DEFAULT_TEXT_BEFORE.format(round)
        self.text_after = ROUND_DEFAULT_TEXT_AFTER.format(round)

    @property
    def datetime_str_1(self) -> str:
        return timestamp_to_str(self.timestamp_1)

    @property
    def datetime_str_2(self) -> str:
        return timestamp_to_str(self.timestamp_2)

    @property
    def datetime_str_3(self) -> str:
        return timestamp_to_str(self.timestamp_3)

    @property
    def datetime_str_next(self) -> str:
        return timestamp_to_str(self.timestamp_next)

    def set_timestamps(self, timestamp_1: int, timestamp_2: int, timestamp_3: int, timestamp_next: int):
        self.timestamp_1 = timestamp_1
        self.timestamp_2 = timestamp_2
        self.timestamp_3 = timestamp_3
        self.timestamp_next = timestamp_next

    def set_last(self, last: bool):
        warnings.warn("Use direct assignment to last instead")
        self.last = last

    def __repr__(self):
        return f'{self.__class__.__name__}({self.timestamp} {self.datetime_str} [{self.text_before}/{self.text_after}])'


RGB = namedtuple('RGB', ['red', 'green', 'blue'])
DEFAULT_COLORS: dict[int, RGB] = {
        1: RGB(0, 255, 0),
        2: RGB(255, 127, 0),
        3: RGB(255, 0, 0),
}
DEFAULT_DELAYS: dict[int, int] = {1: 15, 2: 5, 3: 10, }


class Timer:
    def __init__(self):
        self.colors: dict[int, RGB] = DEFAULT_COLORS
        self.delays: dict[int, int] = DEFAULT_DELAYS
        self.hours: list[TimerHour] = []

    def set_hours_timestamps(self):
        for hour in self.hours:
            hour.set_timestamps(
                hour.timestamp - self.delays[1] * 60 - self.delays[2] * 60,
                hour.timestamp - self.delays[2] * 60,
                hour.timestamp,
                hour.timestamp + self.delays[3] * 60)
        self.hours[-1].set_last(True)

    def __repr__(self):
        return f'{type(self).__name__}({self.colors} {self.delays} {self.hours})'
