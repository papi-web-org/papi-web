"""FFE-specific rule sets — federation cups whose tournaments need
pre-configured scoring, tie-breaks, lineup constraints, etc.

The rule set is per-tournament: the arbiter creates one tournament for
each phase / group and picks its pairing system (Suisse / Molter /
round-robin) themselves. ``apply_defaults`` then writes the cup's
defaults into the freshly-built ``StoredTournament``.

Game-point scoring for these cups differs between Swiss / round-robin
("counts wins only", draws contribute 0 game points) and Molter (1 /
0.5 / 0). The Molter pairing systems live in a future plugin contribution;
until those land, ``apply_defaults`` treats every system as "Suisse-style"
because the plugin only ships Swiss / round-robin variations today.

Roster constraints (max size, Elo caps, parity) are applied at runtime
by the team-roster modal, not stored on the tournament — that lives in
future phases.
"""

from abc import ABC
from typing import override, TYPE_CHECKING

from common.i18n import _, ngettext
from data.pairings.fixed_table import FixedPairingTable, TablePairing as P
from data.rule_sets import RuleSet
from data.rule_sets.rule_sets import PointAdjustment, RuleSetField
from plugins.ffe.utils import FFEUtils, PlayerFFELicence
from utils.enum import (
    EventType,
    PlayerGender,
    Result,
    ScoreType,
    TeamColourType,
    TeamSortMode,
)

if TYPE_CHECKING:
    from data.teams.team import Team
    from data.teams.team_board import TeamBoard
    from database.sqlite.event.event_store import StoredTournament


# Both FFE cups use the same match-point scheme (3-2-1-0 with PAB
# treated as a win for the exempt team) and the same Suisse-style
# game-point scheme. Centralising the constants here so the two rule
# sets stay in sync.
#
# A match lost by forfeit scores 0 rather than the 1 a match played
# and lost is worth ("un match perdu par forfait 0 point"), which is
# what the absence value says.
_FFE_MATCH_POINTS: dict[int, float] = {
    Result.WIN.value: 3.0,
    Result.DRAW.value: 2.0,
    Result.LOSS.value: 1.0,
    Result.ZERO_POINT_BYE.value: 0.0,
    Result.PAIRING_ALLOCATED_BYE.value: 3.0,
}

# Suisse / all-play-all: only wins count, draws are uncounted, losses
# are zero. Absence scores 0. (For finals, the FFE rules add a -1
# forfeit penalty; that needs a negative game point, deferred until it
# can be emitted via the TRF 299 field.)
_FFE_GAME_POINTS_SUISSE_STYLE: dict[int, float] = {
    Result.WIN.value: 1.0,
    Result.DRAW.value: 0.0,
    Result.LOSS.value: 0.0,
    Result.ZERO_POINT_BYE.value: 0.0,
    Result.PAIRING_ALLOCATED_BYE.value: 2.0,
}

# Molter: standard 1 / 0.5 / 0 game-points. Absence scores 0.
_FFE_GAME_POINTS_MOLTER: dict[int, float] = {
    Result.WIN.value: 1.0,
    Result.DRAW.value: 0.5,
    Result.LOSS.value: 0.0,
    Result.ZERO_POINT_BYE.value: 0.0,
    Result.PAIRING_ALLOCATED_BYE.value: 0.0,
}

# Ranking order for the Swiss / round-robin phases of the two FFE
# team cups: the points (the primary score) → game-points differential →
# game-points "pour" → lowest own avg Elo. Same list applies to
# ``TEAM_SWISS`` and ``TEAM_ROUND_ROBIN`` because the regulations
# bracket "Système Suisse ou toutes rondes" together.
_FFE_SUISSE_TIE_BREAKS: list[tuple[str, dict]] = [
    ('POINTS', {}),
    ('ffe-GP-DIFFERENTIAL', {}),
    ('ffe-GP-FOR', {}),
    ('ffe-OWN-AVG-ELO', {}),
]

# Championnat Féminin (F01 §4.4.a), Suisse / round-robin phases:
# differential, then points "pour", then the per-board differentials.
# Unlike Loubatière there is no lowest-Elo step — F01 keeps that for
# Molter only (§4.4.b).
_FFE_FEMININ_SUISSE_TIE_BREAKS: list[tuple[str, dict]] = [
    ('POINTS', {}),
    ('ffe-GP-DIFFERENTIAL', {}),
    ('ffe-GP-FOR', {}),
    ('ffe-BOARD-DIFFERENTIAL', {}),
]

