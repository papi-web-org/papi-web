from datetime import date, datetime
import weakref
from collections import Counter, defaultdict
from collections.abc import Collection
from functools import cached_property
from logging import Logger
from operator import attrgetter
from typing import TYPE_CHECKING, Any
from _weakref import ReferenceType

from common.exception import SharlyChessException
from common.i18n import _
from common.sharly_chess_config import SharlyChessConfig
from common.logger import get_logger

from data.account import Account
from data.board import Board, compute_round_board_numbers
from data.criteria.managers import TournamentCriterionManager
from data.screens.family import Family
from data.pairings.settings import ColorSeedSetting
from data.player import Player, TournamentPlayer
from data.player_categories import PlayerCategory
from data.prize.assigned_prize import AssignedPrize
from data.prize.prize_category import PrizeCategory
from data.prize.prize_group import PrizeGroup
from data.screens.screen import Screen
from data.teams.team_board import TeamBoard
from data.teams.team_pairing_block import TeamPairingBlock
from data.tie_breaks import (
    TeamTieBreak,
    TieBreak,
    TieBreakOption,
    TieBreakManager,
    TieBreakOptionManager,
)
from data.criteria.tournament_criteria import TournamentCriterion
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredBoard,
    StoredTeamBoard,
    StoredTeamPointAdjustment,
    StoredPlayerPointAdjustment,
    StoredProhibitedPairingGroup,
    StoredTournamentPlayer,
    StoredPairing,
    StoredTieBreak,
    set_stored_fields,
)
from plugins.utils import PluginData
from plugins.manager import plugin_manager
from utils import Utils
from utils.date_time import format_date_range, format_date, format_datetime
from utils.enum import (
    BoardColor,
    PlayerGender,
    Result,
    ScoreType,
    TeamByeType,
    TeamColourType,
    TeamSortMode,
    TournamentRating,
    PlayerRatingType,
    RoleType,
    PlayerTitle,
    CheckInStatus,
    TitleNorm,
)

from utils.types import BigTournamentExemption, TieBreakValue
from data.norms import (
    compute_big_tournament_exemption,
    compute_high_level_tournament,
)
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredTournament, StoredPrizeGroup

if TYPE_CHECKING:
    from data.event import Event
    from data.input_output.trf.trf_data import (
        TrfAbnormalPointsAssignment,
        TrfAcceleratedRound,
        TrfProhibitedPairing,
        TrfOOdOTeamPairing,
        TrfRoundBye,
        TrfTeamForfeitedMatch,
        TrfTeamPABs,
        TrfTournament,
    )
    from data.rule_sets import RuleSet
    from data.rule_sets.rule_sets import PointAdjustment
    from data.prohibited_pairings import (
        ProhibitedPairingDimension,
        RoundProhibitedPairingGroup,
    )
    from data.pairings import PairingVariation, PairingSystem
    from data.pairings.keizer import KeizerScorer
    from data.teams.team import Team
    from data.tie_breaks.team_records import TeamRecord
    from data.tie_breaks.team_tie_breaks import TeamTieBreakContext

logger: Logger = get_logger()


