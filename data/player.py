from functools import total_ordering
from logging import Logger
from dataclasses import dataclass, field
from contextlib import suppress
import warnings

from data.pairing import Pairing
from common.logger import get_logger
from data.util import PlayerGender, PlayerTitle, Color
import trf

logger: Logger = get_logger()


# TODO(Amaras) Make sure the initialization is correctly changed
# NOTE(Amaras) Maybe we should use pydantic here?
@dataclass
@total_ordering
class Player:
    # NOTE(Amaras) what is this ref_id: starting rank or FFE database id?
    ref_id: int
    last_name: str
    first_name: str
    gender: PlayerGender
    title: PlayerTitle
    rating: int
    # NOTE(Amaras)
    fide_id: int
    # NOTE(Amaras) change from 2.1: required for TRF
    federation: str
    # NOTE(Amaras) change from 2.1: required for TRF
    # exports to YYYY.01.01
    birth_year: int
    # TODO(Amaras) this should be a data.util.TournamentRating, and not
    # exported in TRF file
    rating_type: str
    # NOTE(Amaras) not exported in TRF file
    fixed: int
    pairings: dict[int, Pairing]
    # TODO(Amaras) The points field could be stored in a fixed-point format
    # the TRF format only specifies points in a XX.X format.
    # However, this implies changing the API, which is not something I'm
    # willing to do just yet.
    points: float | None = field(default=None, init=False)
    vpoints: float | None = field(default=None, init=False)
    # NOTE(Amaras) The following fields are not exported in the TRF file
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
                # NOTE(Amaras) if you were to include the current round
                # in the computation, boards regularly change their ordering
                # during the current round as results are added
                if round_index < max_round)

    @staticmethod
    def _points_str(points: float | None) -> str:
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
        return self._points_str(self.points)

    def set_vpoints(self, vpoints: float):
        warnings.warn("Use direct assignment to vpoints instead")
        self.vpoints = vpoints

    def add_vpoints(self, vpoints: float):
        with suppress(TypeError):
            self.vpoints += vpoints

    @property
    def vpoints_str(self) -> str:
        return self._points_str(self.vpoints)

    @property
    def not_paired_str(self) -> str:
        return 'Non apparié' + ('e' if self.gender == PlayerGender.FEMALE else '')

    @property
    def exempt_str(self) -> str:
        return 'Exempt' + ('e' if self.gender == PlayerGender.FEMALE else '')

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

    def to_trf(self) -> trf.Player.Player:
        # NOTE(Amaras) This assumes Player.ref_id is the startrank
        return trf.Player.Player(
                self.ref_id,
                f'{self.last_name}, {self.first_name}',
                self.gender.to_trf(),
                self.title.to_trf(),
                self.federation,
                self.fide_id,
                f'{self.birth_year}.01.01',
                self.points,
                None,
                list(
                    map(
                        lambda round_, pairing: pairing.to_trf(round_),
                        enumerate(self.pairings, start=1)
                        )
                    )
                )



    def __repr__(self):
        if self.id == 1:
            return f'{self.__class__.__name__}(EXEMPT)'
        return (f'{self.__class__.__name__}'
                f'({self.title_str}{self.last_name} {self.first_name} {self.rating} [{self.vpoints}])')
