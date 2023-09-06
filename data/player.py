import math
from functools import total_ordering
from typing import Dict, Optional
from logging import Logger

from data.pairing import Pairing
from common.logger import get_logger

logger: Logger = get_logger()

PLAYER_TITLE_VALUES: Dict[str, int] = {'g': 6, 'gf': 5, 'm': 4, 'mf': 3, 'f': 2, 'ff': 1, '': 0, }
PLAYER_TITLE_STRINGS = {v: k for k, v in PLAYER_TITLE_VALUES.items()}

PLAYER_SEX_M: str = 'M'
PLAYER_SEX_F: str = 'F'

COLOR_WHITE: str = 'W'
COLOR_BLACK: str = 'B'
COLOR_DB_VALUES: Dict[str, str] = {
    'B': COLOR_WHITE,
    'N': COLOR_BLACK,
}
COLOR_VALUES: Dict[int, str] = {v: k for k, v in COLOR_DB_VALUES.items()}
COLOR_STRINGS: Dict[str, str] = {
    COLOR_WHITE: 'Blancs',
    COLOR_BLACK: 'Noirs',
}


@total_ordering
class Player:
    def __init__(self, papi_id: int, last_name: str, first_name: str, sex: str, title: int, rating: int,
                 rating_type: str, fixed: int, pairings: Dict[int, Pairing]):
        self.__id: int = papi_id
        self.__last_name: str = last_name
        self.__first_name: str = first_name
        self.__sex: str = sex
        self.__title: int = title
        self.__rating: int = rating
        self.__rating_type: str = rating_type
        self.__fixed = fixed
        self.__pairings: Dict[int, Pairing] = pairings
        self.__points: Optional[float] = None
        self.__vpoints: Optional[float] = None
        self.__board_id: Optional[int] = None
        self.__board_number: Optional[int] = None
        self.__color: Optional[str] = None
        self.__handicap_initial_time: Optional[int] = None
        self.__handicap_increment: Optional[int] = None
        self.__handicap_time_modified: Optional[bool] = None

    @property
    def id(self) -> int:
        return self.__id

    @property
    def first_name(self) -> str:
        return self.__first_name

    @property
    def last_name(self) -> str:
        return self.__last_name

    @property
    def sex(self) -> str:
        return self.__sex

    @property
    def title(self) -> int:
        return self.__title

    @property
    def title_str(self) -> str:
        return PLAYER_TITLE_STRINGS[self.__title]

    @property
    def rating(self) -> int:
        return self.__rating

    @property
    def rating_type(self) -> str:
        return self.__rating_type

    @property
    def fixed(self) -> int:
        return self.__fixed

    @property
    def pairings(self) -> Dict[int, Pairing]:
        return self.__pairings

    @staticmethod
    def __points_str(points: float) -> str:
        if points == 0.5:
            return '½'
        return '{:.1f}'.format(points).replace('.0', '').replace('.5', '½')

    @property
    def points(self) -> float:
        return self.__points

    def set_points(self, points: float):
        self.__points = points

    def add_points(self, points: float):
        self.__points += points

    @property
    def points_str(self) -> str:
        return self.__points_str(self.points)

    @property
    def vpoints(self) -> float:
        return self.__vpoints

    def set_vpoints(self, vpoints: float):
        self.__vpoints = vpoints

    def add_vpoints(self, vpoints: float):
        self.__vpoints += vpoints

    @property
    def vpoints_str(self) -> str:
        return self.__points_str(self.vpoints)

    @property
    def not_paired_str(self) -> str:
        return 'Non apparié' + ('e' if self.__sex == PLAYER_SEX_F else '')

    @property
    def exempt_str(self) -> str:
        return 'Exempt' + ('e' if self.__sex == PLAYER_SEX_F else '')

    @property
    def board_id(self) -> Optional[int]:
        return self.__board_id

    def set_board_id(self, board_id: int):
        self.__board_id = board_id

    @property
    def board_number(self) -> Optional[int]:
        return self.__board_number

    def set_board_number(self, board_number: int):
        self.__board_number = board_number

    @property
    def color(self) -> Optional[str]:
        return self.__color

    def set_color(self, color: str):
        self.__color = color

    @property
    def color_str(self) -> str:
        return COLOR_STRINGS[self.color]

    @property
    def handicap_initial_time(self) -> Optional[int]:
        return self.__handicap_initial_time

    @property
    def handicap_initial_time_minutes(self) -> Optional[int]:
        if self.__handicap_initial_time is None:
            return None
        return self.handicap_initial_time // 60

    @property
    def handicap_initial_time_seconds(self) -> Optional[int]:
        if self.__handicap_initial_time is None:
            return None
        return self.handicap_initial_time % 60

    @property
    def handicap_increment(self) -> Optional[int]:
        return self.__handicap_increment

    @property
    def handicap_time_modified(self) -> Optional[int]:
        return self.__handicap_time_modified

    @property
    def handicap_str(self) -> Optional[str]:
        if self.__handicap_initial_time is None:
            return None
        (minutes, seconds) = divmod(self.__handicap_initial_time, 60)
        minutes_str: str = f'{minutes}\'' if minutes > 0 else ''
        seconds_str: str = f'{seconds}"' if seconds > 0 else ''
        class_str: str = 'modified-time' if self.__handicap_time_modified else 'base-time'
        return f'<span class="{class_str}">{minutes_str}{seconds_str}</span> + {self.handicap_increment}"/cp'

    def set_handicap(self, initial_time: int, increment: int, time_modified: bool):
        self.__handicap_initial_time = initial_time
        self.__handicap_increment = increment
        self.__handicap_time_modified = time_modified

    def __lt__(self, other: 'Player'):
        # p1 < p2 calls p1.__lt__(p2)
        if self.vpoints < other.vpoints:
            return True
        if self.vpoints > other.vpoints:
            return False
        if self.rating < other.rating:
            return True
        if self.rating > other.rating:
            return False
        if self.title < other.title:
            return True
        if self.title > other.title:
            return False
        if self.last_name > other.last_name:
            return True
        if self.last_name < other.last_name:
            return False
        return self.first_name > other.first_name

    def __eq__(self, other: 'Player'):
        # p1 == p2 calls p1.__eq__(p2)
        if self.vpoints != other.vpoints:
            return False
        if self.rating != other.rating:
            return False
        if self.title != other.title:
            return False
        if self.last_name != other.last_name:
            return False
        return self.first_name == other.first_name

    def __repr__(self):
        if self.id == 1:
            return f'{type(self).__name__}(EXEMPT)'
        return (f'{type(self).__name__}'
                f'({self.title_str}{self.last_name} {self.first_name} {self.rating} [{self.vpoints}])')
