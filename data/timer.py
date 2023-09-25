import datetime
from logging import Logger

from common.logger import get_logger

logger: Logger = get_logger()

ROUND_DEFAULT_TEXT_BEFORE: str = 'Début de la ronde {} dans %s'
ROUND_DEFAULT_TEXT_AFTER: str = 'Ronde {} commencée depuis %s'


def timestamp_to_datetime(ts: int) -> datetime:
    return datetime.datetime.fromtimestamp(ts)


def datetime_to_str(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M')


def timestamp_to_str(ts: int) -> str:
    return datetime_to_str(timestamp_to_datetime(ts))


class TimerHour:
    def __init__(self, id: int | str, timestamp: int, round: int | None = None,
                 text_before: str | None = None, text_after: str | None = None):
        self.__id: int | str = id
        self.__timestamp: int = timestamp
        self.__datetime = timestamp_to_datetime(self.timestamp)
        self.__text_before: str | None = None
        self.__text_after: str | None = None
        if round is not None:
            self.__text_before = ROUND_DEFAULT_TEXT_BEFORE.format(round)
            self.__text_after = ROUND_DEFAULT_TEXT_AFTER.format(round)
        if text_before is not None:
            self.__text_before = text_before
        if text_after is not None:
            self.__text_after = text_after
        self.__timestamp_1: int | None = None
        self.__timestamp_2: int | None = None
        self.__timestamp_3: int | None = None
        self.__timestamp_next: int | None = None
        self.__last = False

    @property
    def id(self) -> int | str:
        return self.__id

    @property
    def timestamp(self) -> int:
        return self.__timestamp

    @property
    def datetime_str(self) -> str:
        return self.__datetime.strftime('%Y-%m-%d %H:%M')

    @property
    def date_str(self) -> str:
        return self.__datetime.strftime('%Y-%m-%d')

    @property
    def time_str(self) -> str:
        return self.__datetime.strftime('%H:%M')

    def set_text_before(self, text: str):
        self.__text_before = text

    def set_text_after(self, text: str):
        self.__text_after = text

    def set_round(self, round: int):
        self.set_text_before(ROUND_DEFAULT_TEXT_BEFORE.format(round))
        self.set_text_after(ROUND_DEFAULT_TEXT_AFTER.format(round))

    @property
    def text_before(self) -> str:
        return self.__text_before

    @property
    def text_after(self) -> str:
        return self.__text_after

    @property
    def timestamp_1(self) -> int:
        return self.__timestamp_1

    @property
    def timestamp_2(self) -> int:
        return self.__timestamp_2

    @property
    def timestamp_3(self) -> int:
        return self.__timestamp_3

    @property
    def timestamp_next(self) -> int:
        return self.__timestamp_next

    @property
    def datetime_str_1(self) -> str:
        return timestamp_to_str(self.__timestamp_1)

    @property
    def datetime_str_2(self) -> str:
        return timestamp_to_str(self.__timestamp_2)

    @property
    def datetime_str_3(self) -> str:
        return timestamp_to_str(self.__timestamp_3)

    @property
    def datetime_str_next(self) -> str:
        return timestamp_to_str(self.__timestamp_next)

    @property
    def last(self) -> bool:
        return self.__last

    def set_timestamps(self, timestamp_1: int, timestamp_2: int, timestamp_3: int, timestamp_next: int):
        self.__timestamp_1 = timestamp_1
        self.__timestamp_2 = timestamp_2
        self.__timestamp_3 = timestamp_3
        self.__timestamp_next = timestamp_next

    def set_last(self, last: bool):
        self.__last = last

    def __repr__(self):
        return f'{type(self).__name__}({self.timestamp} {self.datetime_str} [{self.text_before}/{self.text_after}])'


DEFAULT_COLORS: dict[int, tuple[int, int, int, ]] = {1: (0, 255, 0), 2: (255, 127, 0), 3: (255, 0, 0), }
DEFAULT_DELAYS: dict[int, int] = {1: 15, 2: 5, 3: 10, }


class Timer:
    def __init__(self):
        self.__colors: dict[int, tuple[int, int, int, ]] = DEFAULT_COLORS
        self.__delays: dict[int, int] = DEFAULT_DELAYS
        self.__hours: list[TimerHour] = []

    @property
    def colors(self) -> dict[int, tuple[int, int, int, ]]:
        return self.__colors

    @property
    def delays(self) -> dict[int, int]:
        return self.__delays

    @property
    def hours(self) -> list[TimerHour]:
        return self.__hours

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
