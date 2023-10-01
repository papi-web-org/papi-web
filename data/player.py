from functools import total_ordering
from logging import Logger
from dataclasses import dataclass, field
from enum import StrEnum, Enum, IntEnum, auto
from optional import Optional

from data.pairing import Pairing
from common.logger import get_logger

logger: Logger = get_logger()


class PlayerTitle(IntEnum):
    g = 6
    gf = 5
    m = 4
    mf = 3
    f = 2
    ff = 1
    no = 0


PLAYER_TITLE_VALUES = {title.name: title.value for title in PlayerTitle}
del PLAYER_TITLE_VALUES[PlayerTitle.no]
PLAYER_TITLE_VALUES[''] = 0
PLAYER_TITLE_STRINGS = {v: k for k, v in PLAYER_TITLE_VALUES.items()}


class PlayerSex(StrEnum):
    M = 'M'
    F = 'F'


PLAYER_SEX_M: str = PlayerSex.M.value
PLAYER_SEX_F: str = PlayerSex.F.value


class Color(StrEnum):
    White = 'W'
    Black = 'B'


COLOR_WHITE: str = Color.White.value
COLOR_BLACK: str = Color.White.value
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
    __sex: PlayerSex
    __title: Optional[PlayerTitle]
    __rating: int
    __rating_type: str
    __fixed: int
    __pairings: dict[int, Pairing]
    __points: Optional[float] = field(default=Optional.empty(), init=False)
    __vpoints: Optional[float] = field(default=Optional.empty(), init=False)
    __board_id: Optional[int] = field(default=Optional.empty(), init=False)
    __board_number: Optional[int] = field(default=Optional.empty(), init=False)
    __color: Optional[Color] = field(default=Optional.empty(), init=False)
    __handicap_initial_time: Optional[int] = field(default=Optional.empty(), init=False)
    __handicap_increment: Optional[int] = field(default=Optional.empty(), init=False)
    __handicap_time_modified: Optional[bool] = field(default=Optional.empty(), init=False)

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
    def sex(self) -> PlayerSex:
        return self.__sex

    @property
    def title(self) -> Optional[PlayerTitle]:
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
    def __points_str(points: Optional[float]) -> str:
        if points.is_empty():
            return ''
        if points.get() == 0.5:
            return '½'
        return '{:.1f}'.format(points.get()).replace('.0', '').replace('.5', '½')

    @property
    def points(self) -> Optional[float]:
        return self.__points

    def set_points(self, points: float):
        self.__points = Optional.of(points)

    def add_points(self, points: float):
        self.__points = self.__points.map(lambda x: x + points)

    @property
    def points_str(self) -> str:
        return self.__points_str(self.points)

    @property
    def vpoints(self) -> Optional[float]:
        return self.__vpoints

    def set_vpoints(self, vpoints: float):
        self.__vpoints = Optional.of(vpoints)

    def add_vpoints(self, vpoints: float):
        self.__vpoints = self.__vpoints.map(lambda x: x + vpoints)

    @property
    def vpoints_str(self) -> str:
        return self.__points_str(self.vpoints)

    @property
    def not_paired_str(self) -> str:
        return 'Non apparié' + ('e' if self.__sex == PlayerSex.F else '')

    @property
    def exempt_str(self) -> str:
        return 'Exempt' + ('e' if self.__sex == PlayerSex.F else '')

    @property
    def board_id(self) -> Optional[int]:
        return self.__board_id

    def set_board_id(self, board_id: int):
        self.__board_id = Optional.of(board_id)

    @property
    def board_number(self) -> Optional[int]:
        return self.__board_number

    def set_board_number(self, board_number: int):
        self.__board_number = Optional.of(board_number)

    @property
    def color(self) -> Optional[Color]:
        return self.__color

    def set_color(self, color: Color):
        self.__color = Optional.of(color)

    @property
    def color_str(self) -> str:
        return self.color.map(lambda k: COLOR_STRINGS[k]).get_or_default('')

    @property
    def handicap_initial_time(self) -> Optional[int]:
        return self.__handicap_initial_time

    @property
    def handicap_initial_time_minutes(self) -> Optional[int]:
        return self.__handicap_initial_time.map(lambda t: t // 60)

    @property
    def handicap_initial_time_seconds(self) -> Optional[int]:
        return self.__handicap_initial_time.map(lambda t: t % 60)

    @property
    def handicap_increment(self) -> Optional[int]:
        return self.__handicap_increment

    @property
    def handicap_time_modified(self) -> Optional[int]:
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