# Molter phases: Berlin then lowest own avg Elo.
_FFE_MOLTER_TIE_BREAKS: list[tuple[str, dict]] = [
    ('POINTS', {}),
    ('ffe-BERLIN', {}),
    ('ffe-OWN-AVG-ELO', {}),
]

# Results that mean a game was actually contested over the board, as
# opposed to a forfeit, a bye, or an unplayed pairing.
_FFE_PLAYED_RESULTS = frozenset(
    {
        Result.WIN,
        Result.LOSS,
        Result.DRAW,
        Result.UNRATED_WIN,
        Result.UNRATED_LOSS,
        Result.UNRATED_DRAW,
    }
)

# Per-board results that count as a game lost by forfeit for the side
# that holds them.
_FFE_FORFEIT_LOSS_RESULTS = frozenset({Result.FORFEIT_LOSS, Result.DOUBLE_FORFEIT})


# 3 teams / 4 players — cup-specific Molter table used by both the
# Loubatière and Parité 3-team / 3-round phases. Not part of the
# standard FFE Molter registry (whose 3T×4P slot is a truncation of
# Tableau 1 that doesn't match the cup regulations).
_FFE_CUP_3T_4P_TABLE = FixedPairingTable(
    team_count=3,
    players_per_team=4,
    rounds=(
        (
            P('A', 1, 'B', 1),
            P('A', 2, 'C', 1),
            P('B', 2, 'C', 2),
            P('C', 3, 'B', 3),
            P('C', 4, 'A', 3),
            P('B', 4, 'A', 4),
        ),
        (
            P('B', 1, 'C', 1),
            P('B', 2, 'A', 1),
            P('C', 2, 'A', 2),
            P('A', 3, 'C', 3),
            P('A', 4, 'B', 3),
            P('C', 4, 'B', 4),
        ),
        (
            P('C', 1, 'A', 1),
            P('C', 2, 'B', 1),
            P('A', 2, 'B', 2),
            P('B', 3, 'A', 3),
            P('B', 4, 'C', 3),
            P('A', 4, 'C', 4),
        ),
    ),
    is_compromise=True,
)


def _fmt(value: float) -> str:
    """Render a points value the way the modal's number inputs accept
    it — integers without a trailing ``.0``."""
    return str(int(value)) if value == int(value) else str(value)


