import weakref
from collections import Counter
from dataclasses import dataclass, field
from functools import total_ordering
from typing import NamedTuple, Optional, Self, SupportsFloat, TYPE_CHECKING

from utils import Utils
from utils.enum import (
    PlayerTitle,
    TitleNorm,
    PlayerRatingType,
)

if TYPE_CHECKING:
    from _weakref import ReferenceType
    from data.tie_breaks.tie_breaks import TieBreak
    from data.player import TournamentPlayer


@dataclass(frozen=True)
@total_ordering
class Federation:
    name: str = ''

    def __le__(self, other: Self):
        # p1 <= p2 calls p1.__le__(p2)
        assert isinstance(other, self.__class__), (
            f'Can not compare [{type(other)}] and [{self.__class__}]'
        )
        return self.name <= other.name

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
@total_ordering
class Club:
    name: str = ''

    def __le__(self, other: Self):
        # p1 <= p2 calls p1.__le__(p2)
        assert isinstance(other, self.__class__), (
            f'Can not compare [{type(other)}] and [{self.__class__}]'
        )
        return self.name <= other.name

    def __str__(self) -> str:
        return self.name


@dataclass
class PlayerRating:
    estimated: int | None = None
    national: int | None = None
    fide: int | None = None
    k_factor: int | None = None

    @classmethod
    def from_stored_value(cls, dict_rating: dict[str, int | None]) -> Self:
        return cls(
            estimated=dict_rating.get('estimated', None),
            national=dict_rating.get('national', None),
            fide=dict_rating.get('fide', None),
            k_factor=dict_rating.get('k', None),
        )

    @classmethod
    def from_type(cls, value: int | None, rating_type: PlayerRatingType) -> Self:
        match rating_type:
            case PlayerRatingType.FIDE:
                return cls(fide=value)
            case PlayerRatingType.NATIONAL:
                return cls(national=value)
            case PlayerRatingType.ESTIMATED:
                return cls(estimated=value)
            case _:
                raise ValueError(f'{rating_type=}')

    def get_type_value(self, rating_type: PlayerRatingType) -> int | None:
        if rating_type == PlayerRatingType.FIDE:
            return self.fide
        elif rating_type == PlayerRatingType.NATIONAL:
            return self.national
        else:
            return self.estimated

    def set_value_from_type(self, value: int | None, rating_type: PlayerRatingType):
        if rating_type == PlayerRatingType.FIDE:
            self.fide = value
        elif rating_type == PlayerRatingType.NATIONAL:
            self.national = value
        else:
            self.estimated = value

    @property
    def stored_value(self) -> dict[str, int | None]:
        ratings: dict[str, int | None] = {}
        if self.estimated is not None:
            ratings['estimated'] = self.estimated
        if self.national is not None:
            ratings['national'] = self.national
        if self.fide is not None:
            ratings['fide'] = self.fide
        if self.k_factor is not None:
            ratings['k'] = self.k_factor
        return ratings

    def __str__(self) -> str:
        parts = []
        if self.fide is not None:
            parts.append(f'{self.fide}{PlayerRatingType.FIDE.short_name}')
        if self.national is not None:
            parts.append(f'{self.national}{PlayerRatingType.NATIONAL.short_name}')
        if self.estimated is not None:
            parts.append(f'{self.estimated}{PlayerRatingType.ESTIMATED.short_name}')
        return '/'.join(parts) if parts else '-'


@dataclass
class PlayerRatingAndType:
    value: int
    type: PlayerRatingType

    def __str__(self) -> str:
        return f'{self.value} {self.type.short_name}' if self.value else '-'


# 1.4.3d thresholds (FIDE Handbook B.01, 1 Jan 2024). Module-level so the
# typing.NamedTuple below isn't confused into treating them as fields.
BIG_TOURNAMENT_MIN_FEDERATIONS = 3
BIG_TOURNAMENT_MIN_FOREIGNERS = 20
BIG_TOURNAMENT_MIN_TITLED_FOREIGNERS = 10


class BigTournamentExemption(NamedTuple):
    """Aggregated per-tournament counts used by 1.4.3d (Swiss size exception).

    Each field is the worst-case (minimum) across every round in the
    tournament — 1.4.3d requires the threshold to hold for *every* round.

    The threshold constants live at module level above; the properties
    here apply them so the per-field check is a one-liner.
    """

    federations: int
    foreigners: int
    titled_foreigners: int

    @property
    def federations_met(self) -> bool:
        return self.federations >= BIG_TOURNAMENT_MIN_FEDERATIONS

    @property
    def foreigners_met(self) -> bool:
        return self.foreigners >= BIG_TOURNAMENT_MIN_FOREIGNERS

    @property
    def titled_foreigners_met(self) -> bool:
        return self.titled_foreigners >= BIG_TOURNAMENT_MIN_TITLED_FOREIGNERS

    @property
    def is_met(self) -> bool:
        """True iff the tournament qualifies for 1.4.3d (and 1.4.4) exemption."""
        return (
            self.federations_met and self.foreigners_met and self.titled_foreigners_met
        )


