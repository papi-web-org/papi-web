"""FFE *Championnat de France des écoles et collèges* (J03) — team phases.

The J03 championship runs in three phases (art. 1.3): an individual
departmental phase, an academic phase by teams, and the national final by
teams. This rule set covers the two team phases; the individual one is a
different event type and would be a rule set of its own.

Which phase the tournament is gets picked in the tournament form: it sets
the round count and locks it for the national final (art. 4.3), whose
format the regulation fixes. The academic phase is left free, because its
system and round count follow the number of entered teams (art. 3.3.1),
which a rule set can't see.

The two categories — écoles and collèges (art. 1.2.1) — differ only in the
Elo floor used for estimated ratings when numbering teams (art. 5.1.5,
799 vs 999). Nothing in the tournament configuration carries that, so the
rule set doesn't offer the choice rather than offering one that does
nothing.

Not encoded, for want of somewhere to put it:

- art. 4.4's -1 for a missing team shirt, which is the arbiter's call and
  belongs in the manual per-round adjustment;
- art. 5.2's match-sheet rules (no holes, fixed order, at least two boys
  and two girls with -1 from the last board upwards), which are per-round
  lineup validations rather than tournament defaults.
"""

from typing import Any, override, TYPE_CHECKING

from common.i18n import _, ngettext
from data.rule_sets import RuleSet
from data.rule_sets.rule_sets import PointAdjustment, RuleSetField
from plugins.ffe.ffe_rule_sets import _FfeTeamCupRuleSet
from plugins.ffe.utils import FFEUtils, PlayerFFELicence
from plugins.fra_schools import PLUGIN_NAME as FRA_SCHOOLS_PLUGIN_NAME
from utils.enum import (
    EventType,
    PlayerGender,
    Result,
    ScoreType,
    TeamColourType,
    TeamSortMode,
)

if TYPE_CHECKING:
    from data.player import Player
    from data.teams.team import Team
    from database.sqlite.event.event_store import StoredTournament


# Art. 5.3.2: a won match is worth 3 points, a drawn one 2, a lost one 1.
# An exempt team "marque trois points de match" — the same 3 as a win.
# Art. 5.3.2: "Un match perdu par forfait sportif est compté 0 point",
# against the 1 a match played and lost scores — which is what the
# absence value says.
_J03_MATCH_POINTS: dict[int, float] = {
    Result.WIN.value: 3.0,
    Result.DRAW.value: 2.0,
    Result.LOSS.value: 1.0,
    Result.ZERO_POINT_BYE.value: 0.0,
    Result.PAIRING_ALLOCATED_BYE.value: 3.0,
}

# Art. 5.3.1: a won game scores 1, a lost one 0, and a draw is noted X and
# "n'est pas comptabilisée dans le score final" — so it contributes 0 too.
# Art. 5.3.2: an exempt team is treated as having won 5 game points to 0.
_J03_GAME_POINTS: dict[int, float] = {
    Result.WIN.value: 1.0,
    Result.DRAW.value: 0.0,
    Result.LOSS.value: 0.0,
    Result.ZERO_POINT_BYE.value: 0.0,
    Result.PAIRING_ALLOCATED_BYE.value: 5.0,
}

# Art. 5.1.1: "Une équipe est constituée de 8 élèves".
_J03_TEAM_PLAYER_COUNT = 8

# Art. 5.1.2: "une liste de 8 à 10 élèves".
_J03_ROSTER_MAX_SIZE = 10

# Art. 4.3: the national final is a 9-round Swiss.
_J03_NATIONAL_FINAL_ROUNDS = 9

# Art. 5.1.1 / 5.2.4: at least two girls and two boys.
_J03_MIN_PER_GENDER = 2

_J03_PHASE_ACADEMIC = 'academic'
_J03_PHASE_NATIONAL_FINAL = 'national-final'


def _j03_phase_choices() -> tuple[tuple[str, str], ...]:
    """The phase labels, built on each call. ``_()`` translates eagerly, so
    a module-level tuple would freeze the labels in whichever locale
    happened to be active when the module was first imported."""
    return (
        (_J03_PHASE_ACADEMIC, _('Academic phase')),
        (_J03_PHASE_NATIONAL_FINAL, _('National final')),
    )


# Art. 1.5: "Chaque joueur et joueuse doit être titulaire d'une licence FFE
# (A ou B) valable pour la saison en cours."
_J03_ACCEPTED_LICENCES = frozenset({PlayerFFELicence.A, PlayerFFELicence.B})

