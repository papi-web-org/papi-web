import datetime
from logging import Logger
from typing import Optional, Tuple, List, Dict, Union

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


class TimerEvent:
    def __init__(self, id: Union[int, str], timestamp: int, round: Optional[int] = None,
                 text_before: Optional[str] = None, text_after: Optional[str] = None):
        self.__id: Union[int, str] = id
        self.__timestamp: int = timestamp
        self.__datetime = timestamp_to_datetime(self.timestamp)
        self.__text_before: Optional[str] = None
        self.__text_after: Optional[str] = None
        if round is not None:
            self.__text_before = ROUND_DEFAULT_TEXT_BEFORE.format(round)
            self.__text_after = ROUND_DEFAULT_TEXT_AFTER.format(round)
        if text_before is not None:
            self.__text_before = text_before
        if text_after is not None:
            self.__text_after = text_after
        self.__timestamp_1: Optional[int] = None
        self.__timestamp_2: Optional[int] = None
        self.__timestamp_3: Optional[int] = None
        self.__timestamp_next: Optional[int] = None
        self.__last = False

    @property
    def id(self) -> Union[int, str]:
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
        return '{}({} {} [{}/{}])'.format(
            type(self).__name__, self.timestamp, self.datetime_str, self.text_before, self.text_after)


DEFAULT_COLORS: Dict[int, Tuple[int, int, int, ]] = {1: (0, 255, 0), 2: (255, 127, 0), 3: (255, 0, 0), }
DEFAULT_DELAYS: Dict[int, int] = {1: 15, 2: 5, 3: 10, }


class Timer:
    def __init__(self):
        self.__colors: Dict[int, Tuple[int, int, int, ]] = DEFAULT_COLORS
        self.__delays: Dict[int, int] = DEFAULT_DELAYS
        self.__events: List[TimerEvent] = []

    @property
    def colors(self) -> Dict[int, Tuple[int, int, int, ]]:
        return self.__colors

    @property
    def delays(self) -> Dict[int, int]:
        return self.__delays

    @property
    def events(self) -> List[TimerEvent]:
        return self.__events

    def set_events_timestamps(self):
        for event in self.events:
            event.set_timestamps(
                event.timestamp - self.delays[1] * 60 - self.delays[2] * 60,
                event.timestamp - self.delays[2] * 60,
                event.timestamp,
                event.timestamp + self.delays[3] * 60)
        self.events[-1].set_last(True)

    def __repr__(self):
        return '{}({} {} {})'.format(
            type(self).__name__, self.colors, self.delays, self.events)