@dataclass
class NormCheckResult:
    title_norm: TitleNorm
    meets_gender: bool

    played_games: int = 0
    federations_count: int = 0
    from_own_federations_count: int = 0
    from_host_federations_count: int = 0
    # Counted opponents with federation FID — accepted games that don't
    # enter the federation mix (1.4.2a). Shown in the audit histogram.
    fid_count: int = 0
    num_title_holders: int = 0
    title_counts: Optional[Counter[PlayerTitle]] = None
    federations_counter: Optional[Counter['Federation']] = None
    required_titles: list[PlayerTitle] = field(default_factory=list)
    required_titles_met: int = 0
    num_rated_players: int = 0
    score: float = 0
    average_rating: float = 0
    adjusted_player: Optional['TournamentPlayer'] = None
    adjusted_player_rating: Optional[int] = None
    performance: float = 0
    performance_diff: float | None = None
    ignored_opponents_ids: set[int] = field(default_factory=set)

    all_federations_count: int = 0
    eligible_players_count: int = 0
    eligible_players_title_count: int = 0

    not_enough_games: str | None = None
    not_enough_federations: str | None = None
    too_many_own_federation: str | None = None
    too_many_one_federation: Optional[tuple[Federation, str]] = None
    not_enough_title_holders: str | None = None
    not_enough_required_titles: str | None = None
    score_too_low: str | None = None
    average_too_low: str | None = None
    performance_too_low: str | None = None

    # 1.4.3d
    not_enough_all_federations: str | None = None
    not_enough_foreign_players: str | None = None
    not_enough_all_title_holders: str | None = None

    # 1.5.6a
    requirement_156a_met: bool = False

    # 1.4.2c — True if this result used the "last-round opponent forfeit
    # included as a played LOSS" fallback rather than the default 1.4.1c
    # "forfeit excluded" interpretation. The norm check tries 1.4.1c first
    # and only falls back to 1.4.2c if it yields `is_met` where 1.4.1c didn't.
    applied_142c: bool = False

    # When `applied_142c` is True, the 1.4.1c interpretation's losing
    # NormCheckResult — populated so the calculation-details view can show
    # both Rps side by side. None when 1.4.2c did not apply (1.4.1c won
    # outright, or no last-round forfeit existed).
    alternate_142c: Optional['NormCheckResult'] = None

    # 1.4.1e / 1.4.1f — rounds the subset searcher dropped to satisfy the
    # norm. Empty when no search ran or when no winning subset was found.
    ignored_rounds_via_search: frozenset[int] = field(default_factory=frozenset)

    # Per-round audit trail copied from the `NormInputs` that produced
    # this result. One entry per round in the applicant's schedule, with
    # the decision (included / excluded / dropped / no opponent) and a
    # reason key. Rendered by the IT1 in a collapsible block. Typed as
    # list[Any] here to avoid a circular import with data.norms.inputs.
    round_audit: list = field(default_factory=list)

    # 1.4.3a/b/c — exemption from the foreigner requirement (1.4.3 AND
    # 1.4.4, see 1.4.3e: "the normal foreigner requirement. (See 1.4.3
    # and 1.4.4)"). Set by the print doc's `apply_143abc_exemption`
    # based on the arbiter's tournament-type selection. Values: 'a',
    # 'b', 'c', or None. Independent of 1.4.3d: both exemption paths
    # can hold on the same result simultaneously.
    rule_143_exemption: str | None = None

    @property
    def is_143d_met(self) -> bool:
        return (
            not self.not_enough_all_federations
            and not self.not_enough_foreign_players
            and not self.not_enough_all_title_holders
        )

    @property
    def is_143_exempt_via_abc(self) -> bool:
        return self.rule_143_exemption in ('a', 'b', 'c')

    @property
    def is_met(self) -> bool:
        if not self.meets_gender:
            return False
        # These checks have no exemption — must all pass.
        if (
            self.not_enough_games
            or self.not_enough_title_holders
            or self.not_enough_required_titles
            or self.score_too_low
            or self.average_too_low
            or self.performance_too_low
        ):
            return False
        # 1.4.3a-d all exempt the foreigner requirement, i.e. BOTH 1.4.3
        # and 1.4.4 ("except 1.4.3a - 1.4.3d shall be exempt"; the
        # "Otherwise, 1.4.4 applies" clause inside 1.4.3d means 1.4.4
        # stops applying when an exemption holds).
        if self.is_143d_met or self.is_143_exempt_via_abc:
            return True
        return not (
            self.not_enough_federations
            or self.too_many_own_federation
            or self.too_many_one_federation
        )


class TieBreakValue:
    def __init__(self, tie_break: 'TieBreak', value: SupportsFloat):
        self._tie_break_ref: 'ReferenceType[TieBreak]' = weakref.ref(tie_break)
        self.value = value
        self.rank_progress: int | None = None

    @property
    def tie_break(self) -> 'TieBreak':
        if (tie_break := self._tie_break_ref()) is None:
            raise RuntimeError('Reference has been garbage collected')
        return tie_break

    @property
    def display_value(self) -> str | float:
        if self.rank_progress is not None:
            if self.rank_progress > 0:
                return f'▲ {self.rank_progress}'
            if self.rank_progress < 0:
                return f'▼ {-self.rank_progress}'
            return ''
        value = float(self.value)
        if self.tie_break.display_absolute_value:
            return abs(value)
        return value

    @property
    def display_string_value(self) -> str:
        value = self.display_value
        if isinstance(value, float):
            decimals = self.tie_break.display_decimals
            if decimals is not None:
                return f'{value:.{decimals}f}'
            return Utils.points_str(value)
        return value

    def __str__(self) -> str:
        return self.display_string_value
