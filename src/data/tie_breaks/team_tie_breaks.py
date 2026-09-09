"""Team tie-break systems (FIDE Play-Off and Tie-Break Regulations,
effective 1 March 2026).

Implements every tie-break the regulations define for teams:
  - Match Points or Game Points (MPvGP, Art. 13.1)
  - Extended Sonneborn-Berger for teams (ESB, Art. 13.2) with the four
    Own × Opponent score-type combinations: EMMSB, EMGSB, EGMSB, EGGSB
  - Extended Direct Encounter for teams (EDE, Art. 13.3)
  - Scores and Schedule Strength Combination (SSSC, Art. 13.4)
  - the knock-out tie-breaks Board Count (BC, Art. 12.1), Top Board
    Results (TBR, Art. 12.2) and Bottom Board Elimination (BBE, Art.
    12.3), which Art. 13.3.2 also composes after EDE

Each tie-break consumes ``TeamRecord`` instances (see
``team_records.py``); this lets us unit-test the systems against the
TEC-2023 published exercises by building records directly from the
crosstable rather than through the storage layer.
"""

from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from types import UnionType
from typing import Any, Callable, SupportsFloat

from common.i18n import _
from data.pairings import PairingSystem
from data.player import TournamentPlayer
from data.tie_breaks.categories import (
    TeamScoreCategory,
    TeamOpponentRecordCategory,
    TieBreakCategory,
)
from data.tie_breaks.cutters import TieBreakCutter
from data.tie_breaks.options import (
    CutterTieBreakOption,
    LegacyMarch2026TieBreakOption,
    TieBreakOption,
    ForeModifierTieBreakOption,
    NormalizationFactorOverrideTieBreakOption,
    PlayedModifierTieBreakOption,
    TeamScoreTieBreakOption,
)
from data.tie_breaks.team_records import (
    TeamMatchRecord,
    TeamRecord,
    adjust_opponent_total,
    dummy_opponent_score,
)
from data.tie_breaks.tie_breaks import (
    ForeBuchholzTieBreak,
    StandardBuchholzTieBreak,
    TieBreak,
)
from utils.enum import ScoreType


# ---------------------------------------------------------------------------
# ESB variant option (which score-type combination to use)
# ---------------------------------------------------------------------------


class ESBVariant(StrEnum):
    """The four ESB variants (TEC-2023 §10)."""

    EMMSB = 'EMMSB'  # Σ opponent_MP × own_MP_obtained
    EMGSB = 'EMGSB'  # Σ opponent_MP × own_GP_obtained
    EGMSB = 'EGMSB'  # Σ opponent_GP × own_MP_obtained
    EGGSB = 'EGGSB'  # Σ opponent_GP × own_GP_obtained

    @property
    def opponent_score_type(self) -> ScoreType:
        return (
            ScoreType.MATCH_POINTS
            if self in (ESBVariant.EMMSB, ESBVariant.EMGSB)
            else ScoreType.GAME_POINTS
        )

    @property
    def own_score_type(self) -> ScoreType:
        return (
            ScoreType.MATCH_POINTS
            if self in (ESBVariant.EMMSB, ESBVariant.EGMSB)
            else ScoreType.GAME_POINTS
        )


class ESBVariantTieBreakOption(TieBreakOption):
    """Selects which of the four ESB combinations is computed."""

    @staticmethod
    def static_id() -> str:
        return 'ESB_VARIANT'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return ESBVariant.EMMSB.value

    @property
    def template_file_stem(self) -> str:
        return 'esb_variant'

    @property
    def is_variation(self) -> bool:
        return self.value != ESBVariant.EMMSB.value

    @property
    def variation_acronym(self) -> str:
        # Use the variant code as the trf-acronym suffix.
        return self.value

    def set_value_from_variation_acronym(self, acronym: str) -> bool:
        if acronym not in {v.value for v in ESBVariant}:
            return False
        self.value = acronym
        return True

    @property
    def variant(self) -> ESBVariant:
        return ESBVariant(self.value)

    @property
    def variation_name(self) -> str:
        return self.variant.value

    @property
    def variant_options(self) -> 'dict[str, Any]':
        """Select-input dict consumed by the ``esb_variant.html`` option
        template: ESBVariant.value → SelectOption(label, tooltip)."""
        from web.utils import SelectOption

        labels = {
            ESBVariant.EMMSB: _('Opponent match points × match points obtained'),
            ESBVariant.EMGSB: _('Opponent match points × game points obtained'),
            ESBVariant.EGMSB: _('Opponent game points × match points obtained'),
            ESBVariant.EGGSB: _('Opponent game points × game points obtained'),
        }
        return {
            variant.value: SelectOption(
                name=f'{variant.value} — {labels[variant]}',
                tooltip=labels[variant],
            )
            for variant in ESBVariant
        }


# ---------------------------------------------------------------------------
# Cut-1 only for ESB (no median)
# ---------------------------------------------------------------------------


class ESBCutterTieBreakOption(CutterTieBreakOption):
    """ESB-specific cutter: Cut-1 / Cut-2 allowed, no Median (the rules
    explicitly exclude Median modifiers for ESB-type tie-breaks because
    Median would discard the heaviest opponents, contradicting the
    tie-break's design — Art. 14)."""

    @staticmethod
    def static_id() -> str:
        return 'ESB_CUTTER'


