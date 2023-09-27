from functools import total_ordering
from logging import Logger
from dataclasses import dataclass, field

from data.pairing import Pairing
from common.logger import get_logger

logger: Logger = get_logger()

PLAYER_TITLE_VALUES: dict[str, int] = {'g': 6, 'gf': 5, 'm': 4, 'mf': 3, 'f': 2, 'ff': 1, '': 0, }
PLAYER_TITLE_STRINGS = {v: k for k, v in PLAYER_TITLE_VALUES.items()}

PLAYER_SEX_M: str = 'M'
PLAYER_SEX_F: str = 'F'

COLOR_WHITE: str = 'W'
COLOR_BLACK: str = 'B'
COLOR_DB_VALUES: dict[str, str] = {
    'B': COLOR_WHITE,
    'N': COLOR_BLACK,
}
COLOR_VALUES: dict[str, str] = {v: k for k, v in COLOR_DB_VALUES.items()}
COLOR_STRINGS: dict[str, str] = {
    COLOR_WHITE: 'Blancs',
    COLOR_BLACK: 'Noirs',
}


@dataclass
@total_ordering
class Player:
    __id: int
    __last_name: str
    __first_name: str
    __sex: str
    __title: int
    __rating: int
    __rating_type: str
    __fixed: int
    __pairings: dict[int, Pairing]
    __points: float | None = field(default=None, init=False)
    __vpoints: float | None = field(default=None, init=False)
    __board_id: int | None = field(default=None, init=False)
    __color: str | None = field(default=None, init=False)
    __handicap_initial_time: int | None = field(default=None, init=False)
    __handicap_increment: int | None = field(default=None, init=False)
    __handicap_time_modified: bool | None = field(default=None, init=False)

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
    def pairings(self) -> dict[int, Pairing]:
        return self.__pairings

    @staticmethod
    def __points_str(points: float | None) -> str:
        if points is None:
            return ''
        if points == 0.5:
            return '½'
        return '{:.1f}'.format(points).replace('.0', '').replace('.5', '½')

    @property
    def points(self) -> float | None:
        return self.__points

    def set_points(self, points: float):
        self.__points = points

    def add_points(self, points: float):
        if self.__points is not None:
            self.__points += points

    @property
    def points_str(self) -> str:
        return self.__points_str(self.points)

    @property
    def vpoints(self) -> float | None:
        return self.__vpoints

    def set_vpoints(self, vpoints: float):
        self.__vpoints = vpoints

    def add_vpoints(self, vpoints: float):
        if self.__vpoints is not None:
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
    def board_id(self) -> int | None:
        return self.__board_id

    def set_board_id(self, board_id: int):
        self.__board_id = board_id

    @property
    def board_number(self) -> int | None:
        return self.__board_number

    def set_board_number(self, board_number: int):
        self.__board_number = board_number

    @property
    def color(self) -> str | None:
        return self.__color

    def set_color(self, color: str):
        self.__color = color

    @property
    def color_str(self) -> str:
        return COLOR_STRINGS[self.color] if self.color is not None else ''

    @property
    def handicap_initial_time(self) -> int | None:
        return self.__handicap_initial_time

    @property
    def handicap_initial_time_minutes(self) -> int | None:
        if self.__handicap_initial_time is None:
            return None
        return self.__handicap_initial_time // 60

    @property
    def handicap_initial_time_seconds(self) -> int | None:
        if self.__handicap_initial_time is None:
            return None
        return self.__handicap_initial_time % 60

    @property
    def handicap_increment(self) -> int | None:
        return self.__handicap_increment

    @property
    def handicap_time_modified(self) -> int | None:
        return self.__handicap_time_modified

    @property
    def handicap_str(self) -> str | None:
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

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(other, Player):
            return NotImplemented
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
            return f'{self.__class__.__name__}(EXEMPT)'
        return (f'{self.__class__.__name__}'
                f'({self.title_str}{self.last_name} {self.first_name} {self.rating} [{self.vpoints}])')