class _FfeTeamCupRuleSet(RuleSet, ABC):
    """Shared scaffold for the two FFE team cups. Both share the
    4-board team format, MP / GP scoring and colour rule; only roster
    constraints (max size, Elo caps, parity) differ — those land in a
    later phase."""

    @property
    @override
    def event_type(self) -> EventType:
        return EventType.TEAM

    @override
    def forced_team_sort_mode(self, pairing_system_id: str | None = None) -> str | None:
        # Swiss only: teams are ordered by their round-1 lineup's average
        # Elo. The table-driven systems draw their team letters by lot.
        if pairing_system_id != 'TEAM_SWISS':
            return None
        return TeamSortMode.LINEUP_AVERAGE_RATING.value

    @property
    @override
    def forced_prohibited_pairing(self) -> tuple[str, bool] | None:
        # The cups keep teams of the same affiliation apart when the
        # pairing allows it (soft constraint on the team group).
        return ('team-group', False)

    @property
    def round3_winner_protection(self) -> bool:
        """Two teams that have won both of their first two matches are not
        paired together in round 3 (FFE cup regulations). On by default;
        each competition turns it off for the phases its regulations
        exempt, from its own fields."""
        return True

    @property
    @override
    def managed_fields(self) -> set[str]:
        return {
            'rounds',
            'team_player_count',
            'roster_max_size',
            'primary_score',
            'team_colour_type',
            'enforce_roster_order',
            'mp_win',
            'mp_draw',
            'mp_loss',
            'mp_zpb',
            'mp_pab',
            'gp_win',
            'gp_draw',
            'gp_loss',
            'gp_zpb',
            'gp_pab',
        }

    @override
    def apply_defaults(
        self,
        stored_tournament: 'StoredTournament',
        pairing_system_id: str | None = None,
    ) -> None:
        stored_tournament.team_player_count = 4
        stored_tournament.roster_max_size = self.roster_max_size
        stored_tournament.team_colour_type = TeamColourType.A.value
        stored_tournament.enforce_roster_order = True
        stored_tournament.match_points = dict(_FFE_MATCH_POINTS)
        stored_tournament.primary_score = self._primary_score_for(pairing_system_id)
        # Overlay only the game-point fields the rule set manages
        # (win/draw/loss/zpb), preserving any the user set that it does not —
        # notably gp_pab — instead of replacing the whole mapping.
        game_points = dict(stored_tournament.game_points or {})
        game_points.update(self._game_points_for(pairing_system_id))
        stored_tournament.game_points = game_points
        if pairing_system_id is not None:
            # ``stored_tournament.pairing`` is the full variation id, so the
            # round count can differ between variations of a system (single
            # vs double round-robin).
            rounds = self.rounds_for_pairing(
                pairing_system_id, stored_tournament.pairing
            )
            if rounds is not None:
                stored_tournament.rounds = rounds

    @staticmethod
    def _primary_score_for(pairing_system_id: str | None) -> str:
        # The cup regs group "Système Suisse ou toutes rondes" under match
        # points; only Molter scores on game points. A two-game match is a
        # (double) round-robin, so it falls in with the round-robin group.
        if pairing_system_id == 'MOLTER':
            return ScoreType.GAME_POINTS.value
        return ScoreType.MATCH_POINTS.value

    @staticmethod
    def _game_points_for(pairing_system_id: str | None) -> dict[int, float]:
        # Suisse / round-robin (incl. a two-game double round-robin):
        # wins-only (1 / 0 / 0) — draws are the uncounted "X". Only Molter
        # counts every game (1 / 0.5 / 0).
        if pairing_system_id == 'MOLTER':
            return _FFE_GAME_POINTS_MOLTER
        return _FFE_GAME_POINTS_SUISSE_STYLE

    @property
    @override
    def tie_break_overrides_by_pairing(self) -> dict[str, list[tuple[str, dict]]]:
        return {
            'TEAM_SWISS': _FFE_SUISSE_TIE_BREAKS,
            'TEAM_ROUND_ROBIN': _FFE_SUISSE_TIE_BREAKS,
            'MOLTER': _FFE_MOLTER_TIE_BREAKS,
        }

    @property
    def is_final_phase(self) -> bool:
        """Whether this tournament is the competition's final, per the
        cup's own phase field. Cups that declare no phase never are."""
        return False

    @override
    def rounds_for_pairing(
        self,
        pairing_system_id: str,
        pairing_variation_id: str | None = None,
    ) -> int | None:
        # Phase rounds (Loubatière / Parité): the final runs 5 rounds
        # whatever the system — the team-count table that picks the system
        # only covers the qualifying phases, which run 3, apart from the
        # aller-retour (double round-robin, a 2-team home-and-away) at 2.
        from data.pairings.variations import DoubleBergerTeamRoundRobinVariation

        if self.is_final_phase:
            return 5
        if pairing_variation_id == DoubleBergerTeamRoundRobinVariation.static_id():
            return 2
        return {
            'TEAM_SWISS': 3,
            'MOLTER': 3,
            'TEAM_ROUND_ROBIN': 3,
        }.get(pairing_system_id)

    @override
    def molter_table_overrides(self) -> dict[tuple[int, int], FixedPairingTable]:
        return {(3, 4): _FFE_CUP_3T_4P_TABLE}

    # Subclass attribute: per-player rating ceiling. None = skip.
    PLAYER_RATING_CAP: int | None = None

    @override
    def roster_warnings(self, team: 'Team') -> list[str]:
        msgs: list[str] = []
        # The cups require an A (competition) FFE licence for every player.
        without_a_licence = [
            player
            for player in team.players
            if FFEUtils.get_player_plugin_data(player).ffe_licence != PlayerFFELicence.A
        ]
        if without_a_licence:
            names = ', '.join(player.full_name for player in without_a_licence)
            msgs.append(
                _('Player without an A (competition) FFE licence: {names}.').format(
                    names=names
                )
            )
        if (cap := self.PLAYER_RATING_CAP) is not None:
            over = [
                p
                for p in team.players
                if p.event_default_rating and p.event_default_rating > cap
            ]
            if over:
                names = ', '.join(
                    f'{p.full_name} ({p.event_default_rating})' for p in over
                )
                msgs.append(
                    _('Player rating above {cap}: {names}.').format(
                        cap=cap, names=names
                    )
                )
        msgs.extend(self._lineup_sum_warnings(team))
        return msgs

    def _lineup_sum_warnings(self, team: 'Team') -> list[str]:
        """Lineup-rating-sum cap warnings. Subclasses override when
        their regulations cap the fielded lineup's total rating.
        Default: no constraint."""
        return []

    @staticmethod
    def _team_round_match(team: 'Team', round_: int) -> 'TeamBoard | None':
        """The team's real (non-bye) team-match for ``round_``, or
        ``None`` when the team sat out / wasn't paired that round."""
        tournament = team.tournament
        if tournament is None:
            return None
        for team_board in tournament.get_round_team_boards(round_):
            stored = team_board.stored_team_board
            if (
                team.id in (stored.team_a_id, stored.team_b_id)
                and not team_board.is_bye
            ):
                return team_board
        return None

    @staticmethod
    def _team_board_breakdown(
        team_board: 'TeamBoard', team_id: int
    ) -> list[tuple[int, bool, bool]]:
        """Per individual board, in board order, a tuple of
        ``(index, team_forfeited, game_played)``:

        - ``team_forfeited`` — the team didn't field a player on the
          board, or its player there lost by forfeit.
        - ``game_played`` — both teams fielded a player and the board
          carries a real, contested result.
        """
        rows: list[tuple[int, bool, bool]] = []
        for board in team_board.boards:
            white_team, black_team = team_board.board_team_ids(board)
            if team_id not in (white_team, black_team):
                continue
            team_is_white = white_team == team_id
            if team_is_white:
                team_player = board.optional_white_tournament_player
                team_pairing = board.optional_white_pairing
            else:
                team_player = board.black_tournament_player
                team_pairing = board.optional_black_pairing
            team_result = team_pairing.result if team_pairing else Result.NO_RESULT
            forfeited = team_player is None or team_result in _FFE_FORFEIT_LOSS_RESULTS
            played = (
                board.optional_white_tournament_player is not None
                and board.black_tournament_player is not None
                and board.result in _FFE_PLAYED_RESULTS
            )
            rows.append((board.index, forfeited, played))
        return rows

    def _round_breakdown(
        self, team: 'Team', round_: int
    ) -> list[tuple[int, bool, bool]]:
        """``(index, forfeited, played)`` per board for the team this round,
        for either pairing model: a team-vs-team match (Suisse / round-robin)
        or a flat fixed-table round (Molter), which has no team_board."""
        team_board = self._team_round_match(team, round_)
        if team_board is not None:
            return self._team_board_breakdown(team_board, team.id)
        return self._flat_round_breakdown(team, round_)

    @staticmethod
    def _flat_round_breakdown(
        team: 'Team', round_: int
    ) -> list[tuple[int, bool, bool]]:
        """Flat fixed-table (Molter) counterpart of
        :meth:`_team_board_breakdown`: one row per team seat, holes
        included. Empty when the team isn't playing this round."""
        tournament = team.tournament
        if tournament is None:
            return []
        slots = team.effective_round_slots(round_)
        players_by_id = tournament.tournament_players_by_id
        engaged = any(
            player is not None
            and (tp := players_by_id.get(player.id)) is not None
            and round_ in tp.pairings_by_round
            for player in slots
        )
        if not engaged:
            return []
        rows: list[tuple[int, bool, bool]] = []
        for index, player in enumerate(slots):
            if player is None:
                # No player fielded on this board ⇒ forfeited, not played.
                rows.append((index, True, False))
                continue
            tp = players_by_id.get(player.id)
            pairing = tp.pairings_by_round.get(round_) if tp else None
            result = pairing.result if pairing else Result.NO_RESULT
            board = pairing.board if pairing else None
            forfeited = result in _FFE_FORFEIT_LOSS_RESULTS
            played = (
                board is not None
                and board.optional_white_tournament_player is not None
                and board.black_tournament_player is not None
                and board.result in _FFE_PLAYED_RESULTS
            )
            rows.append((index, forfeited, played))
        return rows

    @override
    def team_point_adjustment(
        self, team: 'Team', round_: int
    ) -> 'PointAdjustment | None':
        # -1 when a game was played on a board below a forfeited one.
        return self._following_board_played_penalty(team, round_)

    def _forfeit_loss_penalty(
        self, team: 'Team', round_: int
    ) -> 'PointAdjustment | None':
        """A game lost by forfeit counts −1 game point ("Une partie perdue
        par forfait sportif est comptée -1"). Applies to every pairing
        system, Molter included."""
        if team.tournament is None:
            return None
        count = sum(
            1
            for _index, forfeited, _played in self._round_breakdown(team, round_)
            if forfeited
        )
        if not count:
            return None
        return PointAdjustment(
            gp=-float(count),
            explanation=ngettext(
                '{n} game lost by forfeit, counted as -1.',
                '{n} games lost by forfeit, counted as -1 each.',
                count,
            ).format(n=count),
        )

    def _following_board_played_penalty(
        self, team: 'Team', round_: int
    ) -> 'PointAdjustment | None':
        """−1 for each board the team forfeited while a game was actually
        played on a following (lower) board — i.e. a hole above a board it
        did field (FFE 4.1.c, "pour les deux systèmes"). Works for Molter
        too via the flat breakdown."""
        rows = self._round_breakdown(team, round_)
        played_indexes = [index for index, _f, played in rows if played]
        if not played_indexes:
            return None
        last_played = max(played_indexes)
        count = sum(
            1 for index, forfeited, _p in rows if forfeited and index < last_played
        )
        if not count:
            return None
        return PointAdjustment(
            gp=-float(count),
            explanation=ngettext(
                '{n} forfeited board above a board on which a game was '
                'played, counted as -1.',
                '{n} forfeited boards above a board on which a game was '
                'played, counted as -1 each.',
                count,
            ).format(n=count),
        )

    @override
    def form_defaults(
        self,
        pairing_system_id: str | None = None,
        pairing_variation_id: str | None = None,
    ) -> dict[str, str]:
        gp = self._game_points_for(pairing_system_id)
        defaults: dict[str, str] = {
            'team_player_count': '4',
            'roster_max_size': str(self.roster_max_size)
            if self.roster_max_size
            else '',
            'primary_score': self._primary_score_for(pairing_system_id),
            'team_colour_type': TeamColourType.A.value,
            'enforce_roster_order': 'on',
            'mp_win': _fmt(_FFE_MATCH_POINTS[Result.WIN.value]),
            'mp_draw': _fmt(_FFE_MATCH_POINTS[Result.DRAW.value]),
            'mp_loss': _fmt(_FFE_MATCH_POINTS[Result.LOSS.value]),
            'mp_zpb': _fmt(_FFE_MATCH_POINTS[Result.ZERO_POINT_BYE.value]),
            'mp_pab': _fmt(_FFE_MATCH_POINTS[Result.PAIRING_ALLOCATED_BYE.value]),
            'gp_win': _fmt(gp[Result.WIN.value]),
            'gp_draw': _fmt(gp[Result.DRAW.value]),
            'gp_loss': _fmt(gp[Result.LOSS.value]),
            'gp_zpb': _fmt(gp[Result.ZERO_POINT_BYE.value]),
            'gp_pab': _fmt(gp[Result.PAIRING_ALLOCATED_BYE.value]),
        }
        if pairing_system_id is not None:
            rounds = self.rounds_for_pairing(pairing_system_id, pairing_variation_id)
            if rounds is not None:
                defaults['rounds'] = str(rounds)
        return defaults


