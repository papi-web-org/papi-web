"""Colour policy for knock-out pairings."""

import random
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, cast

from common.i18n import _
from data.pairings.settings import PairingSetting
from utils.enum import BoardColor

if TYPE_CHECKING:
    from data.tournament import Tournament
    from web.utils import SelectOption


class KnockoutColourRule(StrEnum):
    ALTERNATE = 'ALTERNATE'
    HIGHER_SEED_WHITE = 'HIGHER_SEED_WHITE'
    DRAW_LOTS = 'DRAW_LOTS'


class KnockoutColourRuleSetting(PairingSetting[KnockoutColourRule]):
    """How a knock-out match's colours are decided."""

    @staticmethod
    def static_id() -> str:
        return 'KNOCKOUT_COLOUR_RULE'

    @staticmethod
    def static_name() -> str:
        return _('Colour assignment')

    @property
    def template_path(self) -> str:
        return '/admin/pairings/settings/knockout_colour_rule.html'

    def tooltip_representation(self, value: KnockoutColourRule) -> str | None:
        if value == KnockoutColourRule.ALTERNATE:
            return None
        option = self.options.get(value.value)
        return option.name if option is not None else None

    def from_form_data(self, data: dict[str, str]) -> KnockoutColourRule:
        return KnockoutColourRule(data[self.id])

    def to_form_data(self, object_: KnockoutColourRule) -> dict[str, str]:
        return {self.id: object_.value}

    def get_data_errors(
        self, tournament: 'Tournament', data: dict[str, str]
    ) -> dict[str, str]:
        return {}

    @classmethod
    def default_value(cls, tournament: 'Tournament') -> KnockoutColourRule:
        return KnockoutColourRule.ALTERNATE

    @classmethod
    def from_stored_value(cls, value: Any) -> KnockoutColourRule:
        return KnockoutColourRule(value)

    @classmethod
    def to_stored_value(cls, object_: KnockoutColourRule) -> Any:
        return object_.value

    @property
    def options(self) -> 'dict[str, SelectOption]':
        from web.utils import SelectOption

        return {
            KnockoutColourRule.ALTERNATE.value: SelectOption(
                _('Alternate colours'),
                _(
                    'Each side takes the opposite colour to its previous '
                    'round; when an upset makes two clash, the higher seed '
                    'alternates and the lower seed takes what is left. For a '
                    'team, this alternates which team is board-one White.'
                ),
            ),
            KnockoutColourRule.HIGHER_SEED_WHITE.value: SelectOption(
                _('Higher seed plays White'),
                _(
                    'The stronger seed takes White in every match (for a team, '
                    'board-one White).'
                ),
            ),
            KnockoutColourRule.DRAW_LOTS.value: SelectOption(
                _('Drawing of lots'),
                _('Colours are drawn at random for each match.'),
            ),
        }


class _KnockoutColourHost(Protocol):
    def _teams_for_tournament(self, tournament: 'Tournament') -> list[Any]: ...