class BoardsById(dict[int, Board]):
    """Board mapping with a version counter for numbering caches."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.version: int = 0

    def __setitem__(self, key: int, value: Board) -> None:
        super().__setitem__(key, value)
        self.version += 1

    def __delitem__(self, key: int) -> None:
        super().__delitem__(key)
        self.version += 1

    def pop(self, *args: Any) -> Any:
        result = super().pop(*args)
        self.version += 1
        return result

    def clear(self) -> None:
        super().clear()
        self.version += 1


class Tournament:
    """A data wrapper around a stored tournament."""

    def __init__(
        self,
        event: 'Event',
        stored_tournament: StoredTournament,
    ):
        self._event_ref: 'ReferenceType[Event]' = weakref.ref(event)
        self.stored_tournament: StoredTournament = stored_tournament
        self._tournament_players_by_rank: dict[int, TournamentPlayer] | None = None
        # Per-player caches are valid only while pairings are stable.
        self._compute_caching_enabled: bool = False
        self._round_board_numbers_cache: dict[tuple[int, int], dict[int, int]] = {}
        # Whole-table Keizer scorer, rebuilt whenever the per-player caches
        # are cleared (see ``set_for_round`` / ``_compute_tournament_player_ranks``).
        self._keizer_scorer: 'KeizerScorer | None' = None

    # -------------------------------------------------------------------------
    # Plugin
    # -------------------------------------------------------------------------

    @staticmethod
    def plugin_data_class_by_plugin_id() -> dict[str, type[PluginData]]:
        return {
            plugin_id: plugin_data_class
            for plugin_id, plugin_data_class in plugin_manager.hook.get_tournament_plugin_data_class()
        }

    @cached_property
    def plugin_data(self) -> dict[str, PluginData]:
        return {
            plugin_id: plugin_data_class.from_stored_value(
                self.stored_tournament.plugin_data.get(plugin_id, {})
            )
            for plugin_id, plugin_data_class in self.plugin_data_class_by_plugin_id().items()
        }

    # -------------------------------------------------------------------------
    # Stored properties
    # -------------------------------------------------------------------------

    @property
    def event(self) -> 'Event':
        event = self._event_ref()
        if event is None:
            raise RuntimeError('Event reference has been garbage collected')
        return event

    @property
    def id(self) -> int:
        assert self.stored_tournament.id is not None
        return self.stored_tournament.id

    @property
    def index(self) -> int:
        return self.stored_tournament.index

    @property
    def name(self) -> str:
        return self.stored_tournament.name

    @property
    def sanitized_name(self) -> str:
        return Utils.name_to_uniq_id(self.name)

    @property
    def full_name(self) -> str:
        return (
            f'{self.event.name} - {self.name}'
            if len(self.event.tournaments_by_id.values()) > 1
            else self.event.name
        )

    @property
    def log_prefix(self) -> str:
        return f'Event [{self.event.uniq_id}] - Tournament [{self.name}] - '

    @property
    def start_date(self) -> date:
        return self.stored_tournament.start_date

    @property
    def stop_date(self) -> date:
        return self.stored_tournament.stop_date

    @property
    def date_range_str(self) -> str:
        return format_date_range(self.start_date, self.stop_date)

    @property
    def start_date_str(self) -> str:
        return format_date(self.start_date)

    @property
    def stop_date_str(self) -> str:
        return format_date(self.stop_date)

    # Round schedule

    @property
    def round_datetimes(self) -> dict[int, datetime | None]:
        """Return the per-round scheduled datetimes: {round_number: datetime | None}."""
        return self.stored_tournament.round_datetimes

    @property
    def has_schedule(self) -> bool:
        """True if at least one round has a scheduled datetime."""
        return any(v is not None for v in self.round_datetimes.values())

    @property
    def schedule_first_datetime(self) -> datetime | None:
        """Return the earliest scheduled round datetime, or None if no schedule."""
        datetimes = [v for v in self.round_datetimes.values() if v is not None]
        return min(datetimes) if datetimes else None

    @property
    def schedule_last_datetime(self) -> datetime | None:
        """Return the latest scheduled round datetime, or None if no schedule."""
        datetimes = [v for v in self.round_datetimes.values() if v is not None]
        return max(datetimes) if datetimes else None

    @property
    def round_schedule_tooltip_str(self) -> str:
        """Return a multi-line string listing each round with its scheduled time, grouped by date."""
        from collections import defaultdict
        from utils.date_time import format_time

        rounds_by_date = defaultdict(list)
        for round_num in sorted(self.round_datetimes.keys()):
            dt = self.round_datetimes[round_num]
            if dt is not None:
                rounds_by_date[format_date(dt.date())].append((round_num, dt))

        lines: list[str] = ['<div class="text-start text-nowrap d-flex flex-column">']
        for date_str, rounds in rounds_by_date.items():
            if len(rounds) == 1:
                round_num, dt = rounds[0]
                round_str = _('Round #{round}').format(round=round_num)
                lines.append(f'<div><b>{format_datetime(dt)}</b> {round_str}</div>')
            else:
                lines.append(f'<div><b>{date_str}</b></div>')
                for round_num, dt in rounds:
                    round_str = _('Round #{round}').format(round=round_num)
                    lines.append(
                        f'<div class="d-flex gap-2 ms-2"><b class="text-end" style="min-width: 45px">{format_time(dt)}</b><span>{round_str}</span></div>'
                    )
        lines.append('</div>')
        return ''.join(lines)

    @property
    def multiple_fide_periods(self) -> bool:
        """Returns True if the tournament lasts more than one month, False otherwise."""
        return (self.stop_date - self.start_date).days > 30

    @property
    def location(self) -> str | None:
        return self.stored_tournament.location or self.event.location

    @property
    def time_control_trf25(self) -> str:
        return self.stored_tournament.time_control_trf25 or ''

    @property
    def record_illegal_moves(self) -> int:
        if self.stored_tournament.record_illegal_moves is not None:
            return self.stored_tournament.record_illegal_moves
        return SharlyChessConfig.default_record_illegal_moves

    @property
    def check_in_open(self) -> bool:
        return self.stored_tournament.check_in_open

    @property
    def default_player_check_in(self) -> bool:
        return self.started

    @property
    def first_board_number(self) -> int:
        return (
            self.stored_tournament.first_board_number
            or SharlyChessConfig.default_first_board_number
        )

    @property
    def paired_bye_result(self) -> Result:
        if self.stored_tournament.paired_bye_result is None:
            return SharlyChessConfig.default_paired_bye_result
        else:
            return Result(self.stored_tournament.paired_bye_result)

    @property
    def max_byes(self) -> int:
        if self.stored_tournament.max_byes is None:
            return SharlyChessConfig.default_max_byes
        else:
            return self.stored_tournament.max_byes

    @property
    def last_rounds_no_byes(self) -> int:
        if self.stored_tournament.last_rounds_no_byes is None:
            return SharlyChessConfig.default_last_rounds_no_byes
        else:
            return self.stored_tournament.last_rounds_no_byes

    @property
    def last_update(self) -> datetime:
        return self.stored_tournament.last_update

    @property
    def last_player_update(self) -> datetime:
        return self.stored_tournament.last_player_update or self.last_update

    @property
    def last_pairing_update(self) -> datetime:
        return self.stored_tournament.last_pairing_update or self.last_update

    @property
    def rounds(self) -> int:
        """The number of rounds this tournament is played over.
        A stored 0 means the pairing system works it out from its entrants"""
        stored_rounds = self.stored_tournament.rounds
        if self.pairing_variation.sets_its_own_round_count:
            # The system's answer wins over whatever is stored. A
            # tournament saved before it could work this out — or before
            # its boards or its entrants changed — would otherwise be
            # stuck with a count that no longer describes it, and could
            # not be paired at all.
            return self.automatic_rounds or stored_rounds or 1
        return stored_rounds or 1

    @property
    def rounds_are_automatic(self) -> bool:
        """Whether the pairing system settles the round count itself."""
        return self.pairing_variation.automatic_round_count(self) is not None or (
            not self.stored_tournament.rounds
        )

    @property
    def automatic_rounds(self) -> int | None:
        if getattr(self, '_computing_automatic_rounds', False):
            return None
        self._computing_automatic_rounds = True
        try:
            return self.pairing_variation.automatic_round_count(self)
        finally:
            self._computing_automatic_rounds = False

    @cached_property
    def pairing_variation(self) -> 'PairingVariation':
        from data.pairings import PairingVariationManager

        return PairingVariationManager(self.event).get_object(
            self.stored_tournament.pairing
        )

    @cached_property
    def pairing_system(self) -> 'PairingSystem':
        return self.pairing_variation.system()

    @cached_property
    def rating(self) -> TournamentRating:
        return TournamentRating(self.stored_tournament.rating)

    @cached_property
    def player_rating_type(self) -> PlayerRatingType:
        return (
            PlayerRatingType(self.stored_tournament.player_rating_type)
            if self.stored_tournament.player_rating_type is not None
            else self.event.player_rating_type
        )

    @property
    def override_unrated_rapid_blitz(self) -> bool:
        return self.stored_tournament.override_unrated_rapid_blitz

    # -------------------------------------------------------------------------
    # Team tournament settings
    # -------------------------------------------------------------------------

    @property
    def is_team_tournament(self) -> bool:
        return self.stored_tournament.team_player_count is not None

    @property
    def team_player_count(self) -> int | None:
        return self.stored_tournament.team_player_count

    @property
    def rule_set_id(self) -> str | None:
        return self.stored_tournament.rule_set

    @cached_property
    def rule_set(self) -> 'RuleSet | None':
        """Resolved :class:`RuleSet` object for this tournament, or
        ``None`` when no rule set is set or the stored id no longer
        maps to a registered rule set (plugin disabled, etc.)."""
        from data.rule_sets import RuleSetManager

        rule_set_id = self.stored_tournament.rule_set
        if not rule_set_id:
            return None
        try:
            rule_set_type = RuleSetManager(self.event).get_type(rule_set_id)
        except KeyError:
            return None
        return rule_set_type(self.stored_tournament.rule_set_config)

    @property
    def roster_max_size(self) -> int | None:
        """Maximum team-roster size, or ``None`` for no cap. Set on the
        tournament directly; a rule set writes (and locks) it via
        ``apply_defaults`` when attached."""
        return self.stored_tournament.roster_max_size

    @property
    def warn_lineup_order(self) -> bool:
        """True iff the lineup editor warns when a round's board order
        differs from the team roster order. Lineups can still be
        reordered freely. Set manually on the tournament, or forced on
        by a rule set."""
        return bool(self.stored_tournament.enforce_roster_order)

    @property
    def rule_set_forced_team_sort_mode(self) -> str | None:
        """The team-sort mode the rule set imposes for the tournament's
        pairing system, or ``None`` when it leaves the choice free."""
        rule_set = self.rule_set
        if rule_set is None:
            return None
        try:
            system_id = self.pairing_system.id
        except KeyError:
            system_id = None
        return rule_set.forced_team_sort_mode(system_id)

    @property
    def team_sort_mode(self) -> TeamSortMode:
        """Effective team-ordering mode. A rule set may force a value
        (locking the choice); otherwise the stored mode applies."""
        forced = self.rule_set_forced_team_sort_mode
        if forced is not None:
            try:
                return TeamSortMode(forced)
            except ValueError:
                pass
        try:
            return TeamSortMode(self.stored_tournament.team_sort_mode)
        except ValueError:
            return TeamSortMode.MANUAL

    @property
    def _has_stored_pairings(self) -> bool:
        """Cheap, shape-agnostic "already paired?" check read straight
        from the stored board collections — no Board objects built
        (so it can't trip over a mid-rebuild player cache). Covers both
        team-board envelopes (Swiss / Berger) and flat fixed-table
        boards (Molter).

        Bye-only envelopes (``team_b_id`` ``None`` — manual HPB / FPB /
        ZPB / PAB pre-marks set before pairing) don't count: a team
        parked on a bye must not freeze team ordering or the sort mode.
        Only a real match (opponent present) or flat boards mean the
        round was actually paired."""
        stored = self.stored_tournament
        if any(
            stb.team_b_id is not None
            for boards in stored.stored_team_boards_by_round.values()
            for stb in boards
        ):
            return True
        return bool(stored.stored_boards_by_round)

    @property
    def team_sort_mode_locked(self) -> bool:
        """True iff a rule set forces the team-sort mode (UI read-only),
        or the tournament is already paired (mode can no longer change)."""
        return (
            self.rule_set_forced_team_sort_mode is not None or self._has_stored_pairings
        )

    def resort_teams(self, database: 'EventDatabase') -> None:
        """Re-assign team pairing numbers per the effective sort mode.
        No-op once any round is paired. MANUAL keeps the existing order and
        only fills in sequential numbers — appending teams that have none yet
        (e.g. just created) at the end — so every assigned team always has a
        pairing number. RANDOM keeps the existing relative order and drops
        newly-added teams into random positions; the rating modes fully
        re-sort."""
        if self._has_stored_pairings:
            return
        teams = list(self.teams)
        if not teams:
            return
        mode = self.team_sort_mode
        if mode == TeamSortMode.MANUAL:
            # Preserve the current order; unnumbered (new) teams sort last.
            ordered = sorted(
                teams,
                key=lambda t: (
                    t.pairing_number if t.pairing_number is not None else float('inf'),
                    t.name.lower(),
                ),
            )
        elif mode == TeamSortMode.TEAM_AVERAGE_RATING:
            ordered = sorted(
                teams,
                key=lambda t: (-(t.average_rating or 0), t.name.lower()),
            )
        elif mode == TeamSortMode.LINEUP_AVERAGE_RATING:
            ordered = sorted(
                teams,
                key=lambda t: (
                    -(t.lineup_average_rating(1) or 0),
                    t.name.lower(),
                ),
            )
        else:  # RANDOM
            ordered = self._random_team_order(teams)
        for index, team in enumerate(ordered, start=1):
            if team.pairing_number != index:
                team.set_pairing_number(index, database)

    @staticmethod
    def _random_team_order(teams: list['Team']) -> list['Team']:
        import random

        placed = sorted(
            (t for t in teams if t.pairing_number is not None),
            key=lambda t: t.pairing_number or 0,
        )
        newcomers = [t for t in teams if t.pairing_number is None]
        if not placed:
            # Fresh shuffle (mode just switched to random).
            order = list(teams)
            random.shuffle(order)
            return order
        # Insert each newcomer at a random position among the existing
        # order; existing teams keep their relative order.
        order = list(placed)
        for team in newcomers:
            order.insert(random.randint(0, len(order)), team)
        return order

    @property
    def rule_set_managed_tie_breaks(self) -> bool:
        """True iff the tournament has a rule set that imposes a
        tie-break list for the current pairing system. The tie-break
        editor renders read-only in that case."""
        rule_set = self.rule_set
        if rule_set is None:
            return False
        try:
            system_id = self.pairing_system.id
        except KeyError:
            return False
        return bool(rule_set.tie_breaks_for_pairing(system_id))

    @cached_property
    def match_points(self) -> dict[Result, float]:
        """Points awarded for a team match outcome, indexed by `Result`.
        Empty dict for individual tournaments. The stored ``match_points`` dict
        only carries overrides; Olympiad defaults (2/1/0) fill in the rest.

        PAB default depends on the pairing system: Team Swiss defaults
        to DRAW points (avoids over-rewarding an odd team out and
        matches Olympiad practice for unopposed teams); other team
        systems (round-robin, Molter) keep WIN as the PAB default,
        though they rarely produce PABs in practice. Forfeit handling
        is separate."""
        from data.pairings.systems import TeamSwissPairingSystem

        if not self.is_team_tournament:
            return {}
        raw = self.stored_tournament.match_points or {}
        win = float(raw.get(Result.WIN.value, 2.0))
        draw = float(raw.get(Result.DRAW.value, 1.0))
        pab_default = draw if self.pairing_system == TeamSwissPairingSystem() else win
        return {
            Result.WIN: win,
            Result.DRAW: draw,
            Result.LOSS: float(raw.get(Result.LOSS.value, 0.0)),
            Result.PAIRING_ALLOCATED_BYE: float(
                raw.get(Result.PAIRING_ALLOCATED_BYE.value, pab_default)
            ),
        }

    @property
    def primary_score(self) -> 'ScoreType':
        """Score basis used as primary (FIDE 1.2.1). Default: match points
        for team tournaments; not used for individual tournaments."""
        raw = self.stored_tournament.primary_score
        if raw:
            return ScoreType(raw)
        return ScoreType.MATCH_POINTS

    @property
    def secondary_score(self) -> 'ScoreType':
        """The score basis that isn't the primary — derived, not chosen:
        "The rules of the competition shall state which, between 'match
        points' and 'game points', is called 'primary score'" (FIDE Swiss
        Team Pairing System §1.2.1), the other one being the secondary."""
        if self.primary_score == ScoreType.MATCH_POINTS:
            return ScoreType.GAME_POINTS
        return ScoreType.MATCH_POINTS

    @property
    def round_robin_participation_rule(self) -> bool:
        """FIDE 6.6: whether round-robin players who completed less than 50%
        of their games are dropped from the final standings (and their games
        excluded from opponents' tie-breaks). Off for tournaments created
        before the rule existed, so their standings stay unchanged."""
        return bool(self.stored_tournament.round_robin_participation_rule)

    @property
    def secondary_score_for_colours(self) -> bool:
        """Whether the secondary score breaks ties when deciding which
        team is the "first team" for colour allocation (§1.2.1, §4.3).
        Default: on, per §1.2.2."""
        return bool(self.stored_tournament.secondary_score_for_colours)

    @property
    def team_colour_type(self) -> TeamColourType:
        """FIDE C.04.6 §1.7 colour-allocation rule. Default: Type A
        (board-by-board flip)."""
        raw = self.stored_tournament.team_colour_type
        if raw:
            return TeamColourType(raw)
        return TeamColourType.A

    @property
    def color_pattern(self) -> str | None:
        return self.stored_tournament.color_pattern

    def stored_point_adjustment(
        self, team_id: int, round_: int
    ) -> 'StoredTeamPointAdjustment | None':
        """The stored manual adjustment row for (team, round), or None."""
        for adj in self.stored_tournament.stored_team_point_adjustments:
            if adj.team_id == team_id and adj.round_ == round_:
                return adj
        return None

    def manual_point_adjustment(self, team_id: int, round_: int) -> tuple[float, float]:
        """Stored manual (MP, GP) bonus/penalty for (team, round)."""
        adj = self.stored_point_adjustment(team_id, round_)
        return (adj.mp_delta, adj.gp_delta) if adj else (0.0, 0.0)

    def rule_set_point_adjustment(
        self, team_id: int, round_: int
    ) -> 'PointAdjustment | None':
        """Rule-set-imposed adjustment for (team, round), or None."""
        rule_set = self.rule_set
        if rule_set is None:
            return None
        team = self.event.teams_by_id.get(team_id)
        if team is None:
            return None
        return rule_set.team_point_adjustment(team, round_)

    def effective_point_adjustment(
        self, team_id: int, round_: int
    ) -> tuple[float, float]:
        """Combined manual + rule-set (MP, GP) adjustment for the team's
        round. Folded into standings, tie-break records, screens and the
        TRF 299 export."""
        mp, gp = self.manual_point_adjustment(team_id, round_)
        rule_set_adjustment = self.rule_set_point_adjustment(team_id, round_)
        if rule_set_adjustment is not None:
            mp += rule_set_adjustment.mp
            gp += rule_set_adjustment.gp
        return mp, gp

    def set_manual_point_adjustment(
        self,
        team_id: int,
        round_: int,
        mp_delta: float,
        gp_delta: float,
        reason: str | None,
        database: 'EventDatabase',
    ) -> None:
        """Upsert the manual (MP, GP) adjustment for (team, round) and
        keep the in-memory stored list in sync."""
        database.set_stored_team_point_adjustment(
            self.id, team_id, round_, mp_delta, gp_delta, reason
        )
        adjustments = self.stored_tournament.stored_team_point_adjustments
        adjustments[:] = [
            adjustment
            for adjustment in adjustments
            if not (adjustment.team_id == team_id and adjustment.round_ == round_)
        ]
        if mp_delta or gp_delta or reason:
            adjustments.append(
                StoredTeamPointAdjustment(
                    id=None,
                    tournament_id=self.id,
                    team_id=team_id,
                    round_=round_,
                    mp_delta=mp_delta,
                    gp_delta=gp_delta,
                    reason=reason,
                )
            )

    def stored_player_point_adjustment(
        self, player_id: int, round_: int
    ) -> 'StoredPlayerPointAdjustment | None':
        """The stored manual adjustment row for (player, round), or None."""
        for adjustment in self.stored_tournament.stored_player_point_adjustments:
            if adjustment.player_id == player_id and adjustment.round_ == round_:
                return adjustment
        return None

    def player_point_adjustment(self, player_id: int, round_: int) -> float:
        """Manual bonus / penalty points for (player, round) in an
        individual tournament. Team events adjust whole teams instead, so
        this is always zero there.

        Unlike the team counterpart there is no rule-set contribution:
        rule sets award match points, which individual tournaments don't
        have."""
        if self.is_team_tournament:
            return 0.0
        adjustment = self.stored_player_point_adjustment(player_id, round_)
        return adjustment.delta if adjustment else 0.0

    def player_point_adjustment_total(self, player_id: int, after_round: int) -> float:
        """Every adjustment for the player through ``after_round``."""
        if self.is_team_tournament:
            return 0.0
        return sum(
            adjustment.delta
            for adjustment in self.stored_tournament.stored_player_point_adjustments
            if adjustment.player_id == player_id and adjustment.round_ <= after_round
        )

    def set_manual_player_point_adjustment(
        self,
        player_id: int,
        round_: int,
        delta: float,
        reason: str | None,
        database: 'EventDatabase',
    ) -> None:
        """Upsert the manual adjustment for (player, round) and keep the
        in-memory stored list in sync."""
        database.set_stored_player_point_adjustment(
            self.id, player_id, round_, delta, reason
        )
        adjustments = self.stored_tournament.stored_player_point_adjustments
        adjustments[:] = [
            adjustment
            for adjustment in adjustments
            if not (adjustment.player_id == player_id and adjustment.round_ == round_)
        ]
        if delta or reason:
            adjustments.append(
                StoredPlayerPointAdjustment(
                    id=None,
                    tournament_id=self.id,
                    player_id=player_id,
                    round_=round_,
                    delta=delta,
                    reason=reason,
                )
            )

    def _point_adjustment_bound(self, after_round: int | None) -> int:
        """Highest round whose adjustments count: the explicit bound, or
        the current round for live views."""
        bound = after_round if after_round is not None else self.current_round
        return bound or 0

    def _apply_point_adjustments_to_standings(
        self, standings: dict[int, dict[str, Any]], after_round: int | None
    ) -> None:
        bound = self._point_adjustment_bound(after_round)
        for round_ in range(1, bound + 1):
            for team_id, entry in standings.items():
                mp_adj, gp_adj = self.effective_point_adjustment(team_id, round_)
                entry['mp'] += mp_adj
                entry['gp'] += gp_adj

    def team_standings(self, *, after_round: int | None = None) -> list[dict[str, Any]]:
        """Compute team standings for this tournament, sorted by the
        configured ranking criteria in order. The primary score is one of
        them — the Points tie-break — rather than an implicit first key,
        so that its position can be chosen; the secondary score is opted
        into with MPvGP. See :func:`base_key` below.
        Each entry: {team, mp, gp, played, wins, draws, losses, rank}.

        ``after_round`` bounds which rounds count: only matches up to
        and including it are tallied. ``None`` (default) counts every
        stored match — the live standings. A ranking document passes
        the finished round it's printing for, so a paired-but-unfinished
        round isn't counted (played / points stay at the prior round).

        For ``paired_by_team`` systems (team-vs-team blocks), match
        points and game points come from the ``team_board`` records.
        For flat fixed-table systems (e.g. FFE Molter — players from
        different teams paired directly with no team_board envelope),
        a team's points are the sum of its players' individual game
        points across all boards in the tournament. Match-point and
        win/draw/loss tallies aren't meaningful in that mode."""
        match_points = self.match_points

        def wrap_tie_break_values(
            tbs: list, values: list[float]
        ) -> list[TieBreakValue]:
            """Wrap raw tie-break floats as ``TieBreakValue`` so consumers
            share one display path (absolute-value flag, rank-delta arrows)
            instead of each re-implementing it."""
            wrapped: list[TieBreakValue] = []
            for tb, value in zip(tbs, values):
                tbv = TieBreakValue(tb, value)
                if tb.display_rank_delta:
                    tbv.rank_progress = int(round(value))
                wrapped.append(tbv)
            return wrapped

        standings: dict[int, dict[str, Any]] = {}
        for team in self.event.sorted_teams:
            if team.tournament_id != self.id:
                continue
            standings[team.id] = {
                'team': team,
                'mp': 0.0,
                'gp': 0.0,
                'played': 0,
                'wins': 0,
                'draws': 0,
                'losses': 0,
            }
        win_mp = match_points.get(Result.WIN, 2.0)
        draw_mp = match_points.get(Result.DRAW, 1.0)
        loss_mp = match_points.get(Result.LOSS, 0.0)
        pab_mp = match_points.get(Result.PAIRING_ALLOCATED_BYE, win_mp)
        # Flat fixed-table fallback (no team_boards): sum player points
        # straight into team totals. Use ``team_game_points`` so the
        # ``gp_*`` override applies to team scoring here too.
        if not self.team_boards_by_id:
            team_game_points = self.team_game_points
            for board in self.boards_by_id.values():
                if after_round is not None and board.round > after_round:
                    continue
                w_id = board.stored_board.white_player_id
                w_player = self.event.players_by_id.get(w_id) if w_id else None
                if w_player and w_player.team_id in standings:
                    standings[w_player.team_id]['gp'] += (
                        board.white_pairing.result.points(team_game_points)
                    )
                    standings[w_player.team_id]['played'] += 1
                if board.stored_board.black_player_id is not None:
                    b_player = self.event.players_by_id.get(
                        board.stored_board.black_player_id
                    )
                    if b_player and b_player.team_id in standings:
                        standings[b_player.team_id]['gp'] += (
                            board.black_pairing.result.points(team_game_points)
                        )
                        standings[b_player.team_id]['played'] += 1
            self._apply_point_adjustments_to_standings(standings, after_round)
            rows = list(standings.values())
            # Pad to the team tie-break count so consumers that render a
            # column per team tie-break (ranking document / screen table)
            # never index past the end — they aren't computed in this flat
            # fixed-table mode, so they show as zero.
            flat_team_tie_breaks = [
                tb for tb in self.tie_breaks if tb.supports_team_mode
            ]
            for row in rows:
                row['tie_break_values'] = wrap_tie_break_values(
                    flat_team_tie_breaks, [0.0] * len(flat_team_tie_breaks)
                )
            rows.sort(
                key=lambda e: (
                    -e['gp'],
                    e['team'].pairing_number
                    if e['team'].pairing_number is not None
                    else float('inf'),
                    e['team'].name.lower(),
                )
            )
            for rank, entry in enumerate(rows, 1):
                entry['rank'] = rank
            return rows
        team_player_count = float(self.team_player_count or 0)
        win_gp_per_player = Result.WIN.point_value
        draw_gp_per_player = Result.DRAW.point_value
        absent_gp_per_player = self.team_game_points[Result.ZERO_POINT_BYE]
        excluded_team_ids = {
            team.id for team in self.teams if team.is_excluded_from_standings
        }
        for team_board in self.team_boards_by_id.values():
            if after_round is not None and team_board.round > after_round:
                continue
            stb = team_board.stored_team_board
            if stb.team_a_id in excluded_team_ids or stb.team_b_id in excluded_team_ids:
                continue
            a_gp, b_gp = team_board.game_points
            if stb.team_b_id is None:
                ent = standings.get(stb.team_a_id)
                if ent is None:
                    continue
                if stb.bye_type in (None, TeamByeType.PAB) and self.team_bye_is_rest:
                    # Round-robin rest game: not played, no points.
                    continue
                ent['played'] += 1
                # Distinguish bye types: PAB is the only one that
                # awards "as-if drew the match"; the manual byes mirror
                # individual byes scaled by team_player_count.
                match stb.bye_type:
                    case TeamByeType.ZPB:
                        ent['mp'] += loss_mp
                        # Team-level forfeit: every board counts as a
                        # forfeited game, scored at the absent-board game
                        # point value (the gp_zpb override, otherwise 0).
                        ent['gp'] += team_player_count * absent_gp_per_player
                        ent['losses'] += 1
                    case TeamByeType.HPB:
                        ent['mp'] += draw_mp
                        ent['gp'] += team_player_count * draw_gp_per_player
                        ent['draws'] += 1
                    case TeamByeType.FPB:
                        ent['mp'] += win_mp
                        ent['gp'] += team_player_count * win_gp_per_player
                        ent['wins'] += 1
                    case _:
                        # ``None`` / ``PAB`` → engine PAB.
                        ent['mp'] += pab_mp
                        ent['gp'] += self.team_pab_game_points
                        ent['wins'] += 1
                continue
            ent_a = standings.get(stb.team_a_id)
            ent_b = standings.get(stb.team_b_id)
            if ent_a:
                ent_a['played'] += 1
                ent_a['gp'] += a_gp
            if ent_b:
                ent_b['played'] += 1
                ent_b['gp'] += b_gp
            # Match result follows the effective game points (board + this
            # round's penalties/bonuses); the deltas are added to the totals
            # separately by _apply_point_adjustments_to_standings below.
            a_gp_effective, b_gp_effective = team_board.effective_game_points
            if a_gp_effective > b_gp_effective:
                if ent_a:
                    ent_a['mp'] += win_mp
                    ent_a['wins'] += 1
                if ent_b:
                    ent_b['mp'] += loss_mp
                    ent_b['losses'] += 1
            elif a_gp_effective < b_gp_effective:
                if ent_a:
                    ent_a['mp'] += loss_mp
                    ent_a['losses'] += 1
                if ent_b:
                    ent_b['mp'] += win_mp
                    ent_b['wins'] += 1
            else:
                if ent_a:
                    ent_a['mp'] += draw_mp
                    ent_a['draws'] += 1
                if ent_b:
                    ent_b['mp'] += draw_mp
                    ent_b['draws'] += 1
        self._apply_point_adjustments_to_standings(standings, after_round)
        rows = list(standings.values())

        def base_key(entry: dict[str, Any]) -> tuple[float, ...]:
            """Nothing ranks ahead of the configured criteria.

            The primary score is one of them — the Points tie-break —
            rather than an implicit prefix, so that its position can be
            chosen (TRF26 record 212). The secondary score has never been
            implicit either: it is opted into with MPvGP. A tournament
            whose list holds neither ranks on its tie-breaks alone.
            """
            return ()

        for row in rows:
            row['tie_break_values'] = []

        team_tie_breaks = [tb for tb in self.tie_breaks if tb.supports_team_mode]
        if team_tie_breaks:
            tie_break_round = (
                after_round if after_round is not None else self.current_round
            )
            team_records_list = self.team_records(after_round=tie_break_round)
            records_by_id = {r.team_id: r for r in team_records_list}
            context = self.team_tie_break_context()
            after_round = tie_break_round
            for tb in team_tie_breaks:
                if tb.display_rank_delta and isinstance(tb, TeamTieBreak):
                    # Group-level resolution (EDE): cluster rows by the
                    # sort key so far, then ask the tie-break to assign
                    # rank-deltas within each still-tied group.
                    rows.sort(
                        key=lambda e: (
                            base_key(e) + tuple(-v for v in e['tie_break_values'])
                        )
                    )
                    groups: list[list[dict[str, Any]]] = []
                    current: list[dict[str, Any]] = []
                    current_key: tuple[float, ...] | None = None
                    for row in rows:
                        key = base_key(row) + tuple(-v for v in row['tie_break_values'])
                        if key != current_key:
                            if current:
                                groups.append(current)
                            current = [row]
                            current_key = key
                        else:
                            current.append(row)
                    if current:
                        groups.append(current)
                    tied = [
                        [
                            records_by_id[r['team'].id]
                            for r in g
                            if r['team'].id in records_by_id
                            and not r['team'].is_excluded_from_standings
                        ]
                        for g in groups
                        if len(g) > 1
                    ]
                    values_map: dict[int, float] = (
                        tb.compute_all_team_values(
                            tied,
                            records_by_id,
                            context,
                            after_round=after_round,
                        )
                        if tied
                        else {}
                    )
                    for row in rows:
                        row['tie_break_values'].append(
                            float(values_map.get(row['team'].id, 0.0))
                        )
                else:
                    # Scalar tie-break — compute one value per team.
                    for row in rows:
                        rec = records_by_id.get(row['team'].id)
                        if rec is None:
                            row['tie_break_values'].append(0.0)
                            continue
                        value = tb.compute_team_value(
                            rec,
                            records_by_id,
                            context,
                            after_round=after_round,
                        )
                        row['tie_break_values'].append(float(value))

        rows.sort(
            key=lambda e: (
                # Teams excluded from the standings (FIDE 6.6) rank last,
                # regardless of score, so the competitors keep a contiguous
                # ranking. They stay in the crosstable for the record.
                e['team'].is_excluded_from_standings,
                base_key(e)
                + tuple(-v for v in e['tie_break_values'])
                + (
                    e['team'].pairing_number
                    if e['team'].pairing_number is not None
                    else float('inf'),
                    e['team'].name.lower(),
                ),
            )
        )
        for rank, entry in enumerate(rows, 1):
            entry['rank'] = rank
        for row in rows:
            row['tie_break_values'] = wrap_tie_break_values(
                team_tie_breaks, row['tie_break_values']
            )
        return rows

    @cached_property
    def teams_by_id(self) -> dict[int, 'Team']:
        return {
            team.id: team
            for team in self.event.teams_by_id.values()
            if team.tournament_id == self.id
        }

    @property
    def teams(self) -> Collection['Team']:
        return self.teams_by_id.values()

    @cached_property
    def team_count(self) -> int:
        return len(self.teams_by_id)

    @cached_property
    def sorted_teams(self) -> list['Team']:
        return sorted(self.teams, key=attrgetter('name'))

    @property
    def teams_in_pairing_order(self) -> list['Team']:
        """Teams ordered by pairing number then id — the same order the
        fixed-table letters (A, B, …) follow, so a letter-labelled list
        reads in sequence."""
        return sorted(
            self.teams,
            key=lambda team: (
                team.pairing_number
                if team.pairing_number is not None
                else float('inf'),
                team.id,
            ),
        )

    @cached_property
    def teams_by_pairing_number(self) -> dict[int, 'Team']:
        return {
            team.pairing_number: team
            for team in self.teams
            if team.pairing_number is not None
        }

    # -------------------------------------------------------------------------
    # Prohibited pairings
    # -------------------------------------------------------------------------

    @property
    def prohibited_pairing_forced_by_rule_set(self) -> 'tuple[str, bool] | None':
        """The ``(dimension_id, is_hard)`` the tournament's rule set
        imposes, or ``None`` when the configuration is free."""
        rule_set = self.rule_set
        return rule_set.forced_prohibited_pairing if rule_set else None

    @property
    def prohibited_pairing_dimension_id(self) -> str | None:
        forced = self.prohibited_pairing_forced_by_rule_set
        if forced is not None:
            return forced[0]
        return self.stored_tournament.prohibited_pairing_dimension

    @property
    def prohibited_pairing_dimension_is_hard(self) -> bool:
        forced = self.prohibited_pairing_forced_by_rule_set
        if forced is not None:
            return forced[1]
        return self.stored_tournament.prohibited_pairing_dimension_is_hard

    def prohibited_pairing_dimensions(self) -> 'list[ProhibitedPairingDimension]':
        """All grouping dimensions applicable to this tournament: the
        core ones plus any contributed by enabled plugins, filtered to
        match this tournament's individual/team nature."""
        from data.prohibited_pairings import core_prohibited_pairing_dimensions
        from plugins.manager import plugin_manager

        dimensions = list(core_prohibited_pairing_dimensions())
        for plugin_result in plugin_manager.hook_for_event(
            self.event, 'get_prohibited_pairing_dimensions'
        )():
            if plugin_result:
                dimensions.extend(plugin_result)
        return [d for d in dimensions if d.is_team == self.is_team_tournament]

    def prohibited_pairing_dimension(self) -> 'ProhibitedPairingDimension | None':
        dimension_id = self.prohibited_pairing_dimension_id
        if dimension_id is None:
            return None
        for dimension in self.prohibited_pairing_dimensions():
            if dimension.id == dimension_id:
                return dimension
        return None

    def set_prohibited_pairing_config(
        self,
        dimension_id: str | None,
        dimension_is_hard: bool,
        database: 'EventDatabase',
    ):
        self.stored_tournament.prohibited_pairing_dimension = dimension_id or None
        self.stored_tournament.prohibited_pairing_dimension_is_hard = dimension_is_hard
        database.update_stored_tournament(self.stored_tournament)

    @property
    def _prohibited_members(self) -> list:
        """The members the dimension buckets — players for an individual
        tournament, teams for a team one."""
        if self.is_team_tournament:
            return list(self.teams)
        return list(self.tournament_players)

    def _member_id(self, member) -> int:
        return member.id

    def manual_prohibited_pairing_groups(
        self,
    ) -> 'list[StoredProhibitedPairingGroup]':
        return [
            group
            for group in self.stored_tournament.stored_prohibited_pairing_groups
            if group.round_ is None
        ]

    def set_manual_prohibited_pairing_groups(
        self,
        groups: list[tuple[bool, list[int]]],
        database: 'EventDatabase',
    ):
        database.replace_manual_prohibited_pairing_groups(self.id, groups)
        self.stored_tournament.stored_prohibited_pairing_groups = (
            database.load_tournament_stored_prohibited_pairing_groups(self.id)
        )

    def dimension_prohibited_pairing_buckets(self) -> list[tuple[str, list[int]]]:
        """Live dimension buckets of ≥2 members, each ``(key, member_ids)``
        where ``key`` is the shared affiliation value (club / federation
        / … name). Empty when no dimension is selected."""
        dimension = self.prohibited_pairing_dimension()
        if dimension is None:
            return []
        buckets: dict[str, list[int]] = {}
        for member in self._prohibited_members:
            key = dimension.group_key(member)
            if key is None:
                continue
            buckets.setdefault(key, []).append(self._member_id(member))
        return [
            (key, member_ids)
            for key, member_ids in buckets.items()
            if len(member_ids) >= 2
        ]

    def dimension_prohibited_pairing_groups(self) -> list[tuple[bool, list[int]]]:
        """Live dimension-derived groups for the current config, each
        ``(is_hard, member_ids)``. Empty when no dimension is selected."""
        is_hard = self.prohibited_pairing_dimension_is_hard
        return [
            (is_hard, member_ids)
            for _key, member_ids in self.dimension_prohibited_pairing_buckets()
        ]

    def computed_prohibited_pairing_groups(
        self, round_: int | None = None
    ) -> list[tuple[bool, list[int]]]:
        """The live groups for the current config — dimension-derived
        plus the manual template groups. Each is ``(is_hard,
        member_ids)``. This is what a full pairing snapshots.

        When ``round_`` is given, plugin-contributed dynamic groups for
        that round (the ``get_round_prohibited_pairing_groups`` hook —
        e.g. results-based protections) are merged in too."""
        groups: list[tuple[bool, list[int]]] = list(
            self.dimension_prohibited_pairing_groups()
        )
        for group in self.manual_prohibited_pairing_groups():
            if len(group.member_ids) >= 2:
                groups.append((group.is_hard, list(group.member_ids)))
        if round_ is not None:
            for rule_group in self.round_rule_prohibited_pairing_groups(round_):
                groups.append((rule_group.is_hard, list(rule_group.member_ids)))
        return groups

    def round_rule_prohibited_pairing_groups(
        self, round_: int
    ) -> 'list[RoundProhibitedPairingGroup]':
        """Named prohibited-pairing groups contributed by plugins for
        ``round_`` (the ``get_round_prohibited_pairing_groups`` hook). Kept
        named (unlike :meth:`computed_prohibited_pairing_groups`) so the
        prohibited-pairings modal can label them before the round is paired.
        Groups of fewer than two members are dropped."""
        from plugins.manager import plugin_manager

        groups: 'list[RoundProhibitedPairingGroup]' = []
        for plugin_result in plugin_manager.hook_for_event(
            self.event, 'get_round_prohibited_pairing_groups'
        )(tournament=self, round_=round_):
            for group in plugin_result or []:
                if len(group.member_ids) >= 2:
                    groups.append(group)
        return groups

    def prohibited_pairing_snapshot(
        self, round_: int
    ) -> 'list[StoredProhibitedPairingGroup]':
        return [
            group
            for group in self.stored_tournament.stored_prohibited_pairing_groups
            if group.round_ == round_
        ]

    def prohibited_pairing_count_for_round(self, round_: int) -> int:
        """Number of prohibition groups in effect for ``round_``: the frozen
        snapshot once the round is paired, otherwise the live configured
        groups. Drives the round's prohibited-pairings button indicator."""
        snapshot = self.prohibited_pairing_snapshot(round_)
        if snapshot:
            return sum(1 for group in snapshot if len(group.member_ids) >= 2)
        return len(self.computed_prohibited_pairing_groups(round_))

    def _member_pairing_number(self, member_id: int) -> int | None:
        """The TRF pairing number used in 260 records — a team TPN in
        team mode, a player pairing number otherwise."""
        if self.is_team_tournament:
            team = self.teams_by_id.get(member_id)
            return team.pairing_number if team else None
        tp = self.tournament_players_by_id.get(member_id)
        return tp.pairing_number if tp else None

    def _prohibited_member_weakness_ranks(self, after_round: int) -> dict[int, int]:
        """Member id → standing position entering the round (1 = top).
        Soft prohibitions are relaxed from the bottom of this order, so an
        unavoidable clash lands on the players/teams doing worst *now*. In
        round 1 the standings collapse to the initial seed."""
        if self.is_team_tournament:
            return {
                row['team'].id: row['rank']
                for row in self.team_standings(after_round=after_round)
            }
        return {
            tp.id: rank
            for rank, tp in self.compute_tournament_player_ranks(
                after_round=after_round
            ).items()
        }

    def prohibited_pairing_relaxation_inputs(
        self, after_round: int
    ) -> tuple[list[list[int]], list[list[int]], dict[int, int]]:
        """Split the round's configured prohibitions into the always-kept
        hard groups and the soft groups, plus each member's standing rank
        (1 = top) entering the round — the basis for soft relaxation.

        Relaxation is member-level (*protect the top N*), so there is no
        pairwise expansion: a soft group is relaxed by splitting its
        members at a rank cutoff. Skips the standings entirely when there
        are no soft groups."""
        groups = self.computed_prohibited_pairing_groups(after_round + 1)
        hard_groups: list[list[int]] = [
            list(member_ids) for is_hard, member_ids in groups if is_hard
        ]
        soft_groups: list[list[int]] = [
            list(member_ids) for is_hard, member_ids in groups if not is_hard
        ]
        if not soft_groups:
            return hard_groups, [], {}
        return (
            hard_groups,
            soft_groups,
            self._prohibited_member_weakness_ranks(after_round),
        )

    def prohibited_pairing_applied_lines(
        self,
        hard_groups: list[list[int]],
        soft_groups: list[list[int]],
        protect_rank: int,
        rank_by_member: dict[int, int],
        round_: int,
    ) -> 'list[TrfProhibitedPairing]':
        """The round's effective 260 lines. Hard groups become one
        N-member line each. Each soft group is relaxed at ``protect_rank``:
        its members split into protected (rank ``<= protect_rank``) and
        unprotected, and the surviving prohibitions — every pairing
        incident to a protected member — are emitted as compact clique
        lines (never the pairwise expansion). Members with no pairing
        number drop out."""
        from data.input_output.trf.trf_data import TrfProhibitedPairing

        lines: list['TrfProhibitedPairing'] = []
        for group in hard_groups:
            numbers = [
                n
                for n in (self._member_pairing_number(m) for m in group)
                if n is not None
            ]
            if len(numbers) >= 2:
                lines.append(
                    TrfProhibitedPairing(
                        first_round=round_, last_round=round_, pairing_numbers=numbers
                    )
                )
        bottom = max(rank_by_member.values(), default=0) + 1
        for group in soft_groups:
            protected = [
                m for m in group if rank_by_member.get(m, bottom) <= protect_rank
            ]
            unprotected = [
                m for m in group if rank_by_member.get(m, bottom) > protect_rank
            ]
            lines.extend(self._soft_clique_lines(protected, unprotected, round_))
        return lines

    def _soft_clique_lines(
        self, protected: list[int], unprotected: list[int], round_: int
    ) -> 'list[TrfProhibitedPairing]':
        """The surviving prohibitions of one relaxed soft group, as cliques.
        Pairings incident to a protected member survive (a protected member
        must avoid everyone in the group); pairings between two unprotected
        members are relaxed. That edge set is covered by ``protected ∪ {u}``
        for each unprotected ``u`` (or just ``protected`` when none are
        unprotected) — one line per unprotected member, not one per pair."""
        from data.input_output.trf.trf_data import TrfProhibitedPairing

        protected_numbers = [
            n
            for n in (self._member_pairing_number(m) for m in protected)
            if n is not None
        ]
        if not protected_numbers:
            return []
        if not unprotected:
            if len(protected_numbers) < 2:
                return []
            return [
                TrfProhibitedPairing(
                    first_round=round_,
                    last_round=round_,
                    pairing_numbers=protected_numbers,
                )
            ]
        lines: list['TrfProhibitedPairing'] = []
        for member in unprotected:
            number = self._member_pairing_number(member)
            if number is None:
                continue
            lines.append(
                TrfProhibitedPairing(
                    first_round=round_,
                    last_round=round_,
                    pairing_numbers=protected_numbers + [number],
                )
            )
        return lines

    def prohibited_pairing_was_relaxed(self, round_: int) -> bool:
        """True iff this round actually released a soft separation — some
        soft member ranked below the chosen ``protect_rank``. When everyone
        could be protected, ``resolve_soft_protect_rank`` stores the bottom
        rank (full protection), which is *not* a relaxation; the display
        must not announce one."""
        groups = self.prohibited_pairing_snapshot(round_)
        protect_rank = next(
            (g.protect_rank for g in groups if g.protect_rank is not None), None
        )
        if protect_rank is None:
            return False
        ranks = self._prohibited_member_weakness_ranks(after_round=round_ - 1)
        bottom = max(ranks.values(), default=0) + 1
        return any(
            ranks.get(member, bottom) > protect_rank
            for group in groups
            if not group.is_hard
            for member in group.member_ids
        )

    def released_prohibited_pairing_members(self, round_: int) -> list[int]:
        """The soft members released this round (standing rank below the
        chosen ``protect_rank``) — flat and de-duplicated across all soft
        groups. These are the only ones that may now be paired against an
        affiliated opponent; everyone else kept all their soft separations.
        Ordered by standing rank (weakest last)."""
        groups = self.prohibited_pairing_snapshot(round_)
        protect_rank = next(
            (g.protect_rank for g in groups if g.protect_rank is not None), None
        )
        if protect_rank is None:
            return []
        ranks = self._prohibited_member_weakness_ranks(after_round=round_ - 1)
        bottom = max(ranks.values(), default=0) + 1
        released = {
            member
            for group in groups
            if not group.is_hard
            for member in group.member_ids
            if ranks.get(member, bottom) > protect_rank
        }
        return sorted(released, key=lambda member: ranks.get(member, bottom))

    def write_prohibited_pairing_snapshot(
        self, round_: int, protect_rank: int | None, database: 'EventDatabase'
    ):
        """Freeze the round's prohibited-pairing **groups** (the configured
        hard and soft groups that were the basis for this round's pairing)
        together with the soft-relaxation cutoff ``protect_rank`` chosen for
        the round. The configured groups drive the read-only modal; groups
        plus ``protect_rank`` let the TRF 260 export regenerate the exact
        effective set bbpPairings enforced — without persisting the (huge)
        pairwise expansion."""
        database.replace_round_prohibited_pairing_snapshot(
            self.id,
            round_,
            self.computed_prohibited_pairing_groups(round_),
            protect_rank,
        )
        self.stored_tournament.stored_prohibited_pairing_groups = (
            database.load_tournament_stored_prohibited_pairing_groups(self.id)
        )

    def delete_prohibited_pairing_snapshot(
        self, round_: int, database: 'EventDatabase'
    ):
        database.delete_round_prohibited_pairing_snapshot(self.id, round_)
        self.stored_tournament.stored_prohibited_pairing_groups = [
            group
            for group in self.stored_tournament.stored_prohibited_pairing_groups
            if group.round_ != round_
        ]

    def clear_team_cache(self):
        Utils.reset_cached_properties(
            self,
            'teams_by_id',
            'sorted_teams',
            'teams_by_pairing_number',
            'team_boards_by_id',
            'team_boards_by_round',
            'team_pairing_blocks',
        )

    @cached_property
    def team_boards_by_id(self) -> dict[int, TeamBoard]:
        return {
            stored_team_board.id: TeamBoard(self, stored_team_board)
            for stored_team_boards in (
                self.stored_tournament.stored_team_boards_by_round.values()
            )
            for stored_team_board in stored_team_boards
            if stored_team_board.id is not None
        }

    @cached_property
    def team_boards_by_round(self) -> dict[int, list[TeamBoard]]:
        result: dict[int, list[TeamBoard]] = {}
        for team_board in self.team_boards_by_id.values():
            result.setdefault(team_board.round, []).append(team_board)
        for round_team_boards in result.values():
            round_team_boards.sort(key=lambda tb: (tb.index is None, tb.index or 0))
        return result

    def get_round_team_boards(self, round_: int) -> list[TeamBoard]:
        return self.team_boards_by_round.get(round_, [])

    def team_tie_break_context(self) -> 'TeamTieBreakContext':
        """Snapshot the tournament parameters team tie-breaks need."""
        from data.tie_breaks.team_tie_breaks import TeamTieBreakContext

        match_points = self.match_points
        team_size = self.team_player_count or 0
        return TeamTieBreakContext(
            primary_score=self.primary_score,
            secondary_score=self.secondary_score,
            rounds=self.rounds,
            win_mp=match_points.get(Result.WIN, 2.0),
            draw_mp=match_points.get(Result.DRAW, 1.0),
            loss_mp=match_points.get(Result.LOSS, 0.0),
            team_player_count=team_size,
            draw_gp=team_size * self.draw_points,
            predetermined_pairings=self.pairing_system.predetermined_pairings,
            excluded_team_ids=frozenset(
                team.id for team in self.teams if team.is_excluded_from_standings
            ),
        )

    def _team_board_scores_for(
        self, team_board: TeamBoard, team_id: int
    ) -> tuple[float, ...]:
        """Per-board own scores for ``team_id`` in this match, ordered
        by board index. Required by board-weighted tie-breaks (FFE
        Berlin, knockout BC/TBR/BBE)."""
        scores: list[float] = []
        for board in sorted(team_board.boards, key=lambda b: b.index):
            white_team_id, _black_team_id = team_board.board_team_ids(board)
            white_pairing = board.optional_white_pairing
            white_pts = white_pairing.points if white_pairing is not None else 0.0
            black_pairing = board.optional_black_pairing
            black_pts = black_pairing.points if black_pairing is not None else 0.0
            scores.append(white_pts if white_team_id == team_id else black_pts)
        return tuple(scores)

    def _team_board_ratings_for(
        self, team_board: TeamBoard, team_id: int
    ) -> tuple[int | None, ...]:
        """Per-board own player ratings for ``team_id`` in this match,
        ordered by board index. Mirrors :meth:`_team_board_scores_for`
        for tie-breaks that weigh team standings by own-player rating.
        ``None`` for unrated players."""
        ratings: list[int | None] = []
        for board in sorted(team_board.boards, key=lambda b: b.index):
            white_id = board.stored_board.white_player_id
            black_id = board.stored_board.black_player_id
            white_player = (
                self.tournament_players_by_id.get(white_id) if white_id else None
            )
            black_player = (
                self.tournament_players_by_id.get(black_id) if black_id else None
            )
            own_player = (
                white_player
                if white_player and white_player.team_id == team_id
                else black_player
                if black_player and black_player.team_id == team_id
                else None
            )
            ratings.append(
                own_player.rating if own_player and own_player.rating else None
            )
        return tuple(ratings)

    def team_records(self, *, after_round: int | None = None) -> list['TeamRecord']:
        """Build :class:`TeamRecord` instances for every team in this
        tournament, suitable as input to the team tie-break compute API.

        Only PLAYED and PAB match types are currently emitted — the
        underlying data model does not yet capture team-level HPB / ZPB
        / forfeit semantics. When those land, this method should
        widen accordingly."""
        from data.tie_breaks.team_records import (
            TeamMatchRecord,
            TeamMatchType,
            TeamRecord,
        )

        if after_round is None:
            after_round = self.current_round
        match_points = self.match_points
        win_mp = match_points.get(Result.WIN, 2.0)
        draw_mp = match_points.get(Result.DRAW, 1.0)
        loss_mp = match_points.get(Result.LOSS, 0.0)
        pab_mp = match_points.get(Result.PAIRING_ALLOCATED_BYE, win_mp)

        totals_mp: dict[int, float] = {team.id: 0.0 for team in self.teams}
        totals_gp: dict[int, float] = {team.id: 0.0 for team in self.teams}
        matches_per_team: dict[int, list[TeamMatchRecord]] = {
            team.id: [] for team in self.teams
        }
        excluded_team_ids = {
            team.id for team in self.teams if team.is_excluded_from_standings
        }

        for team_board in self.team_boards_by_id.values():
            if team_board.round > after_round:
                continue
            stb = team_board.stored_team_board
            a_id = stb.team_a_id
            b_id = stb.team_b_id
            if a_id in excluded_team_ids or b_id in excluded_team_ids:
                continue
            a_gp, b_gp = team_board.game_points
            a_boards = self._team_board_scores_for(team_board, a_id)
            a_ratings = self._team_board_ratings_for(team_board, a_id)
            if b_id is None:
                if stb.bye_type in (None, TeamByeType.PAB) and self.team_bye_is_rest:
                    # Round-robin rest game: not a match — no record,
                    # no points, invisible to the tie-breaks.
                    continue
                # A PAB team still participates (it's present, just unpaired),
                # so OWN-ELO should reflect its strength. The bye envelope has
                # no boards, so take the round's line-up players' ratings.
                bye_team = self.event.teams_by_id.get(a_id)
                pab_ratings: tuple[int | None, ...]
                if bye_team is None:
                    pab_ratings = a_ratings
                else:
                    rating_list: list[int | None] = []
                    for player in bye_team.effective_round_slots(team_board.round):
                        tp = (
                            self.tournament_players_by_id.get(player.id)
                            if player is not None
                            else None
                        )
                        rating_list.append(tp.rating if tp and tp.rating else None)
                    pab_ratings = tuple(rating_list)
                matches_per_team[a_id].append(
                    TeamMatchRecord(
                        round_=team_board.round,
                        opponent_id=None,
                        own_mp=pab_mp,
                        own_gp=self.team_pab_game_points,
                        match_type=TeamMatchType.PAB,
                        board_scores=a_boards,
                        board_ratings=pab_ratings,
                    )
                )
                totals_mp[a_id] += pab_mp
                totals_gp[a_id] += self.team_pab_game_points
                continue
            # Match result follows the effective game points (board + this
            # round's penalties/bonuses); the deltas are added to own_gp /
            # totals by the loop below — here they only tip the comparison.
            a_gp_effective, b_gp_effective = team_board.effective_game_points
            if a_gp_effective > b_gp_effective:
                a_mp, b_mp = win_mp, loss_mp
            elif a_gp_effective < b_gp_effective:
                a_mp, b_mp = loss_mp, win_mp
            else:
                a_mp = b_mp = draw_mp
            b_boards = self._team_board_scores_for(team_board, b_id)
            b_ratings = self._team_board_ratings_for(team_board, b_id)
            matches_per_team[a_id].append(
                TeamMatchRecord(
                    round_=team_board.round,
                    opponent_id=b_id,
                    own_mp=a_mp,
                    own_gp=a_gp,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=a_boards,
                    board_ratings=a_ratings,
                )
            )
            matches_per_team[b_id].append(
                TeamMatchRecord(
                    round_=team_board.round,
                    opponent_id=a_id,
                    own_mp=b_mp,
                    own_gp=b_gp,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=b_boards,
                    board_ratings=b_ratings,
                )
            )
            totals_mp[a_id] += a_mp
            totals_gp[a_id] += a_gp
            totals_mp[b_id] += b_mp
            totals_gp[b_id] += b_gp

        # Fold bonus/penalty points into totals (used by total-based
        # tie-breaks and the secondary score) and into each round's match
        # record (so MP/GP-sum tie-breaks like points-for / differential
        # see them; board- and rating-based tie-breaks read board data and
        # are unaffected).
        from dataclasses import replace

        adjustment_bound = self._point_adjustment_bound(after_round)
        for team in self.teams:
            for round_ in range(1, adjustment_bound + 1):
                mp_adj, gp_adj = self.effective_point_adjustment(team.id, round_)
                if not mp_adj and not gp_adj:
                    continue
                totals_mp[team.id] += mp_adj
                totals_gp[team.id] += gp_adj
                team_matches = matches_per_team[team.id]
                for index, match in enumerate(team_matches):
                    if match.round_ == round_:
                        team_matches[index] = replace(
                            match,
                            own_mp=match.own_mp + mp_adj,
                            own_gp=match.own_gp + gp_adj,
                        )
                        break

        records: list[TeamRecord] = []
        for team in self.teams:
            records.append(
                TeamRecord(
                    team_id=team.id,
                    name=team.name,
                    total_mp=totals_mp[team.id],
                    total_gp=totals_gp[team.id],
                    matches=sorted(matches_per_team[team.id], key=lambda m: m.round_),
                    pairing_number=team.pairing_number,
                )
            )
        return records

    @cached_property
    def team_pairing_blocks(self) -> list[TeamPairingBlock]:
        return [
            TeamPairingBlock(self, stored_block)
            for stored_block in self.stored_tournament.stored_team_pairing_blocks
        ]

    def get_round_team_pairing_blocks(self, round_: int) -> list[TeamPairingBlock]:
        return [
            block
            for block in self.team_pairing_blocks
            if block.applies_to_round(round_)
        ]

    def is_team_pair_blocked(self, team_a_id: int, team_b_id: int, round_: int) -> bool:
        return any(
            block.involves(team_a_id, team_b_id)
            for block in self.get_round_team_pairing_blocks(round_)
        )

    # -------------------------------------------------------------------------
    # Pairing settings
    # -------------------------------------------------------------------------

    @property
    def stored_pairing_settings(self) -> dict[str, Any]:
        return self.stored_tournament.pairing_settings

    @cached_property
    def pairing_settings(self) -> dict[str, Any]:
        return {
            setting.id: setting.get_value(self)
            for setting in self.pairing_variation.settings
        }

    @property
    def pairing_warning_message(self) -> str | None:
        """Warning to display at global pairing level."""
        plugin_warning = plugin_manager.hook_for_event(
            self.event, 'get_tournament_pairing_warning_message'
        )(tournament=self)
        if plugin_warning:
            return plugin_warning
        return None

    def set_valid_pairing_settings(self):
        modified_settings: dict[str, Any] = {}
        for setting in self.pairing_variation.settings:
            if setting.is_valid(self):
                continue
            modified_settings[setting.id] = setting.to_stored_value(
                setting.default_value(self)
            )
        if modified_settings:
            self.update_pairing_settings(
                self.stored_pairing_settings | modified_settings
            )

    def update_pairing_settings(self, pairing_settings: dict[str, Any]):
        with EventDatabase(self.event.uniq_id, write=True) as database:
            database.set_tournament_pairing_settings(self.id, pairing_settings)
        self.stored_tournament.pairing_settings = pairing_settings
        Utils.reset_cached_properties(self, 'pairing_settings')

    def get_pairing_settings_data_errors(self, data: dict[str, str]) -> dict[str, Any]:
        return self.pairing_variation.get_settings_data_errors(self, data)

    # -------------------------------------------------------------------------
    # Tie-breaks
    # -------------------------------------------------------------------------

    def _tie_break_from_stored_tie_break(
        self, stored_tie_break: StoredTieBreak
    ) -> TieBreak | None:
        try:
            tie_break_type = TieBreakManager(self.event).get_type(stored_tie_break.type)
        except KeyError:
            logger.warning(
                'Tie-break [%s] not found for tournament [%s].',
                stored_tie_break.type,
                self.name,
            )
            return None
        options: list[TieBreakOption] = []
        manager = TieBreakOptionManager(self.event)
        for option_id, option_value in stored_tie_break.options.items():
            try:
                option_type = manager.get_type(option_id)
                options.append(option_type(option_value))
            except KeyError:
                logger.warning(
                    'Unknown tie-break option [%s] for tie-break [%d].',
                    option_id,
                    stored_tie_break.id,
                )
        return tie_break_type(options)

    @cached_property
    def tie_breaks_by_id(self) -> dict[int, TieBreak]:
        tie_breaks_by_id: dict[int, TieBreak] = {}
        for stored_tie_break in self.stored_tournament.stored_tie_breaks:
            if not (
                tie_break := (self._tie_break_from_stored_tie_break(stored_tie_break))
            ):
                continue
            id_ = stored_tie_break.id
            assert id_ is not None
            tie_breaks_by_id[id_] = tie_break
        return tie_breaks_by_id

    @property
    def tie_breaks(self) -> list[TieBreak]:
        """The ranking criteria, in order.

        A tournament that has none falls back to the points alone: the
        criteria decide the standings outright — the score is one of them
        rather than an implicit first key — so an empty list would
        otherwise rank nobody. Removing the Points tie-break from a list
        that holds others is a deliberate act and is honoured.
        """
        invalid_tie_break_ids = self.tie_breaks_invalid_messages.keys()
        configured = [
            tie_break
            for stored_id, tie_break in self.tie_breaks_by_id.items()
            if stored_id not in invalid_tie_break_ids
        ]
        return configured or self._default_tie_breaks

    @cached_property
    def _default_tie_breaks(self) -> list[TieBreak]:
        """Cached so the instance outlives the call: a
        :class:`TieBreakValue` keeps only a weak reference to its
        tie-break, so a freshly built one would be collected at once."""
        from data.tie_breaks.tie_breaks import PointsTieBreak

        return [PointsTieBreak()]

    @property
    def leads_on_points(self) -> bool:
        """Whether the standings rank on the points before anything else
        — the usual layout, and the only one Papi can express."""
        from data.tie_breaks.tie_breaks import PointsTieBreak

        tie_breaks = self.tie_breaks
        return bool(tie_breaks) and isinstance(tie_breaks[0], PointsTieBreak)

    @property
    def ranks_on_points(self) -> bool:
        """Whether the points are among the ranking criteria at all.

        They need not come first — another criterion may outrank them —
        but leaving them out altogether ranks the field on tie-breaks
        alone, which is almost never intended.
        """
        from data.tie_breaks.tie_breaks import PointsTieBreak

        return any(
            isinstance(tie_break, PointsTieBreak) for tie_break in self.tie_breaks
        )

    @property
    def only_ranks_on_points(self) -> bool:
        """Whether nothing has been chosen to break ties — the standings
        rank on the score and stop there. The state a tournament starts
        in, and the one a tie-break set may be applied to."""
        return len(self.tie_breaks_by_id) == 0 or (
            len(self.tie_breaks_by_id) == 1 and self.leads_on_points
        )

    def tie_break_acronym(self, tie_break: TieBreak) -> str:
        """The label for a criterion's column in the standings.

        The Points tie-break stands for the primary score, which in a
        team tournament is either the match points or the game points —
        the column says which rather than showing a generic label.
        """
        from data.tie_breaks.tie_breaks import PointsTieBreak

        if isinstance(tie_break, PointsTieBreak) and self.is_team_tournament:
            if self.primary_score == ScoreType.MATCH_POINTS:
                return _('MP *** TEAM RANKING HEADER MATCH POINTS')
            return _('GP *** TEAM RANKING HEADER GAME POINTS')
        return tie_break.acronym

    @property
    def leading_tie_break(self) -> TieBreak:
        """The criterion the standings rank on first — the points in the
        usual layout. Prize categories that rank by final standing are
        decided on it, so it is what they display."""
        return self.tie_breaks[0]

    @property
    def team_tie_breaks(self) -> list[TieBreak]:
        """The ranking criteria that yield a per-team value — the list
        :meth:`team_standings` computes values for, in the same order."""
        return [
            tie_break for tie_break in self.tie_breaks if tie_break.supports_team_mode
        ]

    @property
    def team_ranking_tie_breaks(self) -> list[TieBreak]:
        return [
            tie_break
            for tie_break in self.tie_breaks
            if tie_break.is_used_for_team_ranking
        ]

    @property
    def tie_breaks_with_invalid(self) -> Collection[TieBreak]:
        return self.tie_breaks_by_id.values()

    @property
    def tie_breaks_invalid_messages(self) -> dict[int, str]:
        """Get all the messages invalidating the tie-breaks, including the order errors."""
        invalid_messages_by_id: dict[int, str] = {}
        valid_tie_breaks: list[TieBreak] = []
        for stored_id, tie_break in self.tie_breaks_by_id.items():
            if message := self.tie_break_invalid_message(tie_break):
                invalid_messages_by_id[stored_id] = message
            elif not tie_break.allow_multiple and tie_break in valid_tie_breaks:
                # Untranslated, should not happen
                invalid_messages_by_id[stored_id] = (
                    'This tie-break is already used with the same modifiers'
                )
            elif (
                valid_tie_breaks
                and tie_break.allow_multiple
                and tie_break.id == valid_tie_breaks[-1].id
            ):
                invalid_messages_by_id[stored_id] = _(
                    "This tie-break can't be used twice in a row (ignored)."
                )
            else:
                valid_tie_breaks.append(tie_break)
        return invalid_messages_by_id

    def tie_break_invalid_message(self, tie_break: TieBreak) -> str | None:
        """Get a message explaining why a tie-break is invalid in the context of the tournament.
        Return or None if it is valid."""
        if not tie_break.is_compatible_with(self.pairing_system):
            return _(
                'This tie-break is not compatible with '
                'the pairing system [{pairing_system}] (ignored).'
            ).format(pairing_system=self.pairing_system.name)
        if not tie_break.allow_unrated_players and self.unrated_count:
            return _(
                'This tie-break is disabled when there are unrated players '
                'without estimated ratings ({count} in the tournament).'
            ).format(count=self.unrated_count)
        if not tie_break.allow_estimated_players and self.estimated_count:
            return _(
                'By default, this tie-break is disabled when there '
                'are unrated players ({count} in the tournament). '
                'You must specify that the player estimation is explained '
                'in the rules.'
            ).format(count=self.estimated_count)
        return None

    @property
    def tie_breaks_warning_message(self) -> str | None:
        """Warning to display at global tie-break level."""
        plugin_warning = plugin_manager.hook_for_event(
            self.event, 'get_tournament_tie_breaks_warning_message'
        )(tournament=self)
        if plugin_warning:
            return plugin_warning
        return None

    def reorder_tie_breaks(self, ordered_ids: list[int]):
        if len(ordered_ids) != len(self.tie_breaks_by_id):
            raise ValueError(f'{ordered_ids=}')
        for object_id in self.tie_breaks_by_id:
            if object_id not in ordered_ids:
                raise ValueError(
                    f'Tie break [{object_id}] not part of tournament [{self.name}].'
                )
        with EventDatabase(self.event.uniq_id, True) as database:
            self._set_tie_break_indexes(database, ordered_ids)
        self.tie_breaks_by_id = {
            object_id: self.tie_breaks_by_id[object_id] for object_id in ordered_ids
        }

    def _set_tie_break_indexes(self, database: EventDatabase, ordered_ids: list[int]):
        for index, object_id in enumerate(ordered_ids):
            stored_tie_break = self.tie_breaks_by_id[object_id].to_stored_value()
            stored_tie_break.id = object_id
            stored_tie_break.tournament_id = self.id
            stored_tie_break.index = index
            database.update_stored_tie_break(stored_tie_break)

    def add_tie_break(self, tie_break: TieBreak):
        stored_tie_break = tie_break.to_stored_value()
        stored_tie_break.tournament_id = self.id
        stored_tie_break.index = len(self.tie_breaks_by_id)
        with EventDatabase(self.event.uniq_id, write=True) as database:
            object_id = database.add_stored_tie_break(stored_tie_break)
        self.tie_breaks_by_id[object_id] = tie_break
        return tie_break

    def update_tie_break(self, tie_break_id: int, new_tie_break: TieBreak):
        if tie_break_id not in self.tie_breaks_by_id:
            raise ValueError(
                f'Tie-break [{tie_break_id}] not part of tournament [{self.name}].'
            )
        stored_tie_break = new_tie_break.to_stored_value()
        stored_tie_break.id = tie_break_id
        stored_tie_break.tournament_id = self.id
        stored_tie_break.index = list(self.tie_breaks_by_id).index(tie_break_id)
        with EventDatabase(self.event.uniq_id, write=True) as database:
            database.update_stored_tie_break(stored_tie_break)
        self.tie_breaks_by_id[tie_break_id] = new_tie_break

    def delete_tie_break(self, tie_break_id: int):
        if tie_break_id not in self.tie_breaks_by_id:
            raise ValueError(
                f'Tie-break [{tie_break_id}] not part of tournament [{self.name}].'
            )
        if len(self.tie_breaks_by_id) == 1:
            # The standings rank on the criteria listed and nothing else,
            # so the last one cannot go — there would be nothing to rank on.
            raise ValueError(
                f'Tie-break [{tie_break_id}] is the only ranking criterion '
                f'of tournament [{self.name}].'
            )
        with EventDatabase(self.event.uniq_id, True) as database:
            if self.tie_breaks_by_id[tie_break_id].is_manual:
                self.delete_manual_tie_break_values(database)
            database.delete_stored_tie_break(tie_break_id)
            del self.tie_breaks_by_id[tie_break_id]
            self._set_tie_break_indexes(database, list(self.tie_breaks_by_id))

    def delete_manual_tie_break_values(self, database: EventDatabase):
        manual_updates: dict[int, int | None] = {}
        for tournament_player in self.tournament_players:
            if tournament_player.manual_tiebreak is not None:
                tournament_player.stored_tournament_player.manual_tiebreak = None
                manual_updates[tournament_player.id] = None
        database.set_tournament_players_manual_tiebreak(self.id, manual_updates)

    @property
    def has_manual_tie_break_values(self) -> bool:
        return any(tie_break.is_manual for tie_break in self.tie_breaks) and any(
            player.manual_tiebreak is not None for player in self.tournament_players
        )

    # -------------------------------------------------------------------------
    # Criteria
    # -------------------------------------------------------------------------

    @cached_property
    def criteria(self) -> list[TournamentCriterion]:
        criteria: list[TournamentCriterion] = []
        for criteria_id, stored_value in self.stored_tournament.criteria.items():
            try:
                criterion = TournamentCriterionManager(self.event).get_object(
                    criteria_id
                )
                value = criterion.value_from_stored_value(stored_value)
                criterion.set_value(value)
                criteria.append(criterion)
            except KeyError:
                logger.exception(f'Unknown criterion [{criteria_id}].')
        return criteria

    @cached_property
    def num_players_not_matching_criteria(self) -> int:
        """Return the number of players matching all criteria of this tournament."""
        return sum(
            not player.matches_tournament_criteria for player in self.tournament_players
        )

    def player_matches_criteria(self, tournament_player: TournamentPlayer) -> bool:
        """Check if the player matches all criteria of this tournament."""
        return all(
            criterion.is_player_included_function(tournament_player)
            for criterion in self.criteria
        )

    @property
    def sorted_criteria(self) -> list[TournamentCriterion]:
        return sorted(self.criteria, key=lambda criteria: criteria.id)

    @property
    def criteria_string(self) -> str:
        return ', '.join(criterion.full_name for criterion in self.criteria)

    # -------------------------------------------------------------------------
    # Prize groups
    # -------------------------------------------------------------------------

    @property
    def prize_groups(self) -> Collection[PrizeGroup]:
        return self.prize_groups_by_id.values()

    @property
    def sorted_prize_groups(self) -> list[PrizeGroup]:
        return sorted(
            self.prize_groups,
            key=lambda group: (
                group.main_category is None,
                -len(group.categories),
                group.id,
            ),
        )

    def get_prizes_assigned_to_players_by_group_id_by_category_id(
        self,
        monetary_only: bool,
    ) -> dict[int, dict[int, list[AssignedPrize]]]:
        result: dict[int, dict[int, list[AssignedPrize]]] = {}
        for prize_group in self.sorted_prize_groups:
            prizes_assigned_to_players_by_category_id: dict[
                int, list[AssignedPrize]
            ] = prize_group.get_prizes_assigned_to_players_by_category_id(monetary_only)
            if prizes_assigned_to_players_by_category_id:
                result[prize_group.id] = prizes_assigned_to_players_by_category_id
        return result

    @property
    def main_prize_category(self) -> PrizeCategory | None:
        return next(
            (
                prize_group.main_category
                for prize_group in self.prize_groups
                if prize_group.main_category
            ),
            None,
        )

    @cached_property
    def prize_groups_by_id(self) -> dict[int, PrizeGroup]:
        prize_groups_by_id = {}
        for stored_prize_group in self.stored_tournament.stored_prize_groups:
            assert stored_prize_group.id is not None
            prize_groups_by_id[stored_prize_group.id] = PrizeGroup(
                self, stored_prize_group
            )
        return prize_groups_by_id

    def add_prize_group(self, stored_prize_group: StoredPrizeGroup) -> PrizeGroup:
        with EventDatabase(self.event.uniq_id, True) as database:
            object_id = database.add_stored_prize_group(stored_prize_group)
        stored_prize_group.id = object_id
        prize_group = PrizeGroup(self, stored_prize_group)
        self.prize_groups_by_id[object_id] = prize_group
        return prize_group

    def delete_prize_group(self, prize_group_id: int):
        with EventDatabase(self.event.uniq_id, True) as database:
            database.delete_stored_prize_group(prize_group_id)

        if prize_group_id in self.prize_groups_by_id:
            del self.prize_groups_by_id[prize_group_id]

    def get_unused_prize_group_name(self, base_name: str | None = None) -> str:
        return Utils.get_unused_item_name(
            base_name or _('New group'),
            (group.name for group in self.prize_groups),
        )

    @property
    def total_monetary_prize_value(self) -> float:
        return sum(group.total_monetary_value for group in self.prize_groups)

    @property
    def total_non_monetary_prize_value(self) -> float:
        return sum(group.total_non_monetary_value for group in self.prize_groups)

    def format_total_monetary_prize_value(self, currency: str) -> str:
        return Utils.currency_value_str(self.total_monetary_prize_value, currency)

    def format_total_non_monetary_prize_value(self, currency: str) -> str:
        return Utils.currency_value_str(self.total_non_monetary_prize_value, currency)

    # -------------------------------------------------------------------------
    # Players
    # -------------------------------------------------------------------------

    @property
    def tournament_players(self) -> Collection[TournamentPlayer]:
        return self.tournament_players_by_id.values()

    @cached_property
    def player_count(self) -> int:
        return len(self.tournament_players_by_id)

    @cached_property
    def exclusive_player_ids(self) -> set[int]:
        """The players this tournament would take with it if deleted:
        those it holds and no other tournament of the event does. Players
        are event-level, so one entered in several tournaments stays.

        Team rosters count: a team tournament stores no
        ``tournament_player`` rows, but the loader synthesises them from
        team membership, so ``tournament_players_by_id`` holds them all.
        """
        other_player_ids: set[int] = set()
        for tournament in self.event.tournaments_by_id.values():
            if tournament.id != self.id:
                other_player_ids |= set(tournament.tournament_players_by_id)
        return set(self.tournament_players_by_id) - other_player_ids

    @cached_property
    def tournament_players_by_fide_id(self) -> dict[int, TournamentPlayer]:
        return {
            tournament_player.fide_id: tournament_player
            for tournament_player in self.tournament_players
            if tournament_player.fide_id
        }

    @cached_property
    def tournament_players_by_starting_rank(self) -> dict[int, TournamentPlayer]:
        ordered_players = sorted(
            self.tournament_players,
            key=lambda player: player.starting_rank_sort_key,
        )
        return {
            trf_id: player for trf_id, player in enumerate(ordered_players, start=1)
        }

    @cached_property
    def tournament_players_by_pairing_number(self) -> dict[int, TournamentPlayer]:
        self._set_tournament_players_pairing_numbers()
        return {
            tournament_player.pairing_number or 0: tournament_player
            for tournament_player in sorted(
                self.tournament_players, key=attrgetter('pairing_number')
            )
        }

    @cached_property
    def sorted_tournament_players(self) -> list[TournamentPlayer]:
        return sorted(
            self.tournament_players,
            key=attrgetter('name_sort_key'),
        )

    @cached_property
    def sorted_tournament_players_without_unpaired(self) -> list[TournamentPlayer]:
        unpaired_ids = [
            tournament_player.id
            for tournament_player in self.get_unpaired_tournament_players(self.boards)
        ]
        return [
            player
            for player in self.sorted_tournament_players
            if player.id not in unpaired_ids
        ]

    @cached_property
    def ex_aequo_rank_by_player_id(self) -> dict[int, int]:
        rank_by_player_id: dict[int, int] = {}
        previous_rank_key: tuple | None = None
        previous_rank: int = 0
        for rank, player in self.tournament_players_by_rank.items():
            rank_key = player.rank_sort_key_without_pairing_number
            if rank_key != previous_rank_key:
                previous_rank_key = rank_key
                previous_rank = player.rank
            rank_by_player_id[player.id] = previous_rank
        return rank_by_player_id

    @property
    def min_player_rating(self) -> int | None:
        if not self.tournament_players:
            return None
        return min(player.rating for player in self.tournament_players)

    @property
    def max_player_rating(self) -> int | None:
        if not self.tournament_players:
            return None
        return max(player.rating for player in self.tournament_players)

    @property
    def average_player_rating(self) -> float:
        if not self.tournament_players:
            return 0
        return sum(player.rating for player in self.tournament_players) / len(
            self.tournament_players
        )

    # -------------------------------------------------------------------------
    # Counters
    # -------------------------------------------------------------------------

    @cached_property
    def gender_counts(self) -> Counter[PlayerGender]:
        """Returns the number of players by gender."""
        counter: Counter[PlayerGender] = Counter[PlayerGender]()
        for player in self.tournament_players:
            counter[player.gender] += 1
        return counter

    @cached_property
    def federation_counts(self) -> Counter[str]:
        """Returns the number of players by federation."""
        counter: Counter[str] = Counter[str]()
        for player in self.tournament_players:
            counter[player.federation.name] += 1
        return counter

    @cached_property
    def club_counts(self) -> Counter[str]:
        """Returns the number of players by club."""
        counter: Counter[str] = Counter[str]()
        for player in self.tournament_players:
            counter[player.club.name] += 1
        return counter

    @cached_property
    def category_counts(self) -> Counter[PlayerCategory]:
        counter = Counter[PlayerCategory]()
        for player in self.tournament_players:
            counter[player.category] += 1
        return counter

    @cached_property
    def rating_type_counts(self) -> Counter[PlayerRatingType]:
        counter = Counter[PlayerRatingType]()
        for player in self.tournament_players:
            counter[player.rating_type] += 1
        return counter

    @cached_property
    def check_in_status_grouped_counts(self) -> Counter[CheckInStatus]:
        return self.check_in_status_grouped_counts_for_round(self.current_round + 1)

    def check_in_status_grouped_counts_for_round(
        self, round_: int
    ) -> Counter[CheckInStatus]:
        counter = Counter[CheckInStatus]()
        for player in self.tournament_players:
            status = player.check_in_status_for_round(round_)
            if status not in (CheckInStatus.ABSENT, CheckInStatus.PRESENT):
                status = CheckInStatus.NEXT_ROUND_BYE
            counter[status] += 1
        return counter

    @cached_property
    def unrated_count(self) -> int:
        return sum(player.rating == 0 for player in self.tournament_players)

    @cached_property
    def estimated_count(self) -> int:
        return sum(player.estimated for player in self.tournament_players)

    # -------------------------------------------------------------------------
    # Misc
    # -------------------------------------------------------------------------

    @property
    def chief_arbiter(self) -> Account | None:
        for account in self.event.accounts_by_id.values():
            role = account.get_role(RoleType.CHIEF_ARBITER)
            if role and role.tournament_ids and self.id in role.tournament_ids:
                return account
        return None

    @property
    def deputy_arbiters(self) -> list[Account]:
        return [
            account
            for account in self.event.accounts_by_id.values()
            if (
                (role := account.get_role(RoleType.DEPUTY_ARBITER))
                and role.tournament_ids
                and self.id in role.tournament_ids
            )
        ]

    @property
    def arbiters(self) -> list[Account]:
        return [
            account
            for account in self.event.accounts_by_id.values()
            if (
                (role := account.get_role(RoleType.ARBITER))
                and role.tournament_ids
                and self.id in role.tournament_ids
            )
        ]

    @property
    def max_ranking_round(self) -> int:
        if not self.started:
            return 0
        if self.playing:
            return self.current_round - 1
        return self.current_round

    @property
    def started(self) -> bool:
        return self.current_round != 0

    @property
    def finished(self) -> bool:
        return self.current_round == self.rounds and not self.playing

    @property
    def boards(self) -> list[Board]:
        return self.get_round_boards(self.current_round)

    def boards_without_result(self, at_round: int) -> list[Board]:
        boards = self.get_round_boards(at_round)
        return [
            board
            for board in boards
            if board.result == Result.NO_RESULT
            and (
                board.stored_board.white_player_id is not None
                or board.stored_board.black_player_id is not None
            )
        ]

    @property
    def dependent_families(self) -> list[Family]:
        return [
            family
            for family in self.event.families_by_id.values()
            if family.tournament.id == self.id
        ]

    @property
    def dependent_screens(self) -> list[Screen]:
        dependent_screens = []
        for screen in self.event.basic_screens_by_id.values():
            if screen.screen_type.depends_on_tournament(screen, self):
                dependent_screens.append(screen)

        return dependent_screens

    @property
    def related_screens(self) -> list[Screen]:
        related_screens = []
        for screen in self.event.basic_screens_by_id.values():
            if screen.screen_type.relates_to_tournament(screen, self):
                related_screens.append(screen)

        return related_screens

    def print_real_points(self, round_: int | None = None) -> bool:
        if round_ is None:
            round_ = self.current_round
        return self.pairing_variation.print_real_points(self, round_)

    @cached_property
    def point_values(self) -> dict[Result, float]:
        """Game points awarded per result type for an individual board
        game. Team tournaments always use the standard 1 / 0.5 / 0
        FIDE defaults — team-level PAB / match scoring lives in
        :attr:`match_points`. The ``game_points`` override only applies
        to individual tournaments. Individual default: WIN=1, DRAW=0.5,
        LOSS=0, ZPB=LOSS, PAB=WIN."""
        if self.is_team_tournament:
            return {
                r: r.point_value
                for r in (
                    Result.WIN,
                    Result.DRAW,
                    Result.LOSS,
                    Result.ZERO_POINT_BYE,
                    Result.PAIRING_ALLOCATED_BYE,
                )
            }
        raw = self.stored_tournament.game_points or {}
        win = float(raw.get(Result.WIN.value, 1.0))
        draw = float(raw.get(Result.DRAW.value, 0.5))
        loss = float(raw.get(Result.LOSS.value, 0.0))
        zpb = float(raw.get(Result.ZERO_POINT_BYE.value, loss))
        pab = float(raw.get(Result.PAIRING_ALLOCATED_BYE.value, win))
        return {
            Result.WIN: win,
            Result.DRAW: draw,
            Result.LOSS: loss,
            Result.ZERO_POINT_BYE: zpb,
            Result.PAIRING_ALLOCATED_BYE: pab,
        }

    @cached_property
    def team_game_points(self) -> dict[Result, float]:
        """Per-board game points awarded to a team for an individual
        result, in the team-tournament context. The same
        ``stored_tournament.game_points`` field carries the override
        (3/2/1 etc. via the tournament modal); team scoring respects
        it, while :attr:`point_values` (used for individual rankings
        within the team and for individual mode) stays at the FIDE
        defaults. Defaults: WIN=1, DRAW=0.5, LOSS=0, ABS / FORFAIT
        fall back to LOSS unless the form sets ``gp_zpb`` explicitly
        (e.g. a federation rule scoring forfeits as -1)."""
        raw = self.stored_tournament.game_points or {}
        loss = float(raw.get(Result.LOSS.value, 0.0))
        absent = float(raw.get(Result.ZERO_POINT_BYE.value, loss))
        return {
            Result.WIN: float(raw.get(Result.WIN.value, 1.0)),
            Result.DRAW: float(raw.get(Result.DRAW.value, 0.5)),
            Result.LOSS: loss,
            Result.ZERO_POINT_BYE: absent,
            # ``Result.points()`` only falls back to LOSS for these;
            # surface the absent override explicitly so a forfeit-loss
            # or double-forfeit also gets the configured value.
            Result.FORFEIT_LOSS: absent,
            Result.DOUBLE_FORFEIT: absent,
        }

    @property
    def is_standard_point_system_used(self) -> bool:
        """True if the point system matches the FIDE default 1/0.5/0 with PAB=1."""
        return (
            self.win_points == 1.0
            and self.draw_points == 0.5
            and self.loss_points == 0.0
            and self.pab_points == 1.0
        )

    @property
    def pab_equivalent_result(self) -> Result:
        """Which game result (WIN/DRAW/LOSS) the Pairing Allocated Bye is worth.
        Used for legacy interop where PAB is expressed as one of those three."""
        if self.pab_points == self.win_points:
            return Result.WIN
        if self.pab_points == self.draw_points:
            return Result.DRAW
        if self.pab_points == self.loss_points:
            return Result.LOSS
        return Result.WIN

    @cached_property
    def win_points(self) -> float:
        return Result.WIN.points(self.point_values)

    @cached_property
    def draw_points(self) -> float:
        return Result.DRAW.points(self.point_values)

    @cached_property
    def loss_points(self) -> float:
        return Result.LOSS.points(self.point_values)

    @cached_property
    def pab_points(self) -> float:
        return Result.PAIRING_ALLOCATED_BYE.points(self.point_values)

    @cached_property
    def team_bye_is_rest(self) -> bool:
        """Whether an engine-allocated team bye is a *rest game* (round
        robin and two-game-match systems: not played, no points) rather
        than a points-scoring PAB (Swiss). Manual byes (ZPB / HPB / FPB)
        are unaffected."""
        return self.pairing_variation.engine.pab_result == Result.REST_GAME

    @cached_property
    def team_pab_game_points(self) -> float:
        """Game points awarded to a team for a PAIRING_ALLOCATED_BYE
        match (team-level). An explicit ``gp_pab`` field in the tournament
        settings modal (stored in ``game_points[PAIRING_ALLOCATED_BYE]``)
        overrides it.

        Default depends on the pairing system, scaled by the board count
        (a PAB stands in for a whole match, not a single board): Team Swiss
        treats PAB as a drawn match (FIDE C.04.6 §1.4), so
        ``boards × DRAW`` game points. Other team systems (round-robin /
        Berger, Molter…) treat PAB as a won match, so ``boards × WIN``."""
        from data.pairings.systems import TeamSwissPairingSystem

        raw = self.stored_tournament.game_points or {}
        boards = float(self.team_player_count or 0)
        if self.pairing_system == TeamSwissPairingSystem():
            per_board = float(raw.get(Result.DRAW.value, Result.DRAW.point_value))
        else:
            per_board = float(raw.get(Result.WIN.value, Result.WIN.point_value))
        default = boards * per_board
        return float(raw.get(Result.PAIRING_ALLOCATED_BYE.value, default))

    @cached_property
    def zpb_points(self) -> float:
        return Result.ZERO_POINT_BYE.points(self.point_values)

    @cached_property
    def current_round(self) -> int:
        return (
            self.stored_tournament.current_round
            or self.pairing_system.default_current_round(self)
        )

    @property
    def is_last_round(self) -> bool:
        return self.current_round == self.rounds

    @cached_property
    def is_fully_paired(self) -> bool:
        return all(self.is_round_paired(round_) for round_ in range(1, self.rounds + 1))

    @cached_property
    def has_results(self) -> bool:
        return any(
            self.round_has_result(round_) for round_ in range(1, self.rounds + 1)
        )

    @cached_property
    def has_pairings(self) -> bool:
        return any(
            self.round_has_pairings(round_) for round_ in range(1, self.rounds + 1)
        )

    @property
    def has_titled_players(self) -> bool:
        return any(
            player.strongest_title != PlayerTitle.NONE
            for player in self.tournament_players
        )

    @property
    def has_norm_eligible_titled_players(self) -> bool:
        return any(
            not player.held_titles.isdisjoint(TitleNorm.TITLE_HOLDERS)
            for player in self.tournament_players
        )

    @cached_property
    def last_paired_round(self) -> int:
        return next(
            (
                round_
                for round_ in reversed(range(1, self.rounds + 1))
                if self.round_has_pairings(round_)
            ),
            0,
        )

    @cached_property
    def can_add_players(self) -> bool:
        """Determines if players can be added to the tournament."""
        return not self.finished and (
            not self.has_pairings
            or self.pairing_system.allow_player_addition_once_paired
        )

    @cached_property
    def can_add_teams(self) -> bool:
        """Determines if teams can be added to the tournament."""
        return not self.finished and (
            not self.has_pairings or self.pairing_system.allow_team_addition_once_paired
        )

    @cached_property
    def playing(self) -> bool:
        return self.is_round_in_tournament(
            self.current_round
        ) and not self.is_round_finished(self.current_round)

    @cached_property
    def tournament_players_by_id(self) -> dict[int, TournamentPlayer]:
        players_by_id: dict[int, TournamentPlayer] = {}
        for (
            stored_tournament_player
        ) in self.stored_tournament.stored_tournament_players:
            tournament_player = TournamentPlayer(self, stored_tournament_player)
            players_by_id[tournament_player.id] = tournament_player
        return players_by_id

    @property
    def players_by_id(self) -> dict[int, TournamentPlayer]:
        return self.tournament_players_by_id

    @property
    def players(self) -> Collection[TournamentPlayer]:
        return self.tournament_players

    @cached_property
    def boards_by_id(self) -> BoardsById:
        boards_by_id: BoardsById = BoardsById()
        for (
            round_,
            stored_boards,
        ) in self.stored_tournament.stored_boards_by_round.items():
            for stored_board in stored_boards:
                board = Board(self, round_, stored_board)
                boards_by_id[board.identifier] = board
        return boards_by_id

    def invalidate_board_layout(self) -> None:
        """Invalidate board-number caches after an in-place board change."""
        if 'boards_by_id' in self.__dict__:
            self.boards_by_id.version += 1

    def get_round_boards(self, round_: int) -> list[Board]:
        return sorted(
            (board for board in self.boards_by_id.values() if board.round == round_),
            key=lambda board: board.index,
        )

    @cached_property
    def leave_fixed_board_holes(self) -> bool:
        """Whether a fixed board number leaves the table it displaces empty
        and duplicates the number it lands on, reproducing the numbering of
        the reference file format. When false the round is numbered compactly:
        fixed players keep their number and every other board fills the
        remaining numbers in order."""
        return bool(
            plugin_manager.hook_for_event(self.event, 'leave_fixed_board_holes')(
                tournament=self
            )
        )

    def _round_board_numbers(self, round_: int) -> dict[int, int]:
        cache_key = (round_, self.boards_by_id.version)
        cached = self._round_board_numbers_cache.get(cache_key)
        if cached is not None:
            return cached
        entries = [
            (board.identifier, board.fixed_number, board.standard_number)
            for board in self.get_round_boards(round_)
        ]
        board_numbers = compute_round_board_numbers(
            entries, self.first_board_number, self.leave_fixed_board_holes
        )
        self._round_board_numbers_cache[cache_key] = board_numbers
        return board_numbers

    def board_number(self, board: Board) -> int:
        if board.stored_board.id is None:
            return board.fixed_number or board.standard_number
        return self._round_board_numbers(board.round)[board.identifier]

    def get_round_pab_board(self, round_: int) -> Board | None:
        """The round's pairing-allocated-bye board — a player seated alone,
        *waiting* for an opponent. A flat-system forfeit hole is also
        black-less but is a settled result (``FORFEIT_WIN``), not an empty
        bye, so it's excluded: manual pairing must not attach a new player
        to a legitimate forfeit board."""
        return next(
            (
                board
                for board in self.boards_by_id.values()
                if board.round == round_
                and not board.black_tournament_player
                and board.result == Result.PAIRING_ALLOCATED_BYE
            ),
            None,
        )

    def unboarded_holes(self, round_: int) -> list[tuple[int, str]]:
        """Flat fixed-table (Molter): empty table cells with no board this
        round — absent seats, e.g. freed by unpairing and awaiting a forfeit
        pairing. Each is ``(board_index, label)`` like ``(5, 'B3')``. Empty
        for other systems. A present-but-unpaired player's seat isn't a hole
        (it's filled in the line-up); only ``None`` slots count."""
        from data.pairings.fixed_table import FixedTablePairingEngine

        engine = self.pairing_variation.engine
        if not isinstance(engine, FixedTablePairingEngine):
            return []
        refs = engine.board_references(self, round_)
        team_by_letter = engine.team_by_letter(self)
        boarded = {board.index for board in self.get_round_boards(round_)}
        holes: list[tuple[int, str]] = []
        for index, (white_ref, black_ref) in enumerate(refs):
            if index in boarded:
                continue
            for ref in (white_ref, black_ref):
                team = team_by_letter.get(ref[0])
                if team is None:
                    continue
                slot = int(ref[1:]) - 1
                slots = team.effective_round_slots(round_)
                if 0 <= slot < len(slots) and slots[slot] is None:
                    holes.append((index, ref))
        return holes

    def create_flat_manual_board(
        self,
        round_: int,
        white_id: int | None,
        black_id: int | None,
        index: int,
    ) -> None:
        """Create one flat (Molter) board from a manual selection. Either side
        may be ``None`` (a hole) — but not both. Two players ⇒ a game; one
        player + a hole ⇒ a forfeit win for the present player (handled by
        :meth:`create_boards`, which scores a one-sided flat board as a
        forfeit). No line-up is touched."""
        if white_id is None and black_id is None:
            raise SharlyChessException('A board needs at least one player.')
        for player_id in (white_id, black_id):
            if player_id is None:
                continue
            pairing = self.tournament_players_by_id[player_id].pairings[round_]
            if pairing.exists and pairing.stored_pairing.board_id is not None:
                raise SharlyChessException(
                    f'Player {player_id} is already paired in round {round_}.'
                )
        self.create_boards(
            [
                StoredBoard(
                    id=None,
                    white_player_id=white_id,
                    black_player_id=black_id,
                    index=index,
                )
            ],
            round_,
            Result.FORFEIT_WIN,
        )

    def get_unpaired_tournament_players(
        self, boards: list[Board]
    ) -> list[TournamentPlayer]:
        paired_player_ids: list[int] = []
        for board in boards:
            if board.optional_white_tournament_player:
                paired_player_ids.append(board.optional_white_tournament_player.id)
            if board.black_tournament_player:
                paired_player_ids.append(board.black_tournament_player.id)
        return [
            tournament_player
            for tournament_player in self.tournament_players
            if tournament_player.id not in paired_player_ids
        ]

    @property
    def has_never_paired_players(self) -> bool:
        return any(not player.has_real_pairings for player in self.tournament_players)

    def set_for_round(
        self,
        round_: int | None = None,
        *,
        only_players: 'list[TournamentPlayer] | None' = None,
    ):
        """Prepare a round, optionally limiting point calculation to *only_players*.

        A full-page render must recompute the full field after a limited pass.
        """
        if round_ is None:
            round_ = self.current_round
        self._compute_caching_enabled = True
        try:
            self._keizer_scorer = None
            for player in self.tournament_players:
                player.clear_compute_caches()
            players_to_compute = (
                self.tournament_players if only_players is None else only_players
            )
            for player in players_to_compute:
                self.set_tournament_player_points(player, before_round=round_)
            board_numbers = self._round_board_numbers(round_)
            for board in self.get_round_boards(round_):
                if board.stored_board.id is not None:
                    number = board_numbers[board.identifier]
                else:
                    number = board.fixed_number or board.standard_number
                white_tp = board.optional_white_tournament_player
                if white_tp is not None:
                    white_tp.set_board(board.index, number, BoardColor.WHITE)
                if board.black_tournament_player:
                    board.black_tournament_player.set_board(
                        board.index, number, BoardColor.BLACK
                    )
            plugin_manager.hook_for_event(self.event, 'set_for_round')(
                tournament=self, round_=round_
            )
        finally:
            self._compute_caching_enabled = False

    def generate_round_pairings(
        self, at_round: int, partial_pairings: bool = False
    ) -> str:
        if not partial_pairings and self.round_has_pairings(at_round):
            return _(
                'Round {round} is already paired. Unpair it before pairing it again.'
            ).format(round=at_round)
        self.persist_automatic_rounds()
        return self.pairing_variation.engine.generate_pairings(
            self, at_round, partial_pairings
        )

    def persist_automatic_rounds(self):
        """Write down the round count a system works out for itself.

        ``rounds`` already answers with it, but the stored value is what
        the schedule, the exports and every other reader of the record
        see. Settling it as the pairings are generated keeps them in
        step — including after an unpairing, when the field may have
        changed size and the count with it.
        """
        if not self.pairing_variation.sets_its_own_round_count:
            return
        automatic_rounds = self.automatic_rounds
        if automatic_rounds is None or automatic_rounds == (
            self.stored_tournament.rounds
        ):
            return
        self.stored_tournament.rounds = automatic_rounds
        with EventDatabase(self.event.uniq_id, True) as database:
            database.update_stored_tournament(self.stored_tournament)

    def pairings_generation_disabled_message(self, at_round: int) -> str | None:
        return self.pairing_variation.engine.pairings_generation_disabled_message(
            self, at_round
        )

    def is_round_finished(self, round_: int) -> bool:
        # In team events, reserve players (not in the round's lineup)
        # have no pairing for this round; players punched out of the
        # lineup mid-round retain a row but with ``board_id = None``.
        # Both cases mean "no game to finish". In team-paired systems
        # the round additionally isn't finished until every team has an
        # envelope (real match or any bye) — a team with no envelope is
        # still waiting. Flat systems pair boards without envelopes.
        if self.event.is_team_event:
            if self.pairing_system.paired_by_team:
                envelope_team_ids: set[int] = set()
                for tb in self.get_round_team_boards(round_):
                    stb = tb.stored_team_board
                    envelope_team_ids.add(stb.team_a_id)
                    if stb.team_b_id is not None:
                        envelope_team_ids.add(stb.team_b_id)
                if any(team.id not in envelope_team_ids for team in self.teams):
                    return False
            return self.team_round_results_complete(round_)
        return all(
            player.pairings[round_].result != Result.NO_RESULT
            for player in self.tournament_players
        )

    def team_round_results_complete(self, round_: int) -> bool:
        """All entered results for the round's real boards (team events).
        Unlike :meth:`is_round_finished`, doesn't require every team to
        have an envelope — used to decide how far a late-joining team's
        zero-point byes extend."""
        return all(
            player.pairings[round_].result != Result.NO_RESULT
            for player in self.tournament_players
            if player.pairings[round_].exists
            and player.pairings[round_].stored_pairing.board_id is not None
            # A board whose opponent slot is a hole has no game to
            # play (it's a forfeit), so it never holds up the round.
            and player.pairings[round_].opponent_id is not None
        )

    def is_round_paired(self, round_: int) -> bool:
        return all(
            player.pairings[round_].opponent_id is not None
            or player.pairings[round_].result.is_bye
            for player in self.tournament_players
        )

    def is_round_partially_paired(self, round_: int) -> bool:
        if self.event.is_team_event and self.pairing_system.paired_by_team:
            # Team mode: there's something to complement if at least
            # one team has no envelope (real match / manual bye / PAB)
            # for the round.
            envelope_team_ids: set[int] = set()
            for tb in self.get_round_team_boards(round_):
                stb = tb.stored_team_board
                envelope_team_ids.add(stb.team_a_id)
                if stb.team_b_id is not None:
                    envelope_team_ids.add(stb.team_b_id)
            # "Partially" paired means some teams are paired and some aren't —
            # a fully unpaired round (no envelopes at all) is not partial, so
            # the complementary-pairing button stays hidden.
            return bool(envelope_team_ids) and any(
                team.id not in envelope_team_ids for team in self.teams
            )
        return self.round_has_pairings(round_) and not self.is_round_paired(round_)

    def round_has_result(self, round_: int) -> bool:
        return any(
            player.pairings[round_].result != Result.NO_RESULT
            and player.pairings[round_].opponent_id is not None
            for player in self.tournament_players
        )

    def round_has_played_result(self, round_: int) -> bool:
        return any(player.pairings[round_].played for player in self.tournament_players)

    def round_has_pairings(self, round_: int) -> bool:
        # Team matches are stored as team-board envelopes; the per-player
        # pairings are derived from the lineups. A round with team
        # matches but empty/partial rosters may have no seated players at
        # all, so the envelope is the source of truth for team modes —
        # otherwise the round wrongly reads as unpaired (pair button
        # stays, no unpair button).
        if self.get_round_team_boards(round_):
            return True
        return any(
            player.pairings[round_].opponent_id is not None
            or player.pairings[round_].exempt
            for player in self.tournament_players
        )

    def round_has_pab(self, round_: int) -> bool:
        return any(player.pairings[round_].exempt for player in self.tournament_players)

    def is_round_in_tournament(self, round_: int) -> bool:
        return 1 <= round_ <= self.rounds

    @cached_property
    def big_tournament_exemption(self) -> BigTournamentExemption:
        """1.4.3d Swiss exception — see data.norms for the calculation.

        Cached on the Tournament instance so the per-applicant searcher
        can read it cheaply for every player.
        """
        return compute_big_tournament_exemption(self)

    @cached_property
    def high_level_tournament(self) -> bool:
        """1.5.6a — see data.norms for the calculation.

        Cached on the Tournament instance for per-applicant lookup.
        """
        return compute_high_level_tournament(self)

    def to_trf(
        self,
        after_round: int | None = None,
        next_round_pairings_as_zpb: bool = False,
        prohibited_pairing_override: list['TrfProhibitedPairing'] | None = None,
    ) -> 'TrfTournament':
        from data.input_output.trf.trf_data import TRF_DATE_FORMAT, TrfTournament

        if after_round is None:
            after_round = self.rounds
        self.compute_tournament_player_ranks(after_round=after_round)
        seed_setting = ColorSeedSetting()
        trf = TrfTournament(
            name=self.name,
            city=self.location or '',
            federation=self.event.federation,
            start_date=self.start_date.strftime(TRF_DATE_FORMAT),
            end_date=self.stop_date.strftime(TRF_DATE_FORMAT),
            num_players=len(self.tournament_players_by_id),
            num_rated_players=sum(
                bool(player.fide_rating_value) for player in self.players
            ),
            chief_arbiter=getattr(self.chief_arbiter, 'fide_arbiter_str', ''),
            deputy_arbiters=[
                arbiter.fide_arbiter_str for arbiter in self.deputy_arbiters
            ],
            round_dates=[
                dt.strftime('%y/%m/%d') if dt else ''
                for idx in range(1, after_round + 1)
                for dt in [self.round_datetimes.get(idx)]
            ],
            num_rounds=self.rounds,
            initial_color=seed_setting.get_value(self).value,
            individuals_point_system=self._trf_individuals_point_system(),
            starting_rank_method=self._trf_starting_rank_method(),
            starting_rank_federation=self.event.federation or '',
            pairing_controller_id='Sharly Chess',
            encoded_type=self.pairing_variation.trf_encoded_type,
            # Record 212 is the ordered list of criteria that define the
            # standings, PTS included — no longer prefixed here, since the
            # Points tie-break carries its own place in the list.
            standings_tie_breaks=[
                tie_break.trf_acronym for tie_break in self.tie_breaks
            ],
            time_control=self.time_control_trf25 or '',
            players=[
                player.to_trf(after_round, next_round_pairings_as_zpb)
                for player in self.tournament_players_by_pairing_number.values()
            ],
            accelerated_rounds=self._trf_accelerated_rounds(),
            round_byes=self._trf_round_byes(),
        )
        if self.is_team_tournament:
            self._populate_team_trf(
                trf,
                after_round=after_round,
                next_round_pairings_as_zpb=next_round_pairings_as_zpb,
            )
        else:
            trf.abnormal_points_assignments = (
                self._individual_abnormal_points_assignments(after_round)
            )
        trf.prohibited_pairings = (
            prohibited_pairing_override
            if prohibited_pairing_override is not None
            else self._trf_prohibited_pairings()
        )
        return trf

    def _trf_prohibited_pairings(self) -> 'list[TrfProhibitedPairing]':
        """TRF26 260 records regenerated from the per-round snapshots: the
        frozen hard/soft groups plus the round's ``protect_rank`` reproduce
        the *exact* effective set bbpPairings enforced (hard groups kept
        whole, soft groups relaxed at the stored cutoff) — so the export is
        the truth, not the configured-before-relaxation set. Snapshots with
        no cutoff (a hard-only round, or an imported 260 set) emit every
        group whole."""
        result: list['TrfProhibitedPairing'] = []
        groups_by_round: dict[int, list] = {}
        protect_by_round: dict[int, int] = {}
        for group in self.stored_tournament.stored_prohibited_pairing_groups:
            if group.round_ is None:
                continue
            groups_by_round.setdefault(group.round_, []).append(group)
            if group.protect_rank is not None:
                protect_by_round[group.round_] = group.protect_rank
        for round_ in sorted(groups_by_round):
            groups = groups_by_round[round_]
            protect_rank = protect_by_round.get(round_)
            if protect_rank is None:
                # No relaxation recorded — every stored group is enforced
                # whole (hard-only round, or an imported 260 set).
                whole = [list(group.member_ids) for group in groups]
                result.extend(
                    self.prohibited_pairing_applied_lines(whole, [], 0, {}, round_)
                )
                continue
            hard_groups = [list(g.member_ids) for g in groups if g.is_hard]
            soft_groups = [list(g.member_ids) for g in groups if not g.is_hard]
            rank_by_member = self._prohibited_member_weakness_ranks(
                after_round=round_ - 1
            )
            result.extend(
                self.prohibited_pairing_applied_lines(
                    hard_groups, soft_groups, protect_rank, rank_by_member, round_
                )
            )
        return result

    def _populate_team_trf(
        self,
        trf: 'TrfTournament',
        *,
        after_round: int,
        next_round_pairings_as_zpb: bool = False,
    ) -> None:
        from data.input_output.trf.trf_data import TrfTeam

        """TRF26 team-mode records (310 rosters, 192 team code, 362
        match-point system, 352 board-colour sequence). Built on top
        of the individual TRF (001 player rows + 162 game points)
        produced by :meth:`to_trf` — bbpPairings' ``--team`` mode
        aggregates the per-player games into team match data."""
        match_points = self.match_points
        trf.teams_point_system = {
            'TW': float(match_points.get(Result.WIN, 2.0)),
            'TD': float(match_points.get(Result.DRAW, 1.0)),
            'TL': float(match_points.get(Result.LOSS, 0.0)),
        }
        tpn_map = self._team_trf_tpn_map()
        trf.team_pabs = self._team_pabs_record(
            after_round=after_round, tpn_by_team_id=tpn_map
        )
        trf.oodo_team_pairings = self._team_oodo_records(
            after_round=after_round, tpn_by_team_id=tpn_map
        )
        (
            trf.informative_team_pairings_records,
            trf.informative_team_results_records,
        ) = self._team_informative_records(
            after_round=after_round, tpn_by_team_id=tpn_map
        )

        team_player_count = self.team_player_count or 0
        pattern = self.color_pattern or ''
        if not pattern and team_player_count:
            pattern = ''.join(
                BoardColor.WHITE.value if i % 2 == 0 else BoardColor.BLACK.value
                for i in range(team_player_count)
            )
        trf.board_color_sequence = pattern

        # 240 records in team mode are interpreted by bbpPairings as
        # *team* byes — its team-TRF reader strips them from the
        # member stream and uses the TPN values (not player numbers).
        # We therefore overwrite whatever individual-bye 240s were
        # populated by ``to_trf`` and emit only team byes for the
        # round being paired.
        trf.round_byes = self._team_trf_round_byes(
            after_round=after_round,
            tpn_by_team_id=tpn_map,
            next_round_pairings_as_zpb=next_round_pairings_as_zpb,
        )
        trf.team_forfeited_matches = self._team_forfeited_matches(
            after_round=after_round, tpn_by_team_id=tpn_map
        )

        from data.pairings.engines import _team_ui_sort_key

        teams = sorted(self.teams, key=_team_ui_sort_key)
        tpn_by_team_id = tpn_map
        tp_by_player_id = {tp.id: tp for tp in self.tournament_players}
        team_totals = self._team_trf_totals_after(after_round)
        # Team rank from the tournament's own standings — primary
        # score + secondary + (eventually) team tie-breaks. Falls back
        # to the team-UI order for teams ``team_standings`` doesn't
        # return.
        rank_by_team_id: dict[int, int] = {}
        # Rank must match ``team_totals`` (bounded to ``after_round``) —
        # otherwise the in-progress round leaks into the TRF rank fed to
        # bbpPairings (e.g. during complementary pairing).
        for row in self.team_standings(after_round=after_round):
            rank_by_team_id[row['team'].id] = row['rank']
        nickname_by_team_id = self._team_trf_nickname_map(tpn_by_team_id)
        trf_teams: list[TrfTeam] = []
        for team in teams:
            tpn = tpn_by_team_id[team.id]
            # 310 lists the whole roster: the round's board order first
            # (capped at the board count), then the remaining roster
            # members as substitutes, so a never-fielded player still
            # round-trips through the team record on re-import.
            lineup = team.effective_round_lineup(after_round + 1)[:team_player_count]
            ordered_members = list(lineup)
            seen_ids = {member.id for member in lineup}
            for member in team.players:
                if member.id not in seen_ids:
                    ordered_members.append(member)
                    seen_ids.add(member.id)
            player_ids: list[int] = []
            for member in ordered_members:
                tp = tp_by_player_id.get(member.id)
                if tp is None or tp.pairing_number is None:
                    continue
                player_ids.append(tp.pairing_number)
            mp, gp = team_totals.get(team.id, (0.0, 0.0))
            trf_teams.append(
                TrfTeam(
                    id=tpn,
                    name=team.name[:32],
                    nickname=nickname_by_team_id[team.id],
                    match_points=mp,
                    game_points=gp,
                    rank=rank_by_team_id.get(team.id),
                    player_ids=player_ids,
                )
            )
        trf_teams.sort(key=lambda t: t.id)
        trf.teams = trf_teams
        trf.num_teams = len(trf_teams)
        # Only the team-Swiss system gets the score/colour-derived FIDE
        # team-Swiss code; round-robin, two-game-match and flat fixed-table
        # systems keep their own variation code (set from
        # ``pairing_variation.trf_encoded_type`` when the TRF was built).
        if self.pairing_system.fide_team_swiss_code:
            trf.encoded_type = self._team_trf_encoded_type()
        trf.abnormal_points_assignments = self._team_abnormal_points_assignments(
            after_round=after_round, tpn_by_team_id=tpn_map
        )

    def _individual_abnormal_points_assignments(
        self, after_round: int
    ) -> 'list[TrfAbnormalPointsAssignment]':
        """TRF26 299 records for an individual tournament: one blank-type
        line per (player, round) carrying a bonus / penalty, keyed on the
        pairing number. Only the game-points field applies — 8-11 is for
        teams — and the 001 points already include the delta, which is
        what a reader recomputing the score from the results expects."""
        from data.input_output.trf.trf_data import TrfAbnormalPointsAssignment

        assignments: list[TrfAbnormalPointsAssignment] = []
        for player in self.tournament_players_by_pairing_number.values():
            if player.pairing_number is None:
                continue
            for round_ in range(1, after_round + 1):
                delta = self.player_point_adjustment(player.id, round_)
                if not delta:
                    continue
                assignments.append(
                    TrfAbnormalPointsAssignment(
                        type=' ',
                        match_points=None,
                        game_points=delta,
                        round=round_,
                        pairing_numbers=[player.pairing_number],
                    )
                )
        return assignments

    def _team_abnormal_points_assignments(
        self, *, after_round: int, tpn_by_team_id: dict[int, int]
    ) -> 'list[TrfAbnormalPointsAssignment]':
        """TRF26 299 records — the team bonus / penalty points actually
        applied, one line per (team, round) carrying a non-zero
        effective (MP, GP) delta (manual entry + rule-set). The single
        pairing number is the team's TPN. On import the value is stored
        as a manual adjustment (the rule set isn't carried by the TRF,
        so nothing re-derives the automatic part)."""
        from data.input_output.trf.trf_data import TrfAbnormalPointsAssignment

        assignments: list[TrfAbnormalPointsAssignment] = []
        for team in self.teams:
            tpn = tpn_by_team_id.get(team.id)
            if tpn is None:
                continue
            for round_ in range(1, after_round + 1):
                mp, gp = self.effective_point_adjustment(team.id, round_)
                if not mp and not gp:
                    continue
                assignments.append(
                    TrfAbnormalPointsAssignment(
                        type=' ',
                        match_points=mp,
                        game_points=gp,
                        round=round_,
                        pairing_numbers=[tpn],
                    )
                )
        return assignments

    def _trf_starting_rank_method(self) -> str:
        """TRF26 172 — how the participants were ranked. Derived from the
        ratings actually used rather than from the tournament setting:
        the setting only states a preference, and which fallback fired
        is what the receiver needs in order to reproduce the ranking.

        Estimated ratings (and the floors a rule set may supply) have no
        place in the format, so a tournament that used any of them is
        ranked by a method the TRF cannot express — which is what
        ``OTHER`` is for."""
        used = {player.rating_type for player in self.players}
        if not used:
            # Nothing to describe yet; state the preference.
            return 'FIDE' if self.player_rating_type == PlayerRatingType.FIDE else 'NRO'
        if PlayerRatingType.ESTIMATED in used:
            return 'OTHER'
        if used == {PlayerRatingType.FIDE}:
            return 'FIDE'
        if used == {PlayerRatingType.NATIONAL}:
            return 'NRO'
        # Both were used, so a fallback fired: say which way round.
        return 'FIDON' if self.player_rating_type == PlayerRatingType.FIDE else 'NIDOF'

    def _trf_individuals_point_system(self) -> dict[str, float]:
        """TRF26 162 record — game-point values per result symbol.
        Only emits values that have been overridden vs the FIDE
        defaults; readers fall back to W=1 / D=0.5 / L=0 / ZPB=LOSS /
        PAB=WIN when a symbol is absent. bbpPairings ``--team``
        accepts the full W / D / L / A (ZPB) / P (PAB) alphabet."""
        from data.input_output.trf.trf_mappers import TrfPointSystemResult

        raw = self.stored_tournament.game_points or {}
        result: dict[str, float] = {}
        for outcome_value, value in raw.items():
            try:
                outcome = Result(outcome_value)
            except ValueError:
                continue
            symbol = TrfPointSystemResult.get_outer_value(outcome) or ''
            if not symbol:
                continue
            result[symbol] = float(value)
        return result

    def _team_oodo_records(
        self,
        *,
        after_round: int,
        tpn_by_team_id: dict[int, int],
    ) -> 'list[TrfOOdOTeamPairing]':
        """TRF26 300 records — per-round team lineups in board order.
        Emitted twice per real (non-PAB) team match: once from team_a's
        view, once from team_b's. Carries the historical lineup so a
        re-import can recover round-by-round board ordering when it
        differs from the current 310 roster."""
        from data.input_output.trf.trf_data import TrfOOdOTeamPairing

        team_player_count = self.team_player_count or 0
        team_id_by_player_id = {
            tp.id: tp.team_id
            for tp in self.tournament_players
            if tp.team_id is not None
        }
        records: list[TrfOOdOTeamPairing] = []
        team_boards = sorted(
            (
                tb
                for tb in self.team_boards_by_id.values()
                if 1 <= tb.round <= after_round
                and tb.stored_team_board.team_b_id is not None
            ),
            key=lambda tb: (tb.round, tb.index or 0),
        )
        for tb in team_boards:
            stb = tb.stored_team_board
            a_tpn = tpn_by_team_id.get(stb.team_a_id)
            b_tpn = (
                tpn_by_team_id.get(stb.team_b_id) if stb.team_b_id is not None else None
            )
            if a_tpn is None or b_tpn is None:
                continue
            a_lineup: list[int | None] = [None] * team_player_count
            b_lineup: list[int | None] = [None] * team_player_count
            for board in tb.boards:
                slot = board.index
                if slot < 0 or slot >= team_player_count:
                    continue
                white_tp = board.optional_white_tournament_player
                black_tp = board.black_tournament_player
                for tp in (white_tp, black_tp):
                    if tp is None or tp.pairing_number is None:
                        continue
                    team_id = team_id_by_player_id.get(tp.id)
                    if team_id == stb.team_a_id:
                        a_lineup[slot] = tp.pairing_number
                    elif team_id == stb.team_b_id:
                        b_lineup[slot] = tp.pairing_number
            records.append(
                TrfOOdOTeamPairing(
                    round=tb.round,
                    team_id=a_tpn,
                    opponent_team_id=b_tpn,
                    boards=a_lineup,
                )
            )
            records.append(
                TrfOOdOTeamPairing(
                    round=tb.round,
                    team_id=b_tpn,
                    opponent_team_id=a_tpn,
                    boards=b_lineup,
                )
            )
        return records

    def _team_informative_records(
        self,
        *,
        after_round: int,
        tpn_by_team_id: dict[int, int],
    ) -> tuple[list[str], list[str]]:
        """TRF26 801 (team pairings) and 802 (team results) — one row
        per team summarising every played round. Both are informative
        records; the spec says they "duplicate some information that
        already exists" but recommends emitting them for human
        readability. Export-only — the importer ignores these fields.

        801 per-round block: ``<opp_tpn> <colour> <board-results>
        <team-RID-string>`` where each RID is the player's position on
        the 310 roster (1-9, then A-Z for 10-35, then ``*``).

        802 per-round block: ``<opp_tpn|bye> <colour> <GP> <forfeit>``
        with fixed widths (opp/bye = 3 chars, GP = 4 chars "11.5"
        format)."""

        def _rid_char(position_1based: int) -> str:
            """Encode a roster position as a single character per the
            spec's VNC scheme: 1-9 → '1'-'9', 10-35 → 'A'-'Z', 36+ →
            '*'."""
            if 1 <= position_1based <= 9:
                return str(position_1based)
            if 10 <= position_1based <= 35:
                return chr(ord('A') + position_1based - 10)
            return '*'

        pairings: list[str] = []
        results: list[str] = []
        team_player_count = self.team_player_count or 0
        teams_by_tpn = sorted(
            (
                (tpn_by_team_id[team.id], team)
                for team in self.teams
                if team.id in tpn_by_team_id
            ),
            key=lambda item: item[0],
        )

        # Pre-compute each player's RID character (position on their
        # team's 310 roster + 1 → spec-encoded char).
        rid_by_player_id: dict[int, str] = {}
        for tp in self.tournament_players:
            if tp.team_index is None:
                continue
            rid_by_player_id[tp.id] = _rid_char(tp.team_index + 1)

        # Round → team_id → (opp_tpn, colour, board_results, rid_string,
        # match_gp, is_forfeit, bye_acronym_or_none).
        per_round: dict[
            int,
            dict[
                int,
                tuple[int | None, str, str, str, float, bool, str | None],
            ],
        ] = {}
        for team_board in self.team_boards_by_id.values():
            if not (1 <= team_board.round <= after_round):
                continue
            stb = team_board.stored_team_board
            round_data = per_round.setdefault(team_board.round, {})
            a_gp, b_gp = team_board.game_points
            if stb.team_b_id is None:
                # Team-level PAB.
                round_data[stb.team_a_id] = (
                    None,
                    ' ',
                    ' ' * team_player_count,
                    ' ' * team_player_count,
                    self.team_pab_game_points,
                    False,
                    TeamByeType.PAB,
                )
                continue

            symbols_a: list[str] = []
            symbols_b: list[str] = []
            rid_a: list[str] = []
            rid_b: list[str] = []
            for board in sorted(team_board.boards, key=lambda b: b.index):
                white_tp = board.optional_white_tournament_player
                black_tp = board.black_tournament_player
                wtp_team = white_tp.team_id if white_tp is not None else None
                a_player: TournamentPlayer | None
                b_player: TournamentPlayer | None
                if wtp_team == stb.team_a_id:
                    a_player, b_player = white_tp, black_tp
                else:
                    a_player, b_player = black_tp, white_tp
                rid_a.append(
                    rid_by_player_id.get(a_player.id, ' ')
                    if a_player is not None
                    else ' '
                )
                rid_b.append(
                    rid_by_player_id.get(b_player.id, ' ')
                    if b_player is not None
                    else ' '
                )
                result = board.result
                a_is_white = (
                    a_player is not None
                    and white_tp is not None
                    and white_tp.id == a_player.id
                )
                if result == Result.WIN:
                    a_sym, b_sym = ('1', '0') if a_is_white else ('0', '1')
                elif result == Result.LOSS:
                    a_sym, b_sym = ('0', '1') if a_is_white else ('1', '0')
                elif result == Result.DRAW:
                    a_sym, b_sym = '=', '='
                else:
                    a_sym, b_sym = ' ', ' '
                symbols_a.append(a_sym)
                symbols_b.append(b_sym)
            # Pad to team_player_count.
            while len(symbols_a) < team_player_count:
                symbols_a.append(' ')
                symbols_b.append(' ')
                rid_a.append(' ')
                rid_b.append(' ')
            # Colour of team_a on board 0 → team_a's match colour.
            color_a = ' '
            color_b = ' '
            for board in team_board.boards:
                if board.index != 0:
                    continue
                white_team_id, _black_team_id = team_board.board_team_ids(board)
                if white_team_id == stb.team_a_id:
                    color_a, color_b = 'w', 'b'
                else:
                    color_a, color_b = 'b', 'w'
                break
            round_data[stb.team_a_id] = (
                tpn_by_team_id.get(stb.team_b_id),
                color_a,
                ''.join(symbols_a),
                ''.join(rid_a),
                a_gp,
                False,
                None,
            )
            round_data[stb.team_b_id] = (
                tpn_by_team_id.get(stb.team_a_id),
                color_b,
                ''.join(symbols_b),
                ''.join(rid_b),
                b_gp,
                False,
                None,
            )

        team_totals = self._team_trf_totals_after(after_round)
        nickname_by_team_id = self._team_trf_nickname_map(tpn_by_team_id)
        max_tpn = max(tpn_by_team_id.values(), default=0)
        tpn_width = max(2, len(str(max_tpn)))
        results_width = max(team_player_count, 4)
        rid_width = results_width
        for tpn, team in teams_by_tpn:
            mp, gp = team_totals.get(team.id, (0.0, 0.0))
            nickname = nickname_by_team_id[team.id]
            header_801 = f'{tpn:>{tpn_width}} {nickname:<5} {mp:>4.1f} {gp:>4.1f}'
            header_802 = f'{tpn:>{tpn_width}} {nickname:<5} {mp:>6.1f} {gp:>6.1f}'
            blocks_801: list[str] = []
            blocks_802: list[str] = []
            for round_ in range(1, after_round + 1):
                entry = per_round.get(round_, {}).get(team.id)
                if entry is None:
                    blocks_801.append(
                        f'  {"":>{tpn_width}} {"":1}'
                        f' {"":<{results_width}} {"":<{rid_width}}'
                    )
                    blocks_802.append(f'  {"":>{tpn_width}} {"":1} {"":>4} {"":1}')
                    continue
                opp_tpn, colour, board_str, rid_str, team_gp, _, bye = entry
                # 801: per the spec, an opponent-less round (bye) is
                # represented by leaving the opponent / colour / board
                # results columns blank — keep block width constant.
                if bye is not None:
                    opp_801 = ' ' * tpn_width
                    colour_801 = ' '
                    opp_802 = f'{bye:>3}'
                    colour_802 = ' '
                else:
                    opp_801 = (
                        f'{opp_tpn:>{tpn_width}}'
                        if opp_tpn is not None
                        else ' ' * tpn_width
                    )
                    colour_801 = colour
                    opp_802 = f'{opp_tpn:>3}' if opp_tpn is not None else '   '
                    colour_802 = colour
                blocks_801.append(
                    f'  {opp_801} {colour_801:1}'
                    f' {board_str:<{results_width}}'
                    f' {rid_str:<{rid_width}}'
                )
                blocks_802.append(f'  {opp_802} {colour_802:1} {team_gp:>4.1f}  ')
            pairings.append(header_801 + ''.join(blocks_801))
            results.append(header_802 + ''.join(blocks_802))
        return pairings, results

    def _team_trf_tpn_map(self) -> dict[int, int]:
        """``team.id`` → unique TRF26 team pairing number (TPN).
        ``team.pairing_number`` is a user-editable hint and may
        collide across teams of the same tournament in malformed
        databases; TRF26 requires unique TPNs, so collisions are
        pushed to the next free slot, in team-UI order."""
        from data.pairings.engines import _team_ui_sort_key

        teams = sorted(self.teams, key=_team_ui_sort_key)
        tpn_by_team_id: dict[int, int] = {}
        used: set[int] = set()
        next_tpn = 1
        for team in teams:
            if team.pairing_number is not None and team.pairing_number not in used:
                tpn_by_team_id[team.id] = team.pairing_number
                used.add(team.pairing_number)
                next_tpn = max(next_tpn, team.pairing_number + 1)
        for team in teams:
            if team.id in tpn_by_team_id:
                continue
            while next_tpn in used:
                next_tpn += 1
            tpn_by_team_id[team.id] = next_tpn
            used.add(next_tpn)
            next_tpn += 1
        return tpn_by_team_id

    def _team_trf_nickname_map(self, tpn_by_team_id: dict[int, int]) -> dict[int, str]:
        """``team.id`` → unique 5-char TRF26 310 nickname. Derived from
        the team name; same-club teams (e.g. ``Rennes Paul Bert A/B/C``)
        all reduce to the same prefix, so on a collision the trailing
        characters are replaced with a counter until unique (TRF26
        requires distinct nicknames). Assigned in TPN order for
        determinism. Shared by the 310 and 801/802 records so a team's
        nickname is identical across them."""
        nicknames: dict[int, str] = {}
        used: set[str] = set()
        teams_by_id = self.event.teams_by_id
        for team_id in sorted(tpn_by_team_id, key=lambda t: tpn_by_team_id[t]):
            team = teams_by_id.get(team_id)
            base = ((team.name[:5] if team is not None else '') or 'T').upper()
            nickname = base
            seq = 0
            while nickname in used:
                seq += 1
                tag = str(seq)
                nickname = (base[: max(1, 5 - len(tag))] + tag)[:5]
            used.add(nickname)
            nicknames[team_id] = nickname
        return nicknames

    def _team_pabs_record(
        self, *, after_round: int, tpn_by_team_id: dict[int, int]
    ) -> 'TrfTeamPABs | None':
        """TRF26 320 record: team-PAB match / game points + per-round
        team that received the PAB. Built when the team-PAB scores
        differ from defaults (draw match-points, draw game-points per
        FIDE C.04.6 §1.4) or when at least one team has actually
        received a PAB so far."""
        from data.input_output.trf.trf_data import TrfTeamPABs

        match_points = self.match_points
        draw_mp = match_points.get(Result.DRAW, 1.0)
        pab_mp = match_points.get(Result.PAIRING_ALLOCATED_BYE, draw_mp)
        pab_gp = self.team_pab_game_points
        team_id_by_round: dict[int, int] = {}
        for team_board in self.team_boards_by_id.values():
            if team_board.round > after_round:
                continue
            stb = team_board.stored_team_board
            if stb.team_b_id is not None or stb.bye_type not in (
                None,
                TeamByeType.PAB,
            ):
                continue
            tpn = tpn_by_team_id.get(stb.team_a_id)
            if tpn is not None:
                team_id_by_round[team_board.round] = tpn
        default_gp = float(self.team_player_count or 0) * Result.DRAW.point_value
        non_default = pab_mp != draw_mp or pab_gp != default_gp
        if not team_id_by_round and not non_default:
            return None
        return TrfTeamPABs(
            match_points=pab_mp,
            game_points=pab_gp,
            team_id_by_round=team_id_by_round,
        )

    def team_primary_score_before_round(self, team_id: int, round_: int) -> float:
        """The team's cumulative primary score (match points or game
        points, per :attr:`primary_score`) at the start of ``round_``
        — i.e. after rounds 1..``round_``−1 have been accounted for.
        Returns ``0.0`` for teams with no prior team_board entries."""
        totals = self._team_trf_totals_after(round_ - 1)
        mp, gp = totals.get(team_id, (0.0, 0.0))
        return mp if self.primary_score == ScoreType.MATCH_POINTS else gp

    def _team_trf_totals_after(
        self, after_round: int
    ) -> dict[int, tuple[float, float]]:
        """Per-team ``(match_points, game_points)`` cumulative through
        ``after_round``, bonus / penalty points included. Returned dict
        is keyed by ``team.id``; teams with no team_board entries simply
        get ``(0.0, 0.0)``. PAB (team-level bye) awards the configured
        PAB match points and the tournament's PAB game points (default
        behaviour mirrors :meth:`team_standings`)."""
        match_points = self.match_points
        win_mp = match_points.get(Result.WIN, 2.0)
        draw_mp = match_points.get(Result.DRAW, 1.0)
        loss_mp = match_points.get(Result.LOSS, 0.0)
        pab_mp = match_points.get(Result.PAIRING_ALLOCATED_BYE, draw_mp)
        team_player_count = float(self.team_player_count or 0)
        win_gp_per_player = Result.WIN.point_value
        draw_gp_per_player = Result.DRAW.point_value
        totals: dict[int, list[float]] = {}
        for team_board in self.team_boards_by_id.values():
            if team_board.round > after_round:
                continue
            stb = team_board.stored_team_board
            a_gp, b_gp = team_board.game_points
            a_entry = totals.setdefault(stb.team_a_id, [0.0, 0.0])
            if stb.team_b_id is None:
                match stb.bye_type:
                    case TeamByeType.ZPB:
                        a_entry[0] += loss_mp
                    case TeamByeType.HPB:
                        a_entry[0] += draw_mp
                        a_entry[1] += team_player_count * draw_gp_per_player
                    case TeamByeType.FPB:
                        a_entry[0] += win_mp
                        a_entry[1] += team_player_count * win_gp_per_player
                    case _ if self.team_bye_is_rest:
                        # Round-robin rest game: no points.
                        pass
                    case _:
                        a_entry[0] += pab_mp
                        a_entry[1] += self.team_pab_game_points
                continue
            b_entry = totals.setdefault(stb.team_b_id, [0.0, 0.0])
            a_entry[1] += a_gp
            b_entry[1] += b_gp
            if a_gp > b_gp:
                a_entry[0] += win_mp
                b_entry[0] += loss_mp
            elif a_gp < b_gp:
                a_entry[0] += loss_mp
                b_entry[0] += win_mp
            else:
                a_entry[0] += draw_mp
                b_entry[0] += draw_mp
        # Bonus / penalty points count towards the standings, and the
        # 310 record carries the standings — the 299 records emitted
        # alongside say where the difference from the played results
        # came from. Without this the totals would contradict the rank
        # written on the same line, which does include them.
        for team in self.teams:
            for round_ in range(1, self._point_adjustment_bound(after_round) + 1):
                mp_adj, gp_adj = self.effective_point_adjustment(team.id, round_)
                if not mp_adj and not gp_adj:
                    continue
                entry = totals.setdefault(team.id, [0.0, 0.0])
                entry[0] += mp_adj
                entry[1] += gp_adj
        return {team_id: (mp, gp) for team_id, (mp, gp) in totals.items()}

    def _team_trf_encoded_type(self) -> str:
        """``FIDE_TEAM_TYPE<X>_<primary>[_<secondary>]`` per TRF26 §7
        codes table. ``X`` is the colour-preference rule (A or B);
        when ``TeamColourType.NONE`` is selected the ``TYPE<X>_``
        infix is dropped, matching the FIDE convention for events that
        opt out of colour preferences. The primary-only code is what
        "the secondary score is not used for colour allocation" looks
        like on the wire."""
        primary = 'MP' if self.primary_score == ScoreType.MATCH_POINTS else 'GP'
        colour_type = self.team_colour_type
        infix = (
            f'TYPE{colour_type.value}_' if colour_type != TeamColourType.NONE else ''
        )
        if not self.secondary_score_for_colours:
            return f'FIDE_TEAM_{infix}{primary}'
        secondary = 'MP' if self.secondary_score == ScoreType.MATCH_POINTS else 'GP'
        return f'FIDE_TEAM_{infix}{primary}_{secondary}'

    def _trf_round_byes(self) -> list['TrfRoundBye']:
        from data.input_output.trf.trf_data import TrfRoundBye

        round_byes: list[TrfRoundBye] = []
        for round_ in range(1, self.rounds + 1):
            pairing_numbers_by_bye: dict[Result, list[int]] = defaultdict(list)
            for (
                pairing_number,
                player,
            ) in self.tournament_players_by_pairing_number.items():
                result = player.pairings[round_].result
                if result.is_next_round_bye:
                    pairing_numbers_by_bye[result].append(pairing_number)
            for bye, pairing_numbers in pairing_numbers_by_bye.items():
                round_bye = TrfRoundBye(
                    type=bye.to_trf.upper(),
                    round=round_,
                    pairing_numbers=pairing_numbers,
                )
                round_byes.append(round_bye)
        return round_byes

    def _team_trf_round_byes(
        self,
        *,
        after_round: int,
        tpn_by_team_id: dict[int, int],
        next_round_pairings_as_zpb: bool = False,
    ) -> list['TrfRoundBye']:
        """TRF26 240 records (team-mode interpretation): one entry per
        (round, bye type) listing the team TPNs flagged with
        ``HPB`` / ``FPB`` / ``ZPB`` envelopes. Emits records for every
        round through ``after_round + 1`` so the round-trip preserves
        past manual byes too — bbpPairings only consults the entry
        for the round it's pairing, but ignores the rest harmlessly.

        When *next_round_pairings_as_zpb* is set, teams already on
        any envelope for round ``after_round + 1`` (real matches,
        PAB envelopes) are additionally emitted as ``Z`` byes so
        bbpPairings excludes them when generating complementary
        pairings."""
        from data.input_output.trf.trf_data import TrfRoundBye

        type_map: dict[str, str] = {
            TeamByeType.FPB: 'F',
            TeamByeType.HPB: 'H',
            TeamByeType.ZPB: 'Z',
        }
        last_round = min(after_round + 1, self.rounds)
        next_round = after_round + 1
        records: list[TrfRoundBye] = []
        for round_ in range(1, last_round + 1):
            tpns_by_type: dict[str, list[int]] = defaultdict(list)
            for tb in self.get_round_team_boards(round_):
                stb = tb.stored_team_board
                if stb.team_b_id is None:
                    mapped = type_map.get(stb.bye_type or '')
                    if mapped is None:
                        if next_round_pairings_as_zpb and round_ == next_round:
                            tpn = tpn_by_team_id.get(stb.team_a_id)
                            if tpn is not None:
                                tpns_by_type['Z'].append(tpn)
                        continue
                    tpn = tpn_by_team_id.get(stb.team_a_id)
                    if tpn is not None:
                        tpns_by_type[mapped].append(tpn)
                elif next_round_pairings_as_zpb and round_ == next_round:
                    for tid in (stb.team_a_id, stb.team_b_id):
                        tpn = tpn_by_team_id.get(tid)
                        if tpn is not None:
                            tpns_by_type['Z'].append(tpn)
            if round_ == next_round:
                # Absent teams (check_in=False) are excluded from
                # pairing — emit a Z bye for each one not already in
                # another envelope this round.
                already_enveloped: set[int] = {
                    stb.team_a_id
                    for tb in self.get_round_team_boards(round_)
                    for stb in [tb.stored_team_board]
                } | {
                    stb.team_b_id
                    for tb in self.get_round_team_boards(round_)
                    for stb in [tb.stored_team_board]
                    if stb.team_b_id is not None
                }
                for team in self.teams:
                    if team.check_in:
                        continue
                    if team.id in already_enveloped:
                        continue
                    tpn = tpn_by_team_id.get(team.id)
                    if tpn is not None and tpn not in tpns_by_type['Z']:
                        tpns_by_type['Z'].append(tpn)
            for t, tpns in tpns_by_type.items():
                records.append(
                    TrfRoundBye(type=t, round=round_, pairing_numbers=sorted(tpns))
                )
        return records

    def _team_forfeited_matches(
        self,
        *,
        after_round: int,
        tpn_by_team_id: dict[int, int],
    ) -> list['TrfTeamForfeitedMatch']:
        """TRF26 330 records — one entry per played team match where
        one (or both) teams forfeited by failing to field any player.
        Type ``W`` = white team won by forfeit (black team forfeited),
        ``B`` = black team won, ``D`` = double forfeit. The colour each
        team plays at slot 0 of the match (driven by ``color_pattern``)
        decides which team is "white" for this encoding."""
        from data.input_output.trf.trf_data import TrfTeamForfeitedMatch

        pattern = self.color_pattern or ''
        team_a_board0_white = pattern[:1].upper() != BoardColor.BLACK.value
        records: list[TrfTeamForfeitedMatch] = []
        for round_ in range(1, after_round + 1):
            for tb in self.get_round_team_boards(round_):
                stb = tb.stored_team_board
                if stb.team_b_id is None:
                    continue
                team_a = self.event.teams_by_id.get(stb.team_a_id)
                team_b = self.event.teams_by_id.get(stb.team_b_id)
                if team_a is None or team_b is None:
                    continue
                a_empty = all(p is None for p in team_a.effective_round_slots(round_))
                b_empty = all(p is None for p in team_b.effective_round_slots(round_))
                if not (a_empty or b_empty):
                    continue
                a_tpn = tpn_by_team_id.get(team_a.id)
                b_tpn = tpn_by_team_id.get(team_b.id)
                if a_tpn is None or b_tpn is None:
                    continue
                if team_a_board0_white:
                    white_tpn, black_tpn = a_tpn, b_tpn
                    white_empty, black_empty = a_empty, b_empty
                else:
                    white_tpn, black_tpn = b_tpn, a_tpn
                    white_empty, black_empty = b_empty, a_empty
                # TRF26 330 type is two chars: white-side, black-side.
                # ``+`` = forfeit win, ``-`` = forfeit loss.
                if white_empty and black_empty:
                    forfeit_type = '--'
                elif black_empty:
                    forfeit_type = '+-'
                else:
                    forfeit_type = '-+'
                records.append(
                    TrfTeamForfeitedMatch(
                        type=forfeit_type,
                        round=round_,
                        white_team_id=white_tpn,
                        black_team_id=black_tpn,
                    )
                )
        return records

    def _trf_accelerated_rounds(self) -> list['TrfAcceleratedRound']:
        from data.input_output.trf.trf_data import TrfAcceleratedRound

        variation = self.pairing_variation
        if not variation.include_accelerated_rules_in_trf:
            return []
        rounds = self.rounds
        acceleration_rules = variation.get_tournament_accelerated_rules(self)
        tpn_range_by_group = variation.get_acceleration_number_range_by_group(self)
        accelerated_rounds: list[TrfAcceleratedRound] = [
            TrfAcceleratedRound(
                match_points=None,
                game_points=rule.vpoints,
                first_round=rule.resolved_round_range(self)[0],
                last_round=rule.resolved_round_range(self)[1],
                first_id=number_range[0],
                last_id=number_range[1],
            )
            for rule in acceleration_rules
            if (number_range := rule.resolved_number_range(self)) is not None
        ]
        players_by_tpn = self.tournament_players_by_pairing_number
        for group, (min_tpn, max_tpn) in tpn_range_by_group.items():
            group_rules = [
                rule
                for rule in acceleration_rules
                if rule.number_range is None and rule.group == group
            ]
            if not any(rule.points_threshold for rule in group_rules):
                accelerated_rounds += [
                    TrfAcceleratedRound(
                        match_points=None,
                        game_points=rule.vpoints,
                        first_round=rule.resolved_round_range(self)[0],
                        last_round=rule.resolved_round_range(self)[1],
                        first_id=min_tpn,
                        last_id=max_tpn,
                    )
                    for rule in group_rules
                ]
                continue

            for tpn, player in players_by_tpn.items():
                if not min_tpn <= tpn <= max_tpn:
                    continue
                vpoints_history = [
                    self._calculate_player_virtual_points(player, at_round=round_)
                    for round_ in range(1, rounds + 1)
                ]
                first_round = 1
                previous_vpoints = vpoints_history[0]
                for index in range(1, rounds):
                    vpoints = vpoints_history[index]
                    if vpoints == previous_vpoints:
                        continue
                    if previous_vpoints != 0:
                        accelerated_rounds.append(
                            TrfAcceleratedRound(
                                match_points=None,
                                game_points=previous_vpoints,
                                first_round=first_round,
                                last_round=index,
                                first_id=tpn,
                                last_id=tpn,
                            )
                        )
                    first_round = index + 1
                    previous_vpoints = vpoints
                if previous_vpoints != 0:
                    accelerated_rounds.append(
                        TrfAcceleratedRound(
                            match_points=None,
                            game_points=previous_vpoints,
                            first_round=first_round,
                            last_round=rounds,
                            first_id=tpn,
                            last_id=tpn,
                        )
                    )
        return accelerated_rounds

    def has_acceleration_beyond_last_round(self) -> bool:
        """Whether an acceleration entry would reach past the final round.

        bbpPairings stores one acceleration entry per round up to the entry's
        last round and rejects a player holding more entries than the
        tournament has rounds. This happens when a rule's last round outlives
        a later reduction of the round count (the settings form only validates
        the range at save time)."""
        return any(
            accelerated_round.last_round > self.rounds
            for accelerated_round in self._trf_accelerated_rounds()
        )

    def set_tournament_player_points(
        self, tournament_player: TournamentPlayer, *, before_round: int
    ):
        """Sets the points of a player before round *before_round*."""
        if self.pairing_system.id == 'KEIZER':
            # A Keizer total is not a game-point count; it comes from the
            # whole-table scorer. Points and board-ordering points are the
            # same figure — board 1 is the leader.
            total = self.keizer_scorer.total(
                tournament_player, after_round=before_round - 1
            )
            tournament_player.points = total
            tournament_player.vpoints = total
            return
        vpoints = self._calculate_player_virtual_points(
            tournament_player, at_round=before_round
        )
        tournament_player.compute_points(before_round=before_round)
        assert tournament_player.points is not None
        tournament_player.vpoints = tournament_player.points + vpoints

    @property
    def keizer_scorer(self) -> 'KeizerScorer':
        """The whole-table Keizer scorer, rebuilt after the per-player
        compute caches are cleared so it always reflects current results."""
        if self._keizer_scorer is None:
            from data.pairings.keizer import KeizerScorer

            self._keizer_scorer = KeizerScorer(self)
        return self._keizer_scorer

    def _calculate_player_virtual_points(
        self, tournament_player: TournamentPlayer, *, at_round: int
    ) -> float:
        if self.pairing_variation.vpoints_use_pairing_numbers:
            self.set_tournament_players_pairing_numbers()
        return self.pairing_variation.compute_virtual_points(
            self, tournament_player, at_round
        )

    def store_illegal_move(self, tournament_player: TournamentPlayer):
        """Store an illegal move for the given `tournament_player`, for the current
        round."""
        with EventDatabase(self.event.uniq_id, write=True) as database:
            tournament_player.pairings[self.current_round].add_illegal_move(database)

    def delete_illegal_move(self, tournament_player: TournamentPlayer) -> bool:
        """Deletes one illegal move for the given `tournament_player` for the current round."""
        with EventDatabase(self.event.uniq_id, write=True) as database:
            deleted = tournament_player.pairings[
                self.current_round
            ].delete_illegal_move(database)
        return deleted

    def correct_ranking_round(self, ranking_round: int | None = None) -> int:
        """Returns a correct round number that corresponds the best to a given round number."""
        if ranking_round is None:
            return self.max_ranking_round
        else:
            return max(0, min(ranking_round, self.max_ranking_round))

    def compute_tournament_player_ranks(
        self, *, after_round: int | None = None
    ) -> dict[int, TournamentPlayer]:
        """compute and return the ranks of all the players after round *after_round*."""
        if after_round is None:
            after_round = self.max_ranking_round

        self._compute_caching_enabled = True
        try:
            self._compute_tournament_player_ranks(after_round)
        finally:
            self._compute_caching_enabled = False
        assert self._tournament_players_by_rank is not None
        return self._tournament_players_by_rank

    def _compute_tournament_player_ranks(self, after_round: int) -> None:
        self._keizer_scorer = None
        for player in self.tournament_players:
            player.clear_compute_caches()
        self.set_tournament_players_pairing_numbers()
        tie_breaks = self.tie_breaks
        for tie_break in tie_breaks:
            for player_id, variable in tie_break.get_player_variables(
                self, after_round
            ).items():
                player = self.tournament_players_by_id[player_id]
                player.tie_break_variables[tie_break.id] = variable
        keizer = self.pairing_system.id == 'KEIZER'
        for player in self.tournament_players:
            player.points = (
                self.keizer_scorer.total(player, after_round=after_round)
                if keizer
                else player.standings_points(after_round)
            )
            player.compute_tie_break_values(
                after_round=after_round, tie_breaks=tie_breaks
            )

        for index, tie_break in enumerate(tie_breaks):
            if tie_break.is_computed_per_player:
                continue
            value_by_player_id = tie_break.compute_all_player_values(
                self,
                tie_break_index=index,
                after_round=after_round,
            )
            for player_id, tie_break_value in value_by_player_id.items():
                player = self.tournament_players_by_id[player_id]
                player.tie_break_values[index].value = tie_break_value

        # Players excluded from the standings (FIDE 6.6 round-robin rule) are
        # ranked last regardless of their score, so the competitors keep a
        # contiguous ranking. They stay in the crosstable for the record.
        sorted_tournament_players = sorted(
            self.tournament_players,
            key=lambda p: (p.is_excluded_from_standings, p.rank_sort_key),
        )
        self._tournament_players_by_rank = {
            rank: tournament_player
            for rank, tournament_player in enumerate(sorted_tournament_players, start=1)
        }
        for rank, player in self._tournament_players_by_rank.items():
            player.rank = rank
        for tie_break_index, tie_break in enumerate(tie_breaks):
            if not tie_break.display_rank_delta:
                continue
            players_ranked_without_tie_break = sorted(
                self.tournament_players,
                key=lambda p: p.rank_sort_key_without_tie_break(tie_break_index),
            )
            for rank_without_tie_break, player in enumerate(
                players_ranked_without_tie_break, start=1
            ):
                player.tie_break_values[tie_break_index].rank_progress = (
                    rank_without_tie_break - player.rank
                )

    @property
    def tournament_players_by_rank(self) -> dict[int, TournamentPlayer]:
        assert self._tournament_players_by_rank is not None, (
            'Tournament._tournament_players_by_rank is not set, call Tournament.compute_player_ranks() before.'
        )
        return self._tournament_players_by_rank

    def ensure_tournament_player_ranks_computed(self) -> None:
        """Compute player ranks on demand when they have not been computed
        yet, so rank-dependent derivations (e.g. a ranking screen's default
        name) work without the caller having to precompute them."""
        if self._tournament_players_by_rank is None:
            self.compute_tournament_player_ranks()

    def add_result(self, board: Board, white_result: Result):
        """Stores the given result for the given `board` in the current round.
        Stores the `white_result` directly, and uses the opposite result
        as the black's result.
        Assumes that no asymmetric result was entered."""
        if board.optional_white_tournament_player is None:
            raise ValueError(
                f'Board [{board.stored_board.id}] has a forfeit hole, '
                'its result cannot be changed.'
            )
        assert board.black_tournament_player is not None

        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            board.white_pairing.update_result(event_database, white_result)
            board.black_pairing.update_result(
                event_database, white_result.opposite_result
            )

            board.set_last_result_update(board.white_pairing.result, event_database)

        logger.info(
            'Added result: %s %s %d.%d %s %s %d %s %s %s %d.',
            self.event.uniq_id,
            self.name,
            board.round,
            board.id,
            board.white_tournament_player.last_name,
            board.white_tournament_player.first_name or '',
            board.white_tournament_player.rating,
            white_result,
            board.black_tournament_player.last_name,
            board.black_tournament_player.first_name or '',
            board.black_tournament_player.rating,
        )

        # Remove the cached 'playing' value so that the pairing tab updates correctly
        self.__dict__.pop('playing', None)

    def delete_result(self, board: Board):
        """Deletes the result for the given `board`."""
        assert board.black_tournament_player is not None
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            board.white_pairing.update_result(event_database, Result.NO_RESULT)
            board.black_pairing.update_result(event_database, Result.NO_RESULT)
            board.set_last_result_update(board.white_pairing.result, event_database)
        logger.info(
            'Removed result: %s %s %d.%d.',
            self.event.uniq_id,
            self.name,
            board.round,
            board.id,
        )

        # Remove the cached 'playing' value so that the pairing tab updates correctly
        self.__dict__.pop('playing', None)

    def check_in_player(self, player: Player, check_in: bool):
        """Stores the `check_in` status for the given `player`."""
        with EventDatabase(self.event.uniq_id, write=True) as database:
            database.set_player_check_in(player.id, check_in)
        player.stored_player.check_in = check_in
        player.__dict__.pop('check_in_status', None)

    def check_in_team(self, team: 'Team', check_in: bool):
        """Stores the per-team check-in status."""
        with EventDatabase(self.event.uniq_id, write=True) as database:
            team.set_check_in(check_in, database)

    def check_in_all_teams(self, check_in: bool):
        teams = [team for team in self.teams if team.check_in != check_in]
        if not teams:
            return
        with EventDatabase(self.event.uniq_id, write=True) as database:
            database.set_team_check_in_for_tournament(self.id, check_in)
            for team in teams:
                team.stored_team.check_in = check_in

    @property
    def absent_teams(self) -> list['Team']:
        return [team for team in self.teams if not team.check_in]

    @property
    def team_check_in_status_grouped_counts(self) -> 'Counter[CheckInStatus]':
        counter: Counter[CheckInStatus] = Counter()
        for team in self.teams:
            counter[
                CheckInStatus.PRESENT if team.check_in else CheckInStatus.ABSENT
            ] += 1
        return counter

    def check_in_all_players(self, check_in: bool):
        player_ids = []
        for player in self.players:
            if player.check_in != check_in:
                player_ids.append(player.id)
                player.stored_player.check_in = check_in
        with EventDatabase(self.event.uniq_id, write=True) as database:
            database.set_players_check_in(player_ids, check_in)

    def add_player_to_tournament(
        self,
        stored_player: StoredPlayer,
        event_database: EventDatabase | None = None,
    ):
        assert stored_player.id is not None
        current_round = self.current_round
        last_zpb_round = (
            current_round
            if current_round == 0 or self.is_round_finished(current_round)
            else current_round - 1
        )
        stored_tournament_player = StoredTournamentPlayer(
            tournament_id=self.id,
            player_id=stored_player.id,
            pairing_number=None,
            manual_tiebreak=None,
            stored_pairings=[
                StoredPairing(
                    tournament_id=self.id,
                    player_id=stored_player.id,
                    round_=round_,
                    result=Result.ZERO_POINT_BYE,
                    board_id=None,
                )
                for round_ in range(1, last_zpb_round + 1)
            ],
        )
        if event_database:
            event_database.add_stored_tournament_player(stored_tournament_player)
        else:
            with EventDatabase(self.event.uniq_id, True) as database:
                database.add_stored_tournament_player(stored_tournament_player)
        self.tournament_players_by_id[stored_player.id] = TournamentPlayer(
            self, stored_tournament_player
        )

    def register_rostered_player(self, player_id: int):
        """Take note that a player has joined a team of this tournament.

        A team tournament stores no ``tournament_player`` rows — the
        loader synthesises them from team membership (see
        ``load_stored_tournament_players``) — so a player added to a team
        after the event was loaded is absent from this tournament until
        the next reload, and the players tab shows them with no
        tournament of their own.
        """
        if player_id in self.tournament_players_by_id:
            return
        stored_tournament_player = StoredTournamentPlayer(
            tournament_id=self.id,
            player_id=player_id,
            pairing_number=None,
            manual_tiebreak=None,
            stored_pairings=[],
        )
        self.stored_tournament.stored_tournament_players.append(
            stored_tournament_player
        )
        self.tournament_players_by_id[player_id] = TournamentPlayer(
            self, stored_tournament_player
        )
        self._reset_player_derived_cache()

    def unregister_rostered_player(self, player_id: int):
        """The reverse: a player has left a team of this tournament."""
        if player_id not in self.tournament_players_by_id:
            return
        del self.tournament_players_by_id[player_id]
        self.stored_tournament.stored_tournament_players = [
            stored_tournament_player
            for stored_tournament_player in (
                self.stored_tournament.stored_tournament_players
            )
            if stored_tournament_player.player_id != player_id
        ]
        self._reset_player_derived_cache()

    def _reset_player_derived_cache(self):
        """Drop what is computed from the tournament's player list."""
        Utils.reset_cached_properties(
            self,
            'player_count',
            'exclusive_player_ids',
            'tournament_players_by_fide_id',
            'tournament_players_by_starting_rank',
            'tournament_players_by_pairing_number',
            'sorted_tournament_players',
            'sorted_tournament_players_without_unpaired',
        )

    def get_available_board_indexes(self, round_: int) -> list[int]:
        board_indexes = [
            board.index for board in self.get_round_boards(round_) if not board.exempt
        ]
        max_board_count = (
            len(self.tournament_players) // 2 + len(self.tournament_players) % 2
        )
        return [
            index for index in range(0, max_board_count) if index not in board_indexes
        ]

    def first_unused_board_index(self, round_: int) -> int:
        """Smallest table index occupied by NO board this round — counting
        one-sided forfeit (exempt) boards, which still own a real table.
        Unlike :meth:`get_available_board_indexes` (which frees an exempt
        bye's index for reuse), this never reuses a hole's index, so a manual
        flat pairing can't be placed on top of an existing forfeit table."""
        used = {board.index for board in self.get_round_boards(round_)}
        index = 0
        while index in used:
            index += 1
        return index

    def get_pab_board_index(
        self,
        round_: int,
        new_indexes: list[int] | None = None,
    ) -> int:
        board_indexes = [
            board.index for board in self.get_round_boards(round_) if not board.exempt
        ] + (new_indexes or [])
        if not board_indexes:
            return 0
        return max(board_indexes) + 1

    def set_tournament_players_pairing_numbers(self):
        # Set up the cached property, which makes sure the
        # pairing number checking process is not executed twice
        __ = self.tournament_players_by_pairing_number

    def _set_tournament_players_pairing_numbers(self):
        """Set the pairing numbers of all the players in the tournament.
        Returns a list of players sorted by pairing number."""
        inserted_tournament_players: list[TournamentPlayer] = []
        current_tournament_players: list[TournamentPlayer] = []
        current_pairing_numbers: set[int] = set()
        for tournament_player in self.tournament_players:
            if tournament_player.pairing_number is None:
                inserted_tournament_players.append(tournament_player)
            else:
                current_tournament_players.append(tournament_player)
                current_pairing_numbers.add(tournament_player.pairing_number)
        # Holes in the numbering, i.e. numbers that were attributed and
        # since freed. Counted over the players that *have* a number, not
        # the whole field: a player still waiting for one has never held
        # a number, so counting them would report the numbers about to be
        # handed out as deleted — and on the first pairing, where nobody
        # is numbered yet, that means all of them.
        deleted_pairing_numbers = set(
            range(1, len(current_tournament_players) + 1)
        ).difference(current_pairing_numbers)
        settings_updated = (
            self.pairing_variation.update_settings_from_deleted_pairing_numbers(
                self, deleted_pairing_numbers
            )
        )
        if self.current_round >= 4:
            # FIDE Handbook C.04.2.B.3: No modification of a pairing number
            # is allowed after the fourth round has been paired.
            # --> We keep the numbering only to inserted / deleted players
            if (
                not inserted_tournament_players
                and not deleted_pairing_numbers
                and not settings_updated
            ):
                return
            sorted_tournament_players = sorted(
                current_tournament_players, key=attrgetter('pairing_number')
            )
        else:
            sorted_tournament_players = sorted(
                current_tournament_players, key=attrgetter('starting_rank_sort_key')
            )
        # Handing out the numbers for the first time is not an insertion:
        # nobody is being slotted into an existing order, so the pairing
        # settings that address numbers (acceleration rules) must not be
        # shifted — they were written against the numbering about to be
        # created. Shifting them once per player would march a rule for
        # numbers 1-2 clear off the end of the field.
        numbers_already_attributed = bool(current_tournament_players)
        for tournament_player in inserted_tournament_players:
            tournament_player_index = next(
                (
                    index
                    for index, player_ in enumerate(sorted_tournament_players)
                    if player_.starting_rank_sort_key
                    > tournament_player.starting_rank_sort_key
                ),
                len(sorted_tournament_players),
            )
            sorted_tournament_players.insert(tournament_player_index, tournament_player)
            if numbers_already_attributed:
                settings_updated |= (
                    self.pairing_variation.update_settings_from_added_pairing_number(
                        self, tournament_player_index + 1
                    )
                )

        tournament_players_by_updated_pairing_number = {
            pairing_number: player
            for pairing_number, player in enumerate(sorted_tournament_players, start=1)
            if pairing_number != player.pairing_number
        }
        if not tournament_players_by_updated_pairing_number:
            return
        for (
            pairing_number,
            tournament_player,
        ) in tournament_players_by_updated_pairing_number.items():
            tournament_player.stored_tournament_player.pairing_number = pairing_number
        if self.is_team_tournament:
            # A team tournament's players are synthesised from the team
            # rosters and have no stored tournament_player row to persist
            # to, so their numbering lives in memory only. Skipping the
            # write also keeps the FFE-upload conversion — which runs on a
            # throwaway copy whose database is already closed — from
            # reopening a database that is no longer there.
            return
        with EventDatabase(self.event.uniq_id, True) as database:
            for (
                pairing_number,
                tournament_player,
            ) in tournament_players_by_updated_pairing_number.items():
                database.set_tournament_player_pairing_number(
                    tournament_player.stored_tournament_player
                )
            if settings_updated:
                database.set_tournament_pairing_settings(
                    self.id, self.stored_pairing_settings
                )

    def create_round_pairing(
        self, round_nb: int, white_player_id: int, black_player_id: int | None
    ) -> Board:
        """Creates a pairing for a round."""
        white_tournament_player = self.tournament_players_by_id[white_player_id]
        black_tournament_player = (
            self.tournament_players_by_id[black_player_id] if black_player_id else None
        )
        white_pairing = white_tournament_player.pairings[round_nb]
        black_pairing = (
            black_tournament_player.pairings[round_nb]
            if black_tournament_player
            else None
        )

        if white_pairing.opponent_id:
            raise ValueError(
                f'White player {white_tournament_player.full_name} already has an '
                f'opponent (id: {white_pairing.opponent_id}) for round {round_nb}.'
            )
        if black_tournament_player and black_pairing and black_pairing.opponent_id:
            raise ValueError(
                f'Black player {black_tournament_player.full_name} already has an '
                f'opponent (id: {black_pairing.opponent_id}) for round {round_nb}.'
            )
        with EventDatabase(self.event.uniq_id, True) as database:
            if black_tournament_player and black_pairing:
                result = Result.NO_RESULT
                board = self.get_round_pab_board(round_nb)
                assert board is not None
                board_id = board.identifier
                board.index = self.get_available_board_indexes(round_nb)[0]
                board.replace_player(black_tournament_player, 'black')
                # Re-freeze the fixed number now the second seat is filled.
                set_stored_fields(
                    board.stored_board, fixed_number=board.live_fixed_number or 0
                )
                black_pairing.stored_pairing.result = result.value
                black_pairing.stored_pairing.board_id = board_id
                black_pairing.update(database)
                database.update_stored_board(board.stored_board)
            else:
                result = Result.PAIRING_ALLOCATED_BYE
                # Fill the first free table index (a hole left by an unpaired
                # board), not the end — so a manually paired player lands on
                # the lowest vacant table rather than after the last one.
                available_indexes = self.get_available_board_indexes(round_nb)
                stored_board = StoredBoard(
                    id=None,
                    white_player_id=white_tournament_player.id,
                    black_player_id=None,
                    index=available_indexes[0] if available_indexes else 0,
                )
                board = Board(self, round_nb, stored_board)
                set_stored_fields(
                    stored_board, fixed_number=board.live_fixed_number or 0
                )
                board_id = database.add_stored_board(stored_board)
                set_stored_fields(stored_board, id=board_id)
                self.boards_by_id[board_id] = board
            white_pairing.stored_pairing.result = result.value
            white_pairing.stored_pairing.board_id = board_id
            white_pairing.update(database)
        return board

    def create_team_round_pairing(self, round_: int, team_id: int) -> TeamBoard:
        """Manual team pairing — mirrors :meth:`create_round_pairing`.

        If a PAB envelope (team_b is None, not a manual bye) already
        exists for the round, completes the pair: the existing team
        becomes ``team_a``, *team_id* becomes ``team_b``, individual
        boards are regenerated with both lineups and their results
        flipped from PAB to NO_RESULT. Otherwise creates a fresh PAB
        envelope for *team_id* (with its lineup populated against an
        empty opposing side, just like an engine-assigned bye)."""
        from data.pairings.engines import TeamPairingEngine

        engine = self.pairing_variation.engine
        assert isinstance(engine, TeamPairingEngine)
        round_list = self.stored_tournament.stored_team_boards_by_round.setdefault(
            round_, []
        )
        manual_bye_types = TeamByeType.manual_bye_types()
        pab_stb = next(
            (
                stb
                for stb in round_list
                if stb.team_b_id is None and stb.bye_type not in manual_bye_types
            ),
            None,
        )
        on_board_team_ids: set[int] = set()
        for stb in round_list:
            if stb.team_b_id is None and stb.bye_type in manual_bye_types:
                continue
            on_board_team_ids.add(stb.team_a_id)
            if stb.team_b_id is not None:
                on_board_team_ids.add(stb.team_b_id)
        if team_id in on_board_team_ids and (
            pab_stb is None or pab_stb.team_a_id != team_id
        ):
            raise ValueError(
                f'Team {team_id} already has a team-board for round {round_}.'
            )
        completing_pair = pab_stb is not None and pab_stb.team_a_id != team_id
        stored_boards: list[StoredBoard] = []
        new_stb: StoredTeamBoard | None = None
        boards_to_delete: list[int] = []
        with EventDatabase(self.event.uniq_id, write=True) as database:
            # Clear any existing manual bye envelope (HPB/FPB/ZPB) for
            # this team — pairing supersedes it.
            existing_byes = [
                stb
                for stb in round_list
                if stb.team_a_id == team_id
                and stb.team_b_id is None
                and stb.bye_type in manual_bye_types
            ]
            for bye_stb in existing_byes:
                if bye_stb.id is not None:
                    database.delete_stored_team_board(bye_stb.id)
                round_list.remove(bye_stb)
            if completing_pair:
                assert pab_stb is not None
                # Drop the PAB-side individual boards; new ones with
                # both lineups will be built below.
                for board in list(self.boards_by_id.values()):
                    if board.stored_board.team_board_id == pab_stb.id:
                        boards_to_delete.append(board.identifier)
                for board_id in boards_to_delete:
                    deleted_board = self.boards_by_id.get(board_id)
                    if deleted_board is None:
                        continue
                    for tp in (
                        deleted_board.optional_white_tournament_player,
                        deleted_board.black_tournament_player,
                    ):
                        if tp is not None:
                            tp.delete_pairing(round_, database)
                            tp.reset_board()
                    database.delete_stored_board(board_id)
                    del self.boards_by_id[board_id]
                pab_stb.team_b_id = team_id
                pab_stb.bye_type = None
                database.update_stored_team_board(pab_stb)
                stored_boards = engine._team_match_stored_boards(self, pab_stb)
            else:
                # Reuse the first free table number — like individual manual
                # pairing, a hole left by an unpaired match is filled rather
                # than always appending at the end (hidden byes hold NULL).
                used_indexes = {
                    stb.index for stb in round_list if stb.index is not None
                }
                next_index = 0
                while next_index in used_indexes:
                    next_index += 1
                new_stb = StoredTeamBoard(
                    id=None,
                    tournament_id=self.id,
                    round_=round_,
                    team_a_id=team_id,
                    team_b_id=None,
                    index=next_index,
                    bye_type=None,
                )
                new_stb.id = database.add_stored_team_board(new_stb)
                round_list.append(new_stb)
                stored_boards = engine._team_match_stored_boards(self, new_stb)
        self.clear_team_cache()
        self.create_boards(stored_boards, round_, Result.PAIRING_ALLOCATED_BYE)
        target_id = pab_stb.id if completing_pair else new_stb.id  # type: ignore[union-attr]
        assert target_id is not None
        return self.team_boards_by_id[target_id]

    def unpair_team_board(self, team_board: TeamBoard) -> None:
        """Unpair a single team match. Deletes the team_board envelope
        and every individual board under it, but leaves the rest of
        the round (other team_boards, manual byes) intact."""
        round_ = team_board.round
        stb_id = team_board.stored_team_board.id
        assert stb_id is not None
        boards_to_delete = [
            board
            for board in self.boards_by_id.values()
            if board.stored_board.team_board_id == stb_id
        ]
        with EventDatabase(self.event.uniq_id, write=True) as database:
            for board in boards_to_delete:
                white_tp = board.optional_white_tournament_player
                if white_tp is not None:
                    white_tp.delete_pairing(round_, database)
                    white_tp.reset_board()
                if board.black_tournament_player:
                    board.black_tournament_player.delete_pairing(round_, database)
                    board.black_tournament_player.reset_board()
                database.delete_stored_board(board.identifier)
                if board.identifier in self.boards_by_id:
                    del self.boards_by_id[board.identifier]
            database.delete_stored_team_board(stb_id)
            for team_id in (
                team_board.stored_team_board.team_a_id,
                team_board.stored_team_board.team_b_id,
            ):
                if team_id is not None:
                    self.set_manual_point_adjustment(
                        team_id, round_, 0.0, 0.0, None, database
                    )
            round_list = self.stored_tournament.stored_team_boards_by_round.get(
                round_, []
            )
            self.stored_tournament.stored_team_boards_by_round[round_] = [
                stb for stb in round_list if stb.id != stb_id
            ]
        self.clear_team_cache()

    def unpair_boards(self, boards: list[Board]):
        rounds: set[int] = set()
        with EventDatabase(self.event.uniq_id, True) as database:
            for board in boards:
                rounds.add(board.round)
                white_tp = board.optional_white_tournament_player
                if white_tp is not None:
                    white_tp.delete_pairing(board.round, database)
                    white_tp.reset_board()
                    self.set_manual_player_point_adjustment(
                        white_tp.id, board.round, 0.0, None, database
                    )
                if board.black_tournament_player:
                    board.black_tournament_player.delete_pairing(board.round, database)
                    board.black_tournament_player.reset_board()
                    self.set_manual_player_point_adjustment(
                        board.black_tournament_player.id,
                        board.round,
                        0.0,
                        None,
                        database,
                    )
                database.delete_stored_board(board.identifier)
                if board.identifier in self.boards_by_id:
                    del self.boards_by_id[board.identifier]
            for round_ in rounds:
                if pab_board := self.get_round_pab_board(round_):
                    pab_board.index = self.get_pab_board_index(round_)
                    database.update_stored_board(pab_board.stored_board)
            if self.event.is_team_event:
                manual_bye_types = TeamByeType.manual_bye_types()
                for round_ in rounds:
                    round_list = self.stored_tournament.stored_team_boards_by_round.get(
                        round_, []
                    )
                    kept: list[StoredTeamBoard] = []
                    for stb in round_list:
                        is_manual_bye = (
                            stb.team_b_id is None and stb.bye_type in manual_bye_types
                        )
                        if is_manual_bye:
                            kept.append(stb)
                        elif stb.id is not None:
                            database.delete_stored_team_board(stb.id)
                            # The match is gone, so its manual bonus /
                            # penalty goes with it.
                            for team_id in (stb.team_a_id, stb.team_b_id):
                                if team_id is not None:
                                    self.set_manual_point_adjustment(
                                        team_id, round_, 0.0, 0.0, None, database
                                    )
                    if kept:
                        self.stored_tournament.stored_team_boards_by_round[round_] = (
                            kept
                        )
                    else:
                        self.stored_tournament.stored_team_boards_by_round.pop(
                            round_, None
                        )
        if self.event.is_team_event:
            self.clear_team_cache()

    def create_boards(
        self, stored_boards: list[StoredBoard], round_: int, pab_result: Result
    ):
        with EventDatabase(self.event.uniq_id, True) as database:
            if pab_board := self.get_round_pab_board(round_):
                pab_board.index = self.get_pab_board_index(
                    round_, [board.index for board in stored_boards]
                )
                database.update_stored_board(pab_board.stored_board)
            for stored_board in stored_boards:
                board = Board(self, round_, stored_board)
                if stored_board.fixed_number is None:
                    # Freeze the fixed table number now so a later edit to a
                    # player's fixed table can't renumber this round.
                    set_stored_fields(
                        stored_board, fixed_number=board.live_fixed_number or 0
                    )
                id_ = database.add_stored_board(stored_board)
                set_stored_fields(stored_board, id=id_)
                self.boards_by_id[id_] = board
                white_pairing = board.optional_white_pairing
                black_pairing = board.optional_black_pairing
                # Reset every pairing this loop touches so any stale
                # result from a prior round-pairing (e.g. ZPB on a
                # player who was absent before being paired in) doesn't
                # leak through. The hole / PAB branches below override
                # this explicitly.
                for p in (white_pairing, black_pairing):
                    if p is None:
                        continue
                    p.stored_pairing.board_id = id_
                    p.stored_pairing.result = Result.NO_RESULT.value
                    p.stored_pairing.effective_points = None
                    p.stored_pairing.illegal_moves = 0
                present_pairing = white_pairing or black_pairing
                if present_pairing is not None and not (
                    white_pairing is not None and black_pairing is not None
                ):
                    parent_team_board_id = stored_board.team_board_id
                    parent_team_board = (
                        self.team_boards_by_id.get(parent_team_board_id)
                        if parent_team_board_id is not None
                        else None
                    )
                    if (
                        parent_team_board is not None
                        and parent_team_board.stored_team_board.team_b_id is not None
                    ):
                        # Real team match, hole on the opposing side ⇒
                        # forfeit win for the present player.
                        present_pairing.stored_pairing.result = Result.FORFEIT_WIN.value
                    else:
                        # PAB envelope (or individual-mode bye) ⇒ PAB.
                        present_pairing.stored_pairing.result = pab_result.value
                if white_pairing is not None:
                    white_pairing.update(database)
                if black_pairing is not None:
                    black_pairing.update(database)

    def toggle_check_in_open(self):
        check_in_open = not self.check_in_open
        with EventDatabase(self.event.uniq_id, True) as database:
            database.set_tournament_check_in_open(self.id, check_in_open)
        self.stored_tournament.check_in_open = check_in_open

    def set_player_participation(
        self, player: TournamentPlayer, withdraw: bool = False
    ):
        # If there aren't any pairings, then the round for the bye is the first round
        round_for_participation = self.current_round or 1
        if not withdraw and self.round_has_pairings(round_for_participation):
            # If returning to tournament and pairings for this round, then start setting removing ZPBs from the next round only
            round_for_participation += 1
        result = Result.ZERO_POINT_BYE if withdraw else Result.NO_RESULT
        new_byes = {
            round_: result
            for round_ in range(
                round_for_participation,
                self.rounds + 1,
            )
            if player.pairings[round_].unpaired
        }
        self.set_player_byes(player, new_byes)
        self.check_in_player(player, not withdraw)
        player.__dict__.pop('has_withdrawn', None)
        player.__dict__.pop('check_in_status', None)

    def set_player_byes(self, player: TournamentPlayer, byes: dict[int, Result]):
        """Updates a player's pairings with ZPB, HPB, FPB or not-paired values."""
        with EventDatabase(self.event.uniq_id, write=True) as database:
            for round_, result in byes.items():
                pairing = player.pairings_by_round[round_]
                if pairing.unpaired:
                    pairing.update_result(database, result)

    def set_current_round(self, round_: int):
        with EventDatabase(self.event.uniq_id, True) as database:
            database.set_tournament_current_round(self.id, round_)