_LOUBATIERE_PHASE_DEPARTMENTAL = 'departmental'
_LOUBATIERE_PHASE_2 = 'phase-2'
_LOUBATIERE_PHASE_3 = 'phase-3'
_LOUBATIERE_PHASE_FINAL = 'final'


def _loubatiere_phase_choices() -> tuple[tuple[str, str], ...]:
    """Built on each call: ``_()`` translates eagerly, so a module-level
    tuple would freeze the labels in whichever locale happened to be
    active when the module was first imported."""
    return (
        (_LOUBATIERE_PHASE_DEPARTMENTAL, _('Departmental phase')),
        (_LOUBATIERE_PHASE_2, _('Phase 2')),
        (_LOUBATIERE_PHASE_3, _('Phase 3')),
        (_LOUBATIERE_PHASE_FINAL, _('Final')),
    )


class CoupeJeanClaudeLoubatiereRuleSet(_FfeTeamCupRuleSet):
    """FFE *Coupe Jean-Claude Loubatière* (C03) — 4-board team cup.

    The cup runs in four phases, which the arbiter picks in the
    tournament form: the phase sets the round count and whether the
    round-3 pairing restriction applies."""

    # Players ≤1800 Elo for phase 1; later phases let phase-1 alumni
    # back in regardless of rating. Surfaced as a warning so the
    # arbiter judges case by case.
    PLAYER_RATING_CAP = 1800

    @property
    @override
    def config_fields(self) -> tuple[RuleSetField, ...]:
        return (
            RuleSetField(
                id='phase',
                label=_('Phase'),
                kind='select',
                default=_LOUBATIERE_PHASE_DEPARTMENTAL,
                choices=_loubatiere_phase_choices(),
                affects_defaults=True,
                locked_once_paired=True,
            ),
        )

    @property
    def phase(self) -> str:
        return self.config_value('phase')

    @property
    @override
    def round3_winner_protection(self) -> bool:
        # Two teams on 2/2 are kept apart in round 3, except in a phase
        # qualifying a single team and in the final (C03 §3.2). Phase 3
        # always qualifies one team per group (§1.2), and the earlier
        # phases only reach a single qualifying place below 5 teams,
        # where the pairing system is never Swiss — so the exception is
        # exactly "phase 3 or final".
        #
        # That last step rests on §1.2 qualifying a team per 4 entered
        # (a per-5 scale would hold too: the smallest Swiss group, 6
        # teams, still earns 2 places). Should the scale ever reach one
        # place per 6, a 6-team Swiss would qualify a single team unless
        # the 10% women-and-girls bonus adds one — and the arbiter would
        # have to say, as they do for the Parité.
        return self.phase in (
            _LOUBATIERE_PHASE_DEPARTMENTAL,
            _LOUBATIERE_PHASE_2,
        )

    @property
    @override
    def is_final_phase(self) -> bool:
        return self.phase == _LOUBATIERE_PHASE_FINAL

    @override
    def team_point_adjustment(
        self, team: 'Team', round_: int
    ) -> 'PointAdjustment | None':
        # A game lost by forfeit counts -1 game point.
        return self._forfeit_loss_penalty(team, round_)

    @property
    @override
    def roster_max_size(self) -> int | None:
        return 5

    @staticmethod
    @override
    def static_id() -> str:
        return 'ffe-coupe-jean-claude-loubatiere'

    @staticmethod
    @override
    def static_name() -> str:
        return _('Jean-Claude Loubatière Cup')

    @property
    @override
    def description(self) -> str:
        return _(
            'FFE 4-board team cup. 5-player roster cap, max Elo 1800 '
            'per player, mixed-system schedule (Swiss / Molter / round-robin).'
        )