class KnockoutColourMixin:
    """Colour assignment shared by all knock-out engines."""

    def _colour_host(self) -> _KnockoutColourHost:
        return cast(_KnockoutColourHost, self)

    @staticmethod
    def _colour_order(
        rule: 'KnockoutColourRule',
        round_: int,
        index: int,
        high: int,
        low: int,
        high_previous: 'BoardColor | None',
        low_previous: 'BoardColor | None',
    ) -> tuple[int, int]:
        if rule == KnockoutColourRule.DRAW_LOTS:
            return (high, low) if random.choice((True, False)) else (low, high)
        if rule == KnockoutColourRule.HIGHER_SEED_WHITE:
            return high, low
        if round_ <= 1:
            return (high, low) if index % 2 == 0 else (low, high)
        if high_previous is not None:
            return (high, low) if high_previous == BoardColor.BLACK else (low, high)
        if low_previous is not None:
            return (low, high) if low_previous == BoardColor.BLACK else (high, low)
        return high, low

    def _apply_colours(
        self,
        tournament: 'Tournament',
        round_: int,
        pairs: list[tuple[int, int | None]],
        stronger_first,
        previous_colour,
    ) -> list[tuple[int, int | None]]:
        """Reorder each contested pair as ``(white, black)`` per the rule."""
        rule = KnockoutColourRuleSetting.get_value(tournament)
        result: list[tuple[int, int | None]] = []
        for index, (a_id, b_id) in enumerate(pairs):
            if b_id is None:
                result.append((a_id, None))
                continue
            high, low = stronger_first(tournament, a_id, b_id)
            result.append(
                self._colour_order(
                    rule,
                    round_,
                    index,
                    high,
                    low,
                    previous_colour(tournament, high, round_),
                    previous_colour(tournament, low, round_),
                )
            )
        return result

    def _coloured_player_pairs(
        self,
        tournament: 'Tournament',
        round_: int,
        pairs: list[tuple[int, int | None]],
    ) -> list[tuple[int, int | None]]:
        return self._apply_colours(
            tournament,
            round_,
            pairs,
            self._stronger_players,
            self._previous_player_colour,
        )

    @staticmethod
    def _stronger_players(
        tournament: 'Tournament', a_id: int, b_id: int
    ) -> tuple[int, int]:
        players = tournament.tournament_players_by_id
        a, b = players.get(a_id), players.get(b_id)
        if a is None or b is None:
            return a_id, b_id
        if b.starting_rank_sort_key < a.starting_rank_sort_key:
            return b_id, a_id
        return a_id, b_id

    @staticmethod
    def _previous_player_colour(
        tournament: 'Tournament', player_id: int, round_: int
    ) -> 'BoardColor | None':
        player = tournament.tournament_players_by_id.get(player_id)
        if player is None:
            return None
        for previous in range(round_ - 1, 0, -1):
            pairing = player.pairings.get(previous)
            if (
                pairing is not None
                and pairing.opponent_id is not None
                and pairing.color is not None
            ):
                return pairing.color
        return None

    def _coloured_team_pairs(
        self,
        tournament: 'Tournament',
        round_: int,
        pairs: list[tuple[int, int | None]],
    ) -> list[tuple[int, int | None]]:
        ordered = self._apply_colours(
            tournament,
            round_,
            pairs,
            self._stronger_teams,
            self._previous_team_colour,
        )
        if self._team_a_is_board_one_white(tournament):
            return ordered
        return [(w, b) if b is None else (b, w) for w, b in ordered]

    def _stronger_teams(
        self, tournament: 'Tournament', a_id: int, b_id: int
    ) -> tuple[int, int]:
        order = [
            team.id for team in self._colour_host()._teams_for_tournament(tournament)
        ]
        rank_a = order.index(a_id) if a_id in order else len(order)
        rank_b = order.index(b_id) if b_id in order else len(order)
        return (a_id, b_id) if rank_a <= rank_b else (b_id, a_id)

    def _previous_team_colour(
        self, tournament: 'Tournament', team_id: int, round_: int
    ) -> 'BoardColor | None':
        team_a_white = self._team_a_is_board_one_white(tournament)
        for previous in range(round_ - 1, 0, -1):
            for team_board in tournament.team_boards_by_round.get(previous, []):
                stb = team_board.stored_team_board
                if stb.team_b_id is None:
                    continue
                if team_id == stb.team_a_id:
                    is_team_a = True
                elif team_id == stb.team_b_id:
                    is_team_a = False
                else:
                    continue
                white = team_a_white if is_team_a else not team_a_white
                return BoardColor.WHITE if white else BoardColor.BLACK
        return None

    @staticmethod
    def _team_a_is_board_one_white(tournament: 'Tournament') -> bool:
        pattern = tournament.color_pattern or ''
        return pattern[0] == BoardColor.WHITE.value if pattern else True