# ---------------------------------------------------------------------------
# TeamTieBreak base class
# ---------------------------------------------------------------------------


class TeamTieBreak(TieBreak, ABC):
    """Team-level tie-breaks (FIDE Play-Off and Tie-Break Regulations,
    Art. 12 and Art. 13).

    Concrete subclass of :class:`TieBreak` so storage, configuration
    and plugin discovery are unified. The individual-side
    :meth:`compute_player_value` is stubbed to zero — team tie-breaks
    are dispatched through :meth:`compute_team_value` /
    :meth:`compute_all_team_values`, and callers that expect a numeric
    per-player value should filter by :attr:`is_team_tiebreak` first.
    """

    @property
    def is_team_tiebreak(self) -> bool:
        return True

    @property
    def supports_team_mode(self) -> bool:
        return True

    @property
    def is_used_for_team_ranking(self) -> bool:
        """Team-score tie-breaks are not "applied per player and
        summed" the way Buchholz can be — they own the team ranking
        directly. So they don't participate in the legacy per-player
        team-ranking aggregation path."""
        return False

    def compute_player_value(
        self, player: TournamentPlayer, *, after_round: int
    ) -> SupportsFloat:
        return 0.0

    @abstractmethod
    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: 'TeamTieBreakContext',
        *,
        after_round: int,
    ) -> SupportsFloat:
        """Compute the tie-break value for one team. ``all_records`` is
        keyed by team_id and contains every team that participated."""

    @property
    def _legacy_march_2026(self) -> bool:
        """True when the tie-break opts out of the March 2026 rules —
        used here for the Art. 16.4 dummy-opponent caps, which earlier
        editions did not have."""
        with suppress(KeyError):
            return bool(self._get_option(LegacyMarch2026TieBreakOption).value)
        return False

    @property
    def is_computed_per_team(self) -> bool:
        """True if the tie-break is a scalar function of a single team.
        False for group-level tie-breaks (e.g. EDE) which inspect every
        tied team at once to produce a relative ranking."""
        return True

    def compute_all_team_values(
        self,
        tied_groups: list[list[TeamRecord]],
        all_records: dict[int, TeamRecord],
        tournament_context: 'TeamTieBreakContext',
        *,
        after_round: int,
    ) -> dict[int, float]:
        """Compute values for every tied team. Default implementation
        delegates to :meth:`compute_team_value` per team; group-level
        tie-breaks (EDE) override this to perform relative ranking."""
        result: dict[int, float] = {}
        for group in tied_groups:
            for team in group:
                value = self.compute_team_value(
                    team,
                    all_records,
                    tournament_context,
                    after_round=after_round,
                )
                result[team.team_id] = float(value)
        return result


# ---------------------------------------------------------------------------
# Tournament context (primary/secondary score type + match-point scale)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamTieBreakContext:
    """Tournament-level constants the tie-breaks need.

    Decoupling these from ``Tournament`` keeps the tie-breaks unit-
    testable: a test can build a context directly and feed records
    that mirror a published exercise without spinning up a database."""

    primary_score: ScoreType
    secondary_score: ScoreType
    rounds: int
    win_mp: float
    draw_mp: float
    loss_mp: float
    # Number of players fielded per team per match — sets the upper
    # bound on game points per match (1 GP per board with 1-½-0).
    team_player_count: int
    # The GP awarded to a team for a half-match draw against a virtual
    # opponent (Art. 16.3.2 dummy opponent). For 4-player teams under
    # standard 2-1-0 / 1-½-0 scoring, this is 4 × ½ = 2 GP.
    draw_gp: float
    # True for round-robin and fixed-table systems, where every opponent
    # is known before the start. Art. 15.2 then counts forfeits as
    # regular matches for the opponent-based tie-breaks, rather than
    # substituting the dummy opponent of Art. 16.
    predetermined_pairings: bool = False
    # Teams dropped from the final standings (FIDE 6.6 round-robin rule):
    # their matches don't count towards any other team's tie-breaks.
    excluded_team_ids: frozenset[int] = frozenset()

    def match_counts_for_tie_breaks(self, match: 'TeamMatchRecord') -> bool:
        """False when *match* is against a team excluded from the final
        standings — that match must not feed the opponent's tie-breaks."""
        return match.opponent_id not in self.excluded_team_ids

    @property
    def max_score_per_match(self) -> dict[ScoreType, float]:
        return {
            ScoreType.MATCH_POINTS: self.win_mp,
            ScoreType.GAME_POINTS: float(self.team_player_count),
        }

    @property
    def min_score_per_match(self) -> dict[ScoreType, float]:
        return {
            ScoreType.MATCH_POINTS: self.loss_mp,
            ScoreType.GAME_POINTS: 0.0,
        }


# ---------------------------------------------------------------------------
# Adjusted-score helpers (Art. 16 dummy-opponent + ZPB-not-followed-by-play)
# ---------------------------------------------------------------------------


def _adjust_opponent_total(
    opponent: TeamRecord,
    score_type: ScoreType,
    context: TeamTieBreakContext,
    *,
    after_round: int,
) -> float:
    return adjust_opponent_total(
        opponent,
        score_type,
        after_round=after_round,
        draw_mp=context.draw_mp,
        draw_gp=context.draw_gp,
    )