_FEMININ_N1F = 'n1f'
_FEMININ_N2F_ZONE = 'n2f-zone'
_FEMININ_N2F_PHASE_2 = 'n2f-phase-2'


def _feminin_division_choices() -> tuple[tuple[str, str], ...]:
    """Built on each call — see :func:`_loubatiere_phase_choices`."""
    return (
        (_FEMININ_N1F, _('Nationale 1 Féminine')),
        (_FEMININ_N2F_ZONE, _('Nationale 2 Féminine, inter-departmental zone phase')),
        (_FEMININ_N2F_PHASE_2, _('Nationale 2 Féminine, second phase')),
    )


class ChampionnatFemininN1N2RuleSet(_FfeTeamCupRuleSet):
    """FFE *Championnat de France Féminin des Clubs*, divisions
    Nationale 1 (N1F) and Nationale 2 (N2F).

    Same 4-board team-cup chassis as Loubatière (MP/GP scoring,
    Molter tie-breaks, 5-player roster, lineup follows the roster
    order). The cup-specific 1800 Elo cap doesn't apply; in its
    place the roster must consist entirely of women players —
    enforced as a soft warning so the arbiter can override.

    Only the N2F zone phase pairs "with the Swiss complementary rules"
    (F01 §1.2.c), so the division the arbiter picks decides whether the
    round-3 restriction and the same-club avoidance apply at all. The
    Top 12F is out of scope: it is a 12-team round-robin with
    semi-finals, not this format.

    The Suisse / round-robin departage of F01 §4.4.a is applied:
    differential, then points "pour", then the sum of the differentials
    on board 1, board 2 and so on.
    """

    @property
    @override
    def config_fields(self) -> tuple[RuleSetField, ...]:
        return (
            RuleSetField(
                id='division',
                label=_('Division'),
                kind='select',
                default=_FEMININ_N1F,
                choices=_feminin_division_choices(),
                help_text=_(
                    'Sets whether the Swiss complementary rules apply — only '
                    'the N2F zone phase plays with them.'
                ),
            ),
        )

    @property
    def division(self) -> str:
        return self.config_value('division')

    @property
    def is_nationale_2(self) -> bool:
        """Whether the chosen division is one of the two Nationale 2
        phases, the Nationale 1 being the only other option."""
        return self.division in (_FEMININ_N2F_ZONE, _FEMININ_N2F_PHASE_2)

    @property
    @override
    def round3_winner_protection(self) -> bool:
        # N1F and the N2F second phase are paired "sans application des
        # règles complémentaires relatives au système Suisse" (F01 §1.2.b,
        # §1.2.c), which is where this rule lives. The zone phase's own
        # single-qualifying-place exception can never change a pairing:
        # it applies below 4 teams, where the group is either a 2-team
        # Swiss (one possible pairing) or an odd Molter (a fixed table).
        return self.division == _FEMININ_N2F_ZONE

    @property
    @override
    def forced_prohibited_pairing(self) -> tuple[str, bool] | None:
        # Same-club avoidance is complementary rule 3, so it rides along
        # with the division rather than applying throughout.
        if self.division != _FEMININ_N2F_ZONE:
            return None
        return super().forced_prohibited_pairing

    @property
    @override
    def roster_max_size(self) -> int | None:
        return 5

    @property
    @override
    def tie_break_overrides_by_pairing(self) -> dict[str, list[tuple[str, dict]]]:
        return {
            'TEAM_SWISS': _FFE_FEMININ_SUISSE_TIE_BREAKS,
            'TEAM_ROUND_ROBIN': _FFE_FEMININ_SUISSE_TIE_BREAKS,
            'MOLTER': _FFE_MOLTER_TIE_BREAKS,
        }

    @staticmethod
    @override
    def static_id() -> str:
        return 'ffe-championnat-feminin-n1-n2'

    @staticmethod
    @override
    def static_name() -> str:
        return _('FFE Women championship (N1F / N2F)')

    @property
    @override
    def description(self) -> str:
        return _(
            'FFE Nationale 1 / Nationale 2 Féminine. 5-player roster, '
            '4-board team matches, mixed Suisse / Molter / round-robin schedule. '
            'Roster must consist of women players only.'
        )

    @override
    def roster_warnings(self, team: 'Team') -> list[str]:
        # The parent's licence check applies; the rating-cap check is a
        # no-op here (no Elo cap on the Féminine divisions). Add the
        # women-only roster check on top.
        msgs = super().roster_warnings(team)
        non_women = [p for p in team.players if p.gender != PlayerGender.WOMAN]
        if non_women:
            names = ', '.join(p.full_name for p in non_women)
            msgs.append(
                _('Roster must consist of women players only: {names}.').format(
                    names=names
                )
            )
        return msgs