# Art. 5.3.3: on equal match points, teams are separated by the direct
# confrontation, then by the number of wins on board 1, then board 2, and
# so on, then by the gains/losses differential. The article scopes this to
# the first three places; applying it to the whole standings is a superset
# that changes nothing about who finishes 1st, 2nd or 3rd.
_J03_TIE_BREAKS: list[tuple[str, dict]] = [
    ('TEAM_EDE', {}),
    (f'{FRA_SCHOOLS_PLUGIN_NAME}-BOARD-ORDER-WINS', {}),
    ('ffe-GP-DIFFERENTIAL', {}),
]


def _fmt(value: float) -> str:
    """Render a points value the way the modal's number inputs accept it —
    integers without a trailing ``.0``."""
    return str(int(value)) if value == int(value) else str(value)


def _round_breakdown(team: 'Team', round_: int) -> list[tuple[int, bool, bool]]:
    """``(board index, team forfeited, game played)`` per board for the
    team this round, empty when it didn't play.

    Borrowed from the FFE cups, which read the same board records for the
    same purpose. Should a third rule set want them, these belong in
    ``data.rule_sets`` rather than in one plugin's module. J03 never uses
    Molter, so only the team-match path is needed."""
    team_board = _FfeTeamCupRuleSet._team_round_match(team, round_)
    if team_board is None:
        return []
    return _FfeTeamCupRuleSet._team_board_breakdown(team_board, team.id)