def _dummy_opponent_score(
    own_record: TeamRecord,
    score_type: ScoreType,
    context: TeamTieBreakContext,
    *,
    after_round: int,
    opponent_adjusted: float | None = None,
    legacy: bool = False,
) -> float:
    return dummy_opponent_score(
        own_record,
        score_type,
        after_round=after_round,
        rounds=context.rounds,
        draw_value=(
            context.draw_mp if score_type == ScoreType.MATCH_POINTS else context.draw_gp
        ),
        opponent_adjusted=opponent_adjusted,
        legacy=legacy,
    )


# ---------------------------------------------------------------------------
# MPvGP
# ---------------------------------------------------------------------------


class MatchPointsVsGamePointsTieBreak(TeamTieBreak):
    """The secondary score (the one not used as primary). Art. 13.1."""

    @staticmethod
    def static_id() -> str:
        return 'TEAM_MPVGP'

    @staticmethod
    def static_name() -> str:
        return _('Match points vs game points')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return []

    @property
    def base_acronym(self) -> str:
        return 'MPvGP'

    @property
    def base_help_text(self) -> str:
        return _(
            'The team score that is not used as the primary score '
            '(match points if the primary is game points and vice versa).'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def is_compatible_with(self, pairing_system: PairingSystem) -> bool:
        # "The score that is not used as primary" needs the system to
        # expose both score types; on systems with only game points
        # there's nothing to return.
        if not pairing_system.supports_match_points:
            return False
        return super().is_compatible_with(pairing_system)

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        return team_record.total(tournament_context.secondary_score)


# ---------------------------------------------------------------------------
# Extended Sonneborn-Berger for teams (4 variants)
# ---------------------------------------------------------------------------


class ExtendedSonnebornBergerTeamTieBreak(TeamTieBreak):
    """ESB for teams. For each round, multiply the opponent's total
    (per ``ESBVariant.opponent_score_type``) by the team's own score
    in that match (per ``ESBVariant.own_score_type``). Sum, with
    optional Cut-1 / Cut-2.

    Forfeit losses and ZPB contribute zero by construction (own_score
    is zero); HPB contributes a non-zero amount (own_score equals draw
    points) — that contribution is treated as VUR for the cut rule.
    """

    @staticmethod
    def static_id() -> str:
        return 'TEAM_EXTENDED_SB'

    @staticmethod
    def static_name() -> str:
        return _('Extended Sonneborn-Berger')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return [
            ESBVariantTieBreakOption,
            ESBCutterTieBreakOption,
            LegacyMarch2026TieBreakOption,
        ]

    @cached_property
    def variant(self) -> ESBVariant:
        return self._get_option(ESBVariantTieBreakOption).variant

    @cached_property
    def cutter(self) -> TieBreakCutter:
        return self._get_option(ESBCutterTieBreakOption).cutter

    def is_compatible_with(self, pairing_system: PairingSystem) -> bool:
        # Variants whose enum names a match-point side need the
        # pairing system to expose match points.
        uses_mp = ScoreType.MATCH_POINTS in (
            self.variant.opponent_score_type,
            self.variant.own_score_type,
        )
        if uses_mp and not pairing_system.supports_match_points:
            return False
        return super().is_compatible_with(pairing_system)

    @property
    def base_acronym(self) -> str:
        return self.variant.value

    @property
    def acronym(self) -> str:
        # The variant option is already encoded in ``base_acronym``
        # (e.g. ``EMGSB``) — don't repeat it. Append only the cutter.
        parts: list[str] = [self.base_acronym]
        cutter_option = self._get_option(ESBCutterTieBreakOption)
        if cutter_option.is_variation and cutter_option.variation_acronym:
            parts.append(cutter_option.variation_acronym)
        return '/'.join(parts)

    @property
    def picker_acronym(self) -> str:
        # The four FIDE variants (EMMSB/EMGSB/EGMSB/EGGSB) are all
        # ESB — the variant is a configurable option, so the picker
        # names the family.
        return 'ESB'

    @property
    def picker_help_text(self) -> str:
        # ``base_help_text`` describes the configured variant — for
        # the family picker we want a variant-agnostic summary.
        return _(
            'For each round, sum the opponent score multiplied by the '
            'team score obtained in that match across all rounds. '
            'The four variants (EMMSB / EMGSB / EGMSB / EGGSB) choose '
            'which score type — match points or game points — is used '
            'on each side; pick one in the variant option below '
            '(FIDE tie-break regulations, Art. 13.2).'
        )

    @property
    def base_help_text(self) -> str:
        return _(
            'For each round, the opponent total {opp} multiplied by '
            'the team {own} obtained in that match, summed across all '
            'rounds (FIDE tie-break regulations, Art. 13.2).'
        ).format(
            opp=_(self.variant.opponent_score_type.value),
            own=_(self.variant.own_score_type.value),
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamOpponentRecordCategory()

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        opp_score_type = self.variant.opponent_score_type
        own_score_type = self.variant.own_score_type
        cut = self.cutter.bottom_cut
        if cut >= after_round:
            return 0.0

        @dataclass(frozen=True, order=True)
        class _Contribution:
            opp_total: float
            value: float

        general: list[_Contribution] = []
        vur: list[_Contribution] = []
        # Art. 15.2: with pre-determined pairings a forfeit is a regular
        # match, so the real opponent's total counts. Byes cannot occur
        # in such a system, so every unplayed match here is a forfeit.
        forfeits_are_played = tournament_context.predetermined_pairings
        for match in team_record.matches:
            if match.round_ > after_round:
                continue
            if not tournament_context.match_counts_for_tie_breaks(match):
                continue
            if match.unplayed and not (
                forfeits_are_played and match.opponent_id is not None
            ):
                # Art. 16.4.1: a forfeit caps the dummy at the scheduled
                # opponent's adjusted score; a bye caps at draw points ×
                # rounds (16.4.2).
                opponent_adjusted = None
                if not match.is_bye and match.opponent_id is not None:
                    opponent_adjusted = _adjust_opponent_total(
                        all_records[match.opponent_id],
                        opp_score_type,
                        tournament_context,
                        after_round=after_round,
                    )
                opp_total = _dummy_opponent_score(
                    team_record,
                    opp_score_type,
                    tournament_context,
                    after_round=after_round,
                    opponent_adjusted=opponent_adjusted,
                    legacy=self._legacy_march_2026,
                )
            else:
                assert match.opponent_id is not None
                opponent = all_records[match.opponent_id]
                opp_total = _adjust_opponent_total(
                    opponent,
                    opp_score_type,
                    tournament_context,
                    after_round=after_round,
                )
            own = team_record.own_against(match, own_score_type)
            contribution = _Contribution(opp_total=opp_total, value=opp_total * own)
            if match.voluntary_unplayed:
                vur.append(contribution)
            else:
                general.append(contribution)

        vur.sort()
        general.sort()
        # VUR cut rule (matches the individual SB implementation):
        # the natural least-significant value is the contribution with
        # the lowest opp_total (tie-break: lowest contribution). A VUR
        # contribution is dropped first only when (a) its opp_total is
        # already at or below the general LSV opp_total — natural cut —
        # or (b) its contribution value is at least the general LSV
        # contribution, in which case Art. 16.5 forces the cut to deny
        # the competitor any benefit from the voluntary absence.
        for _step in range(cut):
            if not vur:
                with suppress(IndexError):
                    general.pop(0)
            elif not general:
                with suppress(IndexError):
                    vur.pop(0)
            else:
                v = vur[0]
                g = general[0]
                if v.opp_total <= g.opp_total:
                    vur.pop(0)
                elif v.value >= g.value:
                    vur.pop(0)
                else:
                    general.pop(0)
        return sum(c.value for c in vur) + sum(c.value for c in general)


# ---------------------------------------------------------------------------
# Scores and Schedule Strength Combination (SSSC, Art. 13.4)
# ---------------------------------------------------------------------------


class ScoresAndScheduleStrengthCombinationTieBreak(TeamTieBreak):
    """secondary_score + (Buchholz on the primary) / normalisation_factor.

    The normalisation factor F_N rescales the Buchholz term so it lives
    on the same order of magnitude as the secondary score, preserving
    the intent that schedule strength should refine, not overwhelm,
    the raw scores. It equals floor(max_primary_total / max_secondary_per_round).
    """

    @staticmethod
    def static_id() -> str:
        return 'TEAM_SSSC'

    @staticmethod
    def static_name() -> str:
        return _('Scores + Schedule Strength (SSSC)')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return [
            PlayedModifierTieBreakOption,
            ForeModifierTieBreakOption,
            NormalizationFactorOverrideTieBreakOption,
            LegacyMarch2026TieBreakOption,
        ]

    @property
    def base_acronym(self) -> str:
        return 'SSSC'

    @property
    def base_help_text(self) -> str:
        return _(
            'Secondary score plus the team Buchholz on the primary '
            'score divided by a normalisation factor (FIDE Handbook '
            'Art. 13.4).'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamOpponentRecordCategory()

    @staticmethod
    def normalization_factor(context: TeamTieBreakContext) -> int:
        max_primary_round = context.max_score_per_match[context.primary_score]
        max_secondary_round = context.max_score_per_match[context.secondary_score]
        max_primary_total = context.rounds * max_primary_round
        if max_secondary_round <= 0:
            return 1
        return int(max_primary_total // max_secondary_round)

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        secondary = team_record.total(tournament_context.secondary_score)
        team_score_value = (
            TeamScoreTieBreakOption.VALUE_GP
            if tournament_context.primary_score == ScoreType.GAME_POINTS
            else TeamScoreTieBreakOption.VALUE_MP
        )
        sub_options: list[TieBreakOption] = [TeamScoreTieBreakOption(team_score_value)]
        try:
            played = self._get_option(PlayedModifierTieBreakOption)
            if played.value:
                sub_options.append(played)
        except KeyError:
            pass
        with suppress(KeyError):
            legacy = self._get_option(LegacyMarch2026TieBreakOption)
            if legacy.value:
                sub_options.append(legacy)
        fore = False
        try:
            fore_opt = self._get_option(ForeModifierTieBreakOption)
            fore = bool(fore_opt.value)
        except KeyError:
            pass
        bh_cls: type[TieBreak] = (
            ForeBuchholzTieBreak if fore else StandardBuchholzTieBreak
        )
        bh = float(
            bh_cls(sub_options).compute_team_value(
                team_record,
                all_records,
                tournament_context,
                after_round=after_round,
            )
        )
        # /Kx override: use the explicit factor when set, else compute.
        override = 0
        try:
            override = int(
                self._get_option(NormalizationFactorOverrideTieBreakOption).value
            )
        except KeyError:
            pass
        factor = override if override else self.normalization_factor(tournament_context)
        return secondary + bh / factor


# ---------------------------------------------------------------------------
# Extended Direct Encounter (EDE, Art. 13.3)
# ---------------------------------------------------------------------------


class EDEKnockoutVariant(StrEnum):
    """What Art. 13.3.2 lets a competition add to EDE for the case where
    "exactly two teams are still tied in both MP and GP": one or two of
    the knock-out tie-breaks of Art. 12, in order. The regulations name
    four combinations; ``NONE`` leaves the teams tied."""

    NONE = ''
    EDEBT = 'BT'  # + Board Count, then Top Board Results
    EDEBB = 'BB'  # + Board Count, then Bottom Board Elimination
    EDET = 'T'  # + Top Board Results
    EDEB = 'B'  # + Bottom Board Elimination

    @property
    def acronym(self) -> str:
        return f'EDE{self.value}'


class EDEKnockoutTieBreakOption(TieBreakOption):
    """Selects the Art. 13.3.2 combination applied to the last two tied
    teams."""

    @staticmethod
    def static_id() -> str:
        return 'EDE_KNOCKOUT'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return EDEKnockoutVariant.NONE.value

    @property
    def template_file_stem(self) -> str:
        return 'ede_knockout'

    @property
    def is_variation(self) -> bool:
        return self.value != EDEKnockoutVariant.NONE.value

    @property
    def variant(self) -> EDEKnockoutVariant:
        return EDEKnockoutVariant(self.value or '')

    @property
    def variation_acronym(self) -> str:
        return self.value

    def set_value_from_variation_acronym(self, acronym: str) -> bool:
        if not acronym.startswith('EDE'):
            return False
        suffix = acronym[3:]
        if suffix not in {v.value for v in EDEKnockoutVariant}:
            return False
        self.value = suffix
        return True

    @property
    def variation_name(self) -> str:
        return self.variant.acronym

    @property
    def variant_options(self) -> 'dict[str, Any]':
        """Select-input dict consumed by ``ede_knockout.html``."""
        from web.utils import SelectOption

        labels = {
            EDEKnockoutVariant.NONE: _('Nothing further — leave the teams tied'),
            EDEKnockoutVariant.EDEBT: _('Board count, then top board results'),
            EDEKnockoutVariant.EDEBB: _('Board count, then bottom board elimination'),
            EDEKnockoutVariant.EDET: _('Top board results'),
            EDEKnockoutVariant.EDEB: _('Bottom board elimination'),
        }
        return {
            variant.value: SelectOption(
                name=(
                    labels[variant]
                    if variant is EDEKnockoutVariant.NONE
                    else f'{variant.acronym} — {labels[variant]}'
                ),
                tooltip=labels[variant],
            )
            for variant in EDEKnockoutVariant
        }


class ExtendedDirectEncounterTieBreak(TeamTieBreak):
    """Direct-encounter ranking with primary→secondary fallback and
    recursive subgroup resolution.

    Process (Art. 13.3, applying Art. 6):
      1. Build a separate crosstable using only matches between the
         tied teams (in Swiss, only played matches; forfeits ignored).
      2. Compute each team's sub-score using the primary score type.
      3. Split into subgroups using min/max possible sub-scores (when
         a sub-match wasn't played, min = loss value, max = win value
         per the score type).
      4. If no split is possible, retry the whole step with the
         secondary score. Still no split → leave the group tied.
      5. Recurse into every subgroup of size ≥ 2 with the score type
         that produced the split. Art. 13.3.3 says to "restart with the
         new subset from 13.3.1", which on its own reads as going back
         to the primary score; endnote [6] of the TEC-2023 exercises
         settles it the other way — a subgroup stays on the score in
         use "because we are still within the same application of the
         tie-break". Exercise 45 turns on exactly this.

    The result for each team is a within-group rank delta (0 = worst
    of the group, larger = better), so the surrounding standings
    machinery can break the parent tie by sorting on the delta.
    """

    is_aggregatable = False

    @staticmethod
    def static_id() -> str:
        return 'TEAM_EDE'

    @staticmethod
    def static_name() -> str:
        return _('Extended Direct Encounter')

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        return [EDEKnockoutTieBreakOption, PlayedModifierTieBreakOption]

    @property
    def knockout_variant(self) -> EDEKnockoutVariant:
        with suppress(KeyError):
            return self._get_option(EDEKnockoutTieBreakOption).variant
        return EDEKnockoutVariant.NONE

    @property
    def base_acronym(self) -> str:
        return self.knockout_variant.acronym

    @property
    def acronym(self) -> str:
        # The knockout variant is already encoded in ``base_acronym``
        # (e.g. ``EDEBB``) — don't repeat it. Append only the played
        # modifier. Repeating it would also make the acronym unreadable
        # on the way back in: ``tie_break_from_trf_acronym`` resolves the
        # variant from the part before the slash, then fails on a ``BB``
        # suffix no option accepts.
        parts: list[str] = [self.base_acronym]
        played_option = self._get_option(PlayedModifierTieBreakOption)
        if played_option.is_variation and played_option.variation_acronym:
            parts.append(played_option.variation_acronym)
        return '/'.join(parts)

    @property
    def picker_acronym(self) -> str:
        # The knockout combinations (EDEBT / EDEBB / EDET / EDEB) are all
        # EDE — the combination is a configurable option, so the picker
        # names the family.
        return 'EDE'

    @property
    def base_help_text(self) -> str:
        return _(
            'Direct-encounter ranking for tied teams using a separate '
            'crosstable, with secondary-score fallback and recursive '
            'sub-group resolution.'
        )

    @property
    def category(self) -> TieBreakCategory:
        return TeamOpponentRecordCategory()

    @property
    def is_computed_per_team(self) -> bool:
        return False

    @property
    def display_rank_delta(self) -> bool:
        return True

    @property
    def allow_multiple(self) -> bool:
        return True

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        return 0.0

    def compute_all_team_values(
        self,
        tied_groups: list[list[TeamRecord]],
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> dict[int, float]:
        values: dict[int, float] = {}
        for group in tied_groups:
            self._resolve(
                group,
                0,
                values,
                tournament_context,
                after_round,
                tournament_context.primary_score,
            )
        return values

    def _resolve(
        self,
        group: list[TeamRecord],
        min_value: int,
        values: dict[int, float],
        context: TeamTieBreakContext,
        after_round: int,
        score_type: ScoreType,
    ) -> None:
        if len(group) == 1:
            values[group[0].team_id] = float(min_value)
            return
        min_max = {
            t.team_id: self._team_min_max(t, group, score_type, context, after_round)
            for t in group
        }
        subgroups = self._split(min_max, group)
        if len(subgroups) > 1:
            for sub in subgroups:
                # A subgroup stays on the score that split its parent:
                # it is "still within the same application of the
                # tie-break" (TEC-2023 exercises, endnote [6]), not a
                # fresh one starting from the primary. Restarting on the
                # primary swaps teams 1 and 2 of exercise 45 against the
                # published answer.
                self._resolve(sub, min_value, values, context, after_round, score_type)
                min_value += len(sub)
            return
        # Split failed — fall back to secondary if we were on primary,
        # otherwise try the Art. 13.3.2 knock-out tie-breaks and, that
        # failing, leave the entire group tied at the current rank.
        if score_type == context.primary_score:
            self._resolve(
                group,
                min_value,
                values,
                context,
                after_round,
                context.secondary_score,
            )
            return
        ordered = self._knockout_order(group, context, after_round)
        if ordered is not None:
            for rank, team in enumerate(reversed(ordered)):
                values[team.team_id] = float(min_value + rank)
            return
        for team in group:
            values[team.team_id] = float(min_value)

    def _knockout_order(
        self,
        group: list[TeamRecord],
        context: TeamTieBreakContext,
        after_round: int,
    ) -> list[TeamRecord] | None:
        """Order the group best-first with the Art. 12 tie-breaks the
        competition chose, or ``None`` when they don't apply or leave
        the teams level.

        Art. 13.3.2 offers these only "if exactly two teams are still
        tied in both MP and GP", and the published exercises 46-48 read
        the boards of those teams' own encounter rather than of their
        whole tournament — the knock-out tie-break judges the little
        tournament EDE has just built.
        """
        variant = self.knockout_variant
        if variant is EDEKnockoutVariant.NONE or len(group) != 2:
            return None
        keys: dict[str, Callable[[list[float]], tuple[float, ...]]] = {
            'B': lambda board_scores: (board_count_key(board_scores),),
            'T': top_board_key,
            'E': bottom_board_key,
        }
        # 'BT' → board count, then top boards; 'BB' → board count, then
        # bottom-board elimination; 'T' / 'B' → that one alone.
        steps = {
            EDEKnockoutVariant.EDEBT: ('B', 'T'),
            EDEKnockoutVariant.EDEBB: ('B', 'E'),
            EDEKnockoutVariant.EDET: ('T',),
            EDEKnockoutVariant.EDEB: ('E',),
        }[variant]
        include_forfeits = context.predetermined_pairings
        with suppress(KeyError):
            include_forfeits = include_forfeits or bool(
                self._get_option(PlayedModifierTieBreakOption).value
            )
        totals = {
            team.team_id: board_totals(
                team,
                context.team_player_count,
                after_round=after_round,
                include_forfeits=include_forfeits,
                opponent_ids={other.team_id for other in group if other is not team},
            )
            for team in group
        }
        for step in steps:
            key = keys[step]
            first, second = group
            first_key, second_key = (
                key(totals[first.team_id]),
                key(totals[second.team_id]),
            )
            if first_key != second_key:
                return [first, second] if first_key > second_key else [second, first]
        return None

    def _team_min_max(
        self,
        team: TeamRecord,
        group: list[TeamRecord],
        score_type: ScoreType,
        context: TeamTieBreakContext,
        after_round: int,
    ) -> tuple[float, float]:
        """Return (min, max) of the score this team can have in the
        sub-crosstable restricted to ``group`` opponents, averaging
        repeated meets and treating missing matches as worst/best
        case under the active score type.

        Art. 6.1.1 excludes forfeits, but only those "not covered by
        Article 15.2" — so with pre-determined pairings they count, and
        in a Swiss the ``/P`` (PlayedModifier) flag is what "unless the
        specific regulations of the tournament state otherwise" looks
        like."""
        try:
            played_modifier = bool(self._get_option(PlayedModifierTieBreakOption).value)
        except KeyError:
            played_modifier = False
        played_modifier = played_modifier or context.predetermined_pairings
        group_ids = {t.team_id for t in group if t.team_id != team.team_id}
        played_score_by_opp: dict[int, list[float]] = {}
        for match in team.matches:
            if match.round_ > after_round:
                continue
            counts = match.played or (played_modifier and match.opponent_id is not None)
            if not counts or match.opponent_id is None:
                continue
            if match.opponent_id in group_ids:
                played_score_by_opp.setdefault(match.opponent_id, []).append(
                    team.own_against(match, score_type)
                )
        accrued = 0.0
        unplayed_count = 0
        for opp_id in group_ids:
            scores = played_score_by_opp.get(opp_id)
            if scores:
                accrued += sum(scores) / len(scores)
            else:
                unplayed_count += 1
        max_per = context.max_score_per_match[score_type]
        min_per = context.min_score_per_match[score_type]
        return (
            accrued + min_per * unplayed_count,
            accrued + max_per * unplayed_count,
        )

    @staticmethod
    def _split(
        min_max_by_id: dict[int, tuple[float, float]],
        group: list[TeamRecord],
    ) -> list[list[TeamRecord]]:
        team_by_id = {t.team_id: t for t in group}
        sorted_items = sorted(min_max_by_id.items(), key=lambda kv: kv[1])
        if not sorted_items:
            return []
        first_id, (first_min, first_max) = sorted_items[0]
        cur_max = first_max
        current: list[TeamRecord] = [team_by_id[first_id]]
        subgroups: list[list[TeamRecord]] = []
        for team_id, (min_, max_) in sorted_items[1:]:
            if min_ <= cur_max:
                cur_max = max(cur_max, max_)
                current.append(team_by_id[team_id])
            else:
                subgroups.append(current)
                cur_max = max_
                current = [team_by_id[team_id]]
        subgroups.append(current)
        return subgroups


# ---------------------------------------------------------------------------
# Tie-breaks specific for team knock-outs (BC / TBR / BBE, Art. 12)
# ---------------------------------------------------------------------------


def board_totals(
    team_record: TeamRecord,
    boards: int,
    *,
    after_round: int,
    include_forfeits: bool,
    opponent_ids: set[int] | None = None,
) -> list[float]:
    """Game points the team scored on each board, board 1 first.

    ``opponent_ids`` restricts the sum to matches against those teams —
    what Art. 13.3.2 needs, since the knock-out tie-breaks it composes
    after EDE judge the tied teams' own encounters rather than their
    whole tournament (TEC-2023 exercises 46-48).
    """
    totals = [0.0] * boards
    for match in team_record.matches:
        if match.round_ > after_round:
            continue
        if opponent_ids is not None and match.opponent_id not in opponent_ids:
            continue
        if not match.played and not (
            include_forfeits and match.opponent_id is not None
        ):
            continue
        for board_index, score in enumerate(match.board_scores):
            if board_index >= boards:
                break
            totals[board_index] += score
    return totals


def board_count_key(totals: list[float]) -> float:
    """Art. 12.1, negated so that higher always ranks first."""
    return -sum((index + 1) * score for index, score in enumerate(totals))


def top_board_key(totals: list[float]) -> tuple[float, ...]:
    """Art. 12.2: board 1, then the next board down, and so on."""
    return tuple(totals)


def bottom_board_key(totals: list[float]) -> tuple[float, ...]:
    """Art. 12.3: every board but the bottom, then dropping the
    bottom-most board still counted, and so on."""
    return tuple(sum(totals[:kept]) for kept in range(len(totals) - 1, 0, -1))


class _BoardTieBreak(TeamTieBreak):
    """Shared base for the Art. 12 tie-breaks, which all rank teams on
    the game points scored *per board* over the whole tournament,
    "regardless of who was playing on it".

    Art. 12 defines them for knock-out matches, but Art. 13.3.2 also
    composes them after EDE in a Swiss or round-robin — list EDE then
    BC / TBR / BBE to build the EDEBT, EDEBB, EDET and EDEB variants
    the regulations name.
    """

    @staticmethod
    def available_options() -> list[type[TieBreakOption]]:
        # The /P flag counts a wholly forfeited match as played, as
        # Art. 15.2 already does for pre-determined pairings.
        return [PlayedModifierTieBreakOption]

    @property
    def category(self) -> TieBreakCategory:
        return TeamScoreCategory()

    def _include_forfeits(self, context: 'TeamTieBreakContext') -> bool:
        """Whether a wholly forfeited match still contributes its
        boards. True under pre-determined pairings (Art. 15.2), which
        is the setting these tie-breaks are written for — "individual
        forfeits are considered equivalent to actually played matches"
        (TEC-2023 exercises, §12). Board-level forfeits inside a played
        match always count: they are part of the match result."""
        if context.predetermined_pairings:
            return True
        with suppress(KeyError):
            return bool(self._get_option(PlayedModifierTieBreakOption).value)
        return False

    def _board_totals(
        self,
        team_record: TeamRecord,
        boards: int,
        after_round: int,
        context: 'TeamTieBreakContext',
    ) -> list[float]:
        """Game points the team scored on each board across the
        tournament, board 1 first."""
        return board_totals(
            team_record,
            boards,
            after_round=after_round,
            include_forfeits=self._include_forfeits(context),
        )

    @staticmethod
    def _pack(digits: list[float], base: int) -> float:
        """Pack a lexicographic comparison into one number, the first
        digit being the most significant — the standings machinery
        ranks on a single value. Scores are doubled so half points
        become whole ones, which is what lets ``base`` bound a digit.
        """
        value = 0.0
        for digit in digits:
            value = value * base + digit * 2
        return value

    @staticmethod
    def _pack_base(boards: int, rounds: int) -> int:
        """Smallest base that keeps every digit in its own place: a
        board yields at most 1 game point per round, so a digit summed
        over every board and round cannot exceed ``2 × boards ×
        rounds`` once doubled."""
        return 2 * boards * max(rounds, 1) + 1


class BoardCountTieBreak(_BoardTieBreak):
    """Board Count (BC, Art. 12.1): for each board, the board number
    multiplied by the game points scored on it, summed.

    "The lower the sum of these products, the higher the ranking of the
    team" — the standings rank on a descending value, so the sum is
    negated. Art. 12.1 also restricts its use to teams that scored the
    same number of game points; that is left to the arbiter, since a
    tie-break cannot decline to be listed.
    """

    @staticmethod
    def static_id() -> str:
        return 'TEAM_BOARD_COUNT'

    @staticmethod
    def static_name() -> str:
        return _('Board count')

    @property
    def base_acronym(self) -> str:
        return 'BC'

    @property
    def base_help_text(self) -> str:
        return _(
            'Each board number multiplied by the game points scored on '
            'that board, summed over the tournament. The lower the sum, '
            'the higher the ranking — it rewards points won on the top '
            'boards. Only meaningful between teams on equal game points.'
        )

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        boards = tournament_context.team_player_count
        totals = self._board_totals(
            team_record, boards, after_round, tournament_context
        )
        return board_count_key(totals)


class TopBoardResultsTieBreak(_BoardTieBreak):
    """Top Board Results (TBR, Art. 12.2): the game points scored on
    board 1; if that isn't decisive, the topmost board not yet counted,
    and so on down.

    That is a lexicographic comparison of the per-board totals from the
    top down, packed into a single value (see :meth:`_pack`). Eight
    boards over eleven rounds pack into 177^7 ≈ 3×10^15, inside the
    range float64 represents exactly; deeper team formats would need a
    comparison-based ranking instead.
    """

    @staticmethod
    def static_id() -> str:
        return 'TEAM_TOP_BOARD_RESULTS'

    @staticmethod
    def static_name() -> str:
        return _('Top board results')

    @property
    def base_acronym(self) -> str:
        return 'TBR'

    @property
    def base_help_text(self) -> str:
        return _(
            'The game points scored on board 1 over the tournament; if '
            'that leaves the teams level, the next board down decides, '
            'and so on.'
        )

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        boards = tournament_context.team_player_count
        totals = self._board_totals(
            team_record, boards, after_round, tournament_context
        )
        base = self._pack_base(boards, tournament_context.rounds)
        return self._pack(list(top_board_key(totals)), base)


class BottomBoardEliminationTieBreak(_BoardTieBreak):
    """Bottom Board Elimination (BBE, Art. 12.3): the game points
    scored on every board except the bottom one; if that isn't
    decisive, exclude the bottom-most board not yet excluded, and so
    on.

    Each step is the running total of the boards still counted, so the
    comparison is lexicographic over those totals from the widest set
    to the narrowest — packed as for :class:`TopBoardResultsTieBreak`.
    """

    @staticmethod
    def static_id() -> str:
        return 'TEAM_BOTTOM_BOARD_ELIMINATION'

    @staticmethod
    def static_name() -> str:
        return _('Bottom board elimination')

    @property
    def base_acronym(self) -> str:
        return 'BBE'

    @property
    def base_help_text(self) -> str:
        return _(
            'The game points scored on every board but the bottom one; '
            'if that leaves the teams level, the bottom-most board left '
            'is excluded in turn until one team is ahead.'
        )

    def compute_team_value(
        self,
        team_record: TeamRecord,
        all_records: dict[int, TeamRecord],
        tournament_context: TeamTieBreakContext,
        *,
        after_round: int,
    ) -> float:
        boards = tournament_context.team_player_count
        totals = self._board_totals(
            team_record, boards, after_round, tournament_context
        )
        base = self._pack_base(boards, tournament_context.rounds)
        return self._pack(list(bottom_board_key(totals)), base)
