from functools import total_ordering
from logging import Logger
from dataclasses import dataclass, field
from contextlib import suppress
import warnings

from data.pairing import Pairing
from common.logger import get_logger
from data.util import PlayerSex, PlayerTitle, Color

logger: Logger = get_logger()

# TODO(pascalaubry) Remove these unused variables
PLAYER_TITLE_VALUES = {title.name: title.value for title in PlayerTitle}
del PLAYER_TITLE_VALUES[PlayerTitle.no.name]
PLAYER_TITLE_VALUES[''] = 0
PLAYER_TITLE_STRINGS = {v: k for k, v in PLAYER_TITLE_VALUES.items()}


# TODO(pascalaubry) Remove these unused variables
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
    ref_id: int
    last_name: str
    first_name: str
    sex: PlayerSex
    title: PlayerTitle
    rating: int
    rating_type: str
    fixed: int
    pairings: dict[int, Pairing]
    points: float | None = field(default=None, init=False)
    vpoints: float | None = field(default=None, init=False)
    board_id: int | None = field(default=None, init=False)
    board_number: int | None = field(default=None, init=False)
    color: Color | None = field(default=None, init=False)
    handicap_initial_time: int | None = field(default=None, init=False)
    handicap_increment: int | None = field(default=None, init=False)
    handicap_time_modified: bool | None = field(default=None, init=False)

    @property
    def id(self) -> int:
        return self.ref_id

    @property
    def title_str(self) -> str:
        return str(self.title)

    def compute_points(self, max_round):
        """Computes and stores the points of the player,
        from round 1 to round `max_round` (returns None)"""
        # NOTE(Amaras) this does not rely on the fact that insertion order
        # is preserved in 3.6+ dict, because I can't be sure insertion order
        # is the correct (increasing) round order
        self.points = sum(
                pairing.result.point_value
                for round_index, pairing in self.pairings.items()
                if round_index <= max_round)

    @staticmethod
    def __points_str(points: float | None) -> str:
        if points is None:
            return ''
        if points == 0.5:
            return '½'
        return '{:.1f}'.format(points).replace('.0', '').replace('.5', '½')

    def set_points(self, points: float):
        warnings.warn("Use direct assignment to points instead")
        self.points = points

    def add_points(self, points: float):
        with suppress(TypeError):
            self.points += points

    @property
    def points_str(self) -> str:
        return self.__points_str(self.points)

    def set_vpoints(self, vpoints: float):
        warnings.warn("Use direct assignment to vpoints instead")
        self.vpoints = vpoints

    def add_vpoints(self, vpoints: float):
        with suppress(TypeError):
            self.vpoints += vpoints

    @property
    def vpoints_str(self) -> str:
        return self.__points_str(self.vpoints)

    @property
    def not_paired_str(self) -> str:
        return 'Non apparié' + ('e' if self.sex == PlayerSex.F else '')

    @property
    def exempt_str(self) -> str:
        return 'Exempt' + ('e' if self.sex == PlayerSex.F else '')

    def set_board_id(self, board_id: int):
        warnings.warn("Use direct assignment to board_id instead")
        self.board_id = board_id

    def set_board_number(self, board_number: int):
        warnings.warn("Use direct assignment to board_number instead")
        self.board_number = board_number

    def set_color(self, color: Color):
        warnings.warn("Use direct assignment to color instead")
        self.color = color

    def set_board(self, board_id: int, board_number: int, color: Color):
        self.board_id = board_id
        self.board_number = board_number
        self.color = color

    @property
    def color_str(self) -> str:
        if self.color is None:
            return ''
        else:
            return str(self.color)

    @property
    def handicap_initial_time_minutes(self) -> int | None:
        with suppress(TypeError):
            return self.handicap_initial_time // 60

    @property
    def handicap_initial_time_seconds(self) -> int | None:
        with suppress(TypeError):
            return self.handicap_initial_time % 60

    @property
    def handicap_str(self) -> str | None:
        if self.handicap_initial_time is None:
            return None
        (minutes, seconds) = divmod(self.handicap_initial_time, 60)
        minutes_str: str = f'{minutes}\'' if minutes > 0 else ''
        seconds_str: str = f'{seconds}"' if seconds > 0 else ''
        class_str: str = 'modified-time' if self.handicap_time_modified else 'base-time'
        return f'<span class="{class_str}">{minutes_str}{seconds_str}</span> + {self.handicap_increment}"/cp'

    def set_handicap(self, initial_time: int, increment: int, time_modified: bool):
        self.handicap_initial_time = initial_time
        self.handicap_increment = increment
        self.handicap_time_modified = time_modified

    def __le__(self, other):
        # p1 <= p2 calls p1.__le__(p2)
        if not isinstance(other, Player):
            return NotImplemented
        return (self.vpoints, self.rating, self.title, other.last_name,
                other.first_name) <= (other.vpoints, other.rating, other.title,
                                      self.last_name, self.first_name)

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(other, Player):
            return NotImplemented
        return (
            self.vpoints == other.vpoints and self.rating == other.rating and
            self.title == other.title and self.last_name == other.last_name and
            self.first_name == other.first_name
        )

    def __repr__(self):
        if self.id == 1:
            return f'{self.__class__.__name__}(EXEMPT)'
        return (f'{self.__class__.__name__}'
                f'({self.title_str}{self.last_name} {self.first_name} {self.rating} [{self.vpoints}])')