class ChampionnatScolaireRuleSet(RuleSet):
    """FFE *Championnat de France des écoles et collèges* (J03), team
    phases — 8-board teams of schoolchildren, 3/2/1 match points and a
    game-point score that counts wins only."""

    @staticmethod
    @override
    def static_id() -> str:
        return 'fra-schools-championnat-scolaire'

    @staticmethod
    @override
    def static_name() -> str:
        return _('French School Championship')

    @property
    @override
    def description(self) -> str:
        return _(
            'FFE 8-board school team championship. Roster of 8 to 10 pupils '
            'with at least 2 girls and 2 boys, draws are not counted in the '
            'score, 9-round Swiss for the national final.'
        )

    @property
    @override
    def event_type(self) -> EventType:
        return EventType.TEAM

    # -----------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------

    @property
    @override
    def config_fields(self) -> tuple[RuleSetField, ...]:
        return (
            RuleSetField(
                id='phase',
                label=_('Phase'),
                kind='select',
                default=_J03_PHASE_ACADEMIC,
                choices=_j03_phase_choices(),
                affects_defaults=True,
                locked_once_paired=True,
            ),
        )

    @property
    def phase(self) -> str:
        return self.config_value('phase')

    @property
    def is_national_final(self) -> bool:
        return self.phase == _J03_PHASE_NATIONAL_FINAL

    # -----------------------------------------------------------------
    # Tournament defaults
    # -----------------------------------------------------------------

    @property
    @override
    def managed_fields(self) -> set[str]:
        fields = {
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
        # Only the final has a round count of its own; leaving 'rounds'
        # unmanaged in the academic phase keeps the input editable there.
        if self.is_national_final:
            fields.add('rounds')
        return fields

    @override
    def apply_defaults(
        self,
        stored_tournament: 'StoredTournament',
        pairing_system_id: str | None = None,
    ) -> None:
        stored_tournament.team_player_count = _J03_TEAM_PLAYER_COUNT
        stored_tournament.roster_max_size = _J03_ROSTER_MAX_SIZE
        # Art. 3.3.2 / 4.3: the team named first has white on the odd
        # boards and black on the even ones.
        stored_tournament.team_colour_type = TeamColourType.A.value
        # Art. 5.2.2: the players stay in the order given in the team
        # composition, swaps are forbidden.
        stored_tournament.enforce_roster_order = True
        # Art. 5.3.3: "le classement est effectué selon le nombre total de
        # points de match".
        stored_tournament.primary_score = ScoreType.MATCH_POINTS.value
        stored_tournament.match_points = dict(_J03_MATCH_POINTS)
        # Overlay only the game-point results the rule set manages,
        # preserving any the arbiter set that it does not.
        game_points = dict(stored_tournament.game_points or {})
        game_points.update(_J03_GAME_POINTS)
        stored_tournament.game_points = game_points
        if pairing_system_id is not None:
            rounds = self.rounds_for_pairing(
                pairing_system_id, stored_tournament.pairing
            )
            if rounds is not None:
                stored_tournament.rounds = rounds

    @override
    def form_defaults(
        self,
        pairing_system_id: str | None = None,
        pairing_variation_id: str | None = None,
    ) -> dict[str, str]:
        defaults: dict[str, str] = {
            'team_player_count': str(_J03_TEAM_PLAYER_COUNT),
            'roster_max_size': str(_J03_ROSTER_MAX_SIZE),
            'primary_score': ScoreType.MATCH_POINTS.value,
            'team_colour_type': TeamColourType.A.value,
            'enforce_roster_order': 'on',
            'mp_win': _fmt(_J03_MATCH_POINTS[Result.WIN.value]),
            'mp_draw': _fmt(_J03_MATCH_POINTS[Result.DRAW.value]),
            'mp_loss': _fmt(_J03_MATCH_POINTS[Result.LOSS.value]),
            'mp_zpb': _fmt(_J03_MATCH_POINTS[Result.ZERO_POINT_BYE.value]),
            'mp_pab': _fmt(_J03_MATCH_POINTS[Result.PAIRING_ALLOCATED_BYE.value]),
            'gp_win': _fmt(_J03_GAME_POINTS[Result.WIN.value]),
            'gp_draw': _fmt(_J03_GAME_POINTS[Result.DRAW.value]),
            'gp_loss': _fmt(_J03_GAME_POINTS[Result.LOSS.value]),
            'gp_zpb': _fmt(_J03_GAME_POINTS[Result.ZERO_POINT_BYE.value]),
            'gp_pab': _fmt(_J03_GAME_POINTS[Result.PAIRING_ALLOCATED_BYE.value]),
        }
        if pairing_system_id is not None:
            rounds = self.rounds_for_pairing(pairing_system_id, pairing_variation_id)
            if rounds is not None:
                defaults['rounds'] = str(rounds)
        return defaults

    @override
    def rounds_for_pairing(
        self,
        pairing_system_id: str,
        pairing_variation_id: str | None = None,
    ) -> int | None:
        # Art. 4.3: the national final is paired "au système Suisse en 9
        # rondes". Art. 3.3.1 sets the academic phase's system and round
        # count from the number of entered teams (2 teams home and away,
        # 3-4 all rounds home and away, 5-6 all rounds, 7+ all rounds or a
        # Swiss of at least 5) — a count this hook can't derive, and one
        # the round-robin systems already compute themselves, so nothing
        # is locked there.
        if self.is_national_final and pairing_system_id == 'TEAM_SWISS':
            return _J03_NATIONAL_FINAL_ROUNDS
        return None

    @property
    @override
    def tie_break_overrides_by_pairing(self) -> dict[str, list[tuple[str, dict]]]:
        # Art. 5.3.3 is written for "système Suisse et toutes rondes", the
        # two systems the team phases use (art. 3.3.1, 4.3).
        return {
            'TEAM_SWISS': _J03_TIE_BREAKS,
            'TEAM_ROUND_ROBIN': _J03_TIE_BREAKS,
        }

    @override
    def forced_team_sort_mode(self, pairing_system_id: str | None = None) -> str | None:
        # Art. 5.1.5: teams are numbered on the average rating of every
        # player on the team sheet — the whole roster, not the fielded
        # lineup. Art. 5 is common to both team phases, so this holds
        # whatever the pairing system.
        return TeamSortMode.TEAM_AVERAGE_RATING.value

    @property
    @override
    def roster_max_size(self) -> int | None:
        return _J03_ROSTER_MAX_SIZE

    # -----------------------------------------------------------------
    # Roster checks
    # -----------------------------------------------------------------

    @override
    def roster_warnings(self, team: 'Team') -> list[str]:
        return [
            *self._licence_warnings(team),
            *self._gender_balance_warnings(team),
            *self._fide_order_warnings(team),
        ]

    @staticmethod
    def _licence_warnings(team: 'Team') -> list[str]:
        # Art. 1.5: an A or B FFE licence, on pain of an administrative
        # forfeit and 2 game points off the team total.
        without_licence = [
            player
            for player in team.players
            if FFEUtils.get_player_plugin_data(player).ffe_licence
            not in _J03_ACCEPTED_LICENCES
        ]
        if not without_licence:
            return []
        names = ', '.join(player.full_name for player in without_licence)
        return [_('Player without an A or B FFE licence: {names}.').format(names=names)]

    @staticmethod
    def _gender_balance_warnings(team: 'Team') -> list[str]:
        # Art. 5.1.1: a team is 8 pupils, at least 2 girls and 2 boys — so
        # a roster short of 2 of either can't field a legal match sheet
        # (art. 5.2.4).
        boys = sum(1 for player in team.players if player.gender == PlayerGender.MAN)
        girls = sum(1 for player in team.players if player.gender == PlayerGender.WOMAN)
        msgs: list[str] = []
        if boys < _J03_MIN_PER_GENDER:
            msgs.append(
                _('Need at least {min} boys on the roster ({n} listed).').format(
                    min=_J03_MIN_PER_GENDER, n=boys
                )
            )
        if girls < _J03_MIN_PER_GENDER:
            msgs.append(
                _('Need at least {min} girls on the roster ({n} listed).').format(
                    min=_J03_MIN_PER_GENDER, n=girls
                )
            )
        return msgs

    @classmethod
    def _fide_order_warnings(cls, team: 'Team') -> list[str]:
        # Art. 5.1.4: players holding a FIDE rating come before all the
        # others; getting it wrong is an administrative forfeit on the
        # offending boards.
        seen_unrated = False
        out_of_order = []
        for player in team.players:
            if cls._has_fide_rating(team, player):
                if seen_unrated:
                    out_of_order.append(player)
            else:
                seen_unrated = True
        if not out_of_order:
            return []
        names = ', '.join(player.full_name for player in out_of_order)
        return [
            _('FIDE-rated player listed after an unrated one: {names}.').format(
                names=names
            )
        ]

    @staticmethod
    def _has_fide_rating(team: 'Team', player: 'Player') -> bool:
        """Whether the player holds a FIDE rating — a fact about the player,
        independent of the rating the tournament ranks on. Art. 5.1.3 has
        the championship use the national rapid list, so the tournament's
        own rating type says nothing about art. 5.1.4."""
        tournament = team.tournament
        if tournament is not None:
            return bool(player.ratings[tournament.rating].fide)
        return any(bool(rating.fide) for rating in player.ratings.values())

    # -----------------------------------------------------------------
    # Per-round adjustments
    # -----------------------------------------------------------------

    @override
    def team_point_adjustment(
        self, team: 'Team', round_: int
    ) -> 'PointAdjustment | None':
        parts = [
            adjustment
            for adjustment in (self._forfeit_loss_penalty(team, round_),)
            if adjustment is not None
        ]
        if not parts:
            return None
        match_points = sum(part.mp for part in parts)
        game_points = sum(part.gp for part in parts)
        explanations = [part.explanation for part in parts if part.explanation]

        # Art. 5.3.1: "Si la somme des points de parties devient négative en
        # raison de forfaits sportifs, le total est ramené à 0." Giving back
        # exactly the overshoot lands the round on 0. Clamping here rather
        # than in the standings covers the match result too: the winner is
        # read from ``TeamBoard.effective_game_points``, which is the board
        # total plus this adjustment.
        board_points = self._own_board_game_points(team, round_)
        if board_points is not None and board_points + game_points < 0:
            game_points = -board_points
            explanations.append(
                _('Negative game-point total brought back to 0.'),
            )

        return PointAdjustment(
            mp=match_points,
            gp=game_points,
            explanation=' '.join(explanations),
        )

    @staticmethod
    def _own_board_game_points(team: 'Team', round_: int) -> float | None:
        """The team's own board game points for the round, before any
        adjustment. ``None`` when it didn't play a match that round.

        Deliberately reads the raw ``game_points`` and not
        ``effective_game_points``: the latter folds this very adjustment
        back in."""
        team_board = _FfeTeamCupRuleSet._team_round_match(team, round_)
        if team_board is None:
            return None
        a_points, b_points = team_board.game_points
        return (
            a_points if team_board.stored_team_board.team_a_id == team.id else b_points
        )

    @staticmethod
    def _forfeit_loss_penalty(team: 'Team', round_: int) -> 'PointAdjustment | None':
        """Art. 5.3.1: a game lost by sporting forfeit counts -1 "si une
        partie a été effectivement jouée sur l'un des échiquiers suivant
        l'échiquier concerné", and 0 otherwise."""
        rows = _round_breakdown(team, round_)
        played_indexes = [index for index, _forfeited, played in rows if played]
        if not played_indexes:
            return None
        last_played = max(played_indexes)
        count = sum(
            1 for index, forfeited, _played in rows if forfeited and index < last_played
        )
        if not count:
            return None
        return PointAdjustment(
            gp=-float(count),
            explanation=ngettext(
                '{n} board forfeited above a board on which a game was '
                'played, counted as -1.',
                '{n} boards forfeited above a board on which a game was '
                'played, counted as -1 each.',
                count,
            ).format(n=count),
        )

    @override
    def validate_config(self, values: dict[str, Any]) -> dict[str, str]:
        return {}