_PARITE_PHASE_ZONE = 'zone'
_PARITE_PHASE_2 = 'phase-2'
_PARITE_PHASE_2_SINGLE = 'phase-2-single'
_PARITE_PHASE_FINAL = 'final'

# Phase 2 qualifies "the first or the first two of each group, as the Coupe
# direction allocates" (C04 §1.2) — the only thing that varies with it is
# the round-3 restriction, so it rides in the phase list rather than in a
# second field that would be meaningless in the other phases.
_PARITE_PHASES_WITH_ROUND_3_PROTECTION = (_PARITE_PHASE_ZONE, _PARITE_PHASE_2)


def _parite_phase_choices() -> tuple[tuple[str, str], ...]:
    """Built on each call — see :func:`_loubatiere_phase_choices`."""
    return (
        (_PARITE_PHASE_ZONE, _('Inter-departmental zone phase')),
        (_PARITE_PHASE_2, _('Phase 2 (two teams qualify)')),
        (_PARITE_PHASE_2_SINGLE, _('Phase 2 (a single team qualifies)')),
        (_PARITE_PHASE_FINAL, _('Final')),
    )


class CoupeDeLaPariteRuleSet(_FfeTeamCupRuleSet):
    """FFE *Coupe de la Parité* (C04) — 2 men + 2 women per match.

    The cup runs in three phases, which the arbiter picks in the
    tournament form. Phase 2 offers two entries: how many teams it
    qualifies is the Coupe direction's call, and nothing in the
    tournament reveals it."""

    @property
    @override
    def config_fields(self) -> tuple[RuleSetField, ...]:
        return (
            RuleSetField(
                id='phase',
                label=_('Phase'),
                kind='select',
                default=_PARITE_PHASE_ZONE,
                choices=_parite_phase_choices(),
                affects_defaults=True,
                locked_once_paired=True,
            ),
        )

    @property
    def phase(self) -> str:
        return self.config_value('phase')

    @property
    @override
    def is_final_phase(self) -> bool:
        return self.phase == _PARITE_PHASE_FINAL

    @property
    @override
    def round3_winner_protection(self) -> bool:
        # Two teams on 2/2 are kept apart in round 3, except in a phase
        # qualifying a single team and in the final (C04 §3.2). The zone
        # phase only reaches a single qualifying place below 4 teams,
        # where the pairing system is never Swiss (§1.2, §3.2), so it
        # always protects.
        return self.phase in _PARITE_PHASES_WITH_ROUND_3_PROTECTION

    @property
    @override
    def roster_max_size(self) -> int | None:
        return 6

    @override
    def roster_warnings(self, team: 'Team') -> list[str]:
        msgs = super().roster_warnings(team)
        msgs.extend(self._gender_balance_warnings(team))
        return msgs

    @staticmethod
    def _gender_balance_warnings(team: 'Team') -> list[str]:
        # The roster holds at most 3 men and 3 women,
        # and each match fields 2 men + 2 women — so a roster needs at
        # least 2 of each gender to field a legal lineup, and no more
        # than 3 of either.
        men = sum(1 for p in team.players if p.gender == PlayerGender.MAN)
        women = sum(1 for p in team.players if p.gender == PlayerGender.WOMAN)
        msgs: list[str] = []
        if men < 2:
            msgs.append(
                _('Need at least 2 men on the roster ({n} listed).').format(n=men)
            )
        elif men > 3:
            msgs.append(
                _('At most 3 men allowed on the roster ({n} listed).').format(n=men)
            )
        if women < 2:
            msgs.append(
                _('Need at least 2 women on the roster ({n} listed).').format(n=women)
            )
        elif women > 3:
            msgs.append(
                _('At most 3 women allowed on the roster ({n} listed).').format(n=women)
            )
        return msgs

    @override
    def _lineup_sum_warnings(self, team: 'Team') -> list[str]:
        tournament = team.tournament
        if tournament is None or not tournament.team_player_count:
            return []
        roster_size = len(team.players)
        if roster_size == 0:
            return []
        lineup_size = min(tournament.team_player_count, roster_size)
        # Lineup of 4 ≤ 8000 ; lineup of 3 < 6000.
        if lineup_size >= 4:
            cap = 8000
        elif lineup_size == 3:
            cap = 5999
        else:
            return []
        bottom_ratings = sorted(p.event_default_rating or 0 for p in team.players)[
            :lineup_size
        ]
        bottom_sum = sum(bottom_ratings)
        if bottom_sum <= cap:
            return []
        return [
            _('No legal {n}-player lineup: cheapest sum {sum} > {cap} cap.').format(
                n=lineup_size, sum=bottom_sum, cap=cap
            )
        ]

    @staticmethod
    @override
    def static_id() -> str:
        return 'ffe-coupe-de-la-parite'

    @staticmethod
    @override
    def static_name() -> str:
        return _('Mixed Cup')

    @property
    @override
    def description(self) -> str:
        return _(
            'FFE mixed team cup. 6-player roster (3M + 3W), per-match '
            'lineup must field 2 men and 2 women, team Elo capped at 8000.'
        )
