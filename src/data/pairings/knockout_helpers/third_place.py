"""Third-place playoff helpers for single-elimination knock-outs."""

from typing import TYPE_CHECKING, Protocol, cast

from common.i18n import _

if TYPE_CHECKING:
    from data.pairings.knockout_helpers.layout import MatchDescriptor
    from data.tournament import Tournament


THIRD_PLACE_MATCH_ID = 'TP.0'
THIRD_PLACE_SECTION = 'third'


def match_loser_of(
    a_id: int | None, b_id: int | None, winner_id: int | None
) -> int | None:
    """The loser of a decided match, or ``None`` while undecided / a bye."""
    if winner_id is None or a_id is None or b_id is None:
        return None
    return a_id if winner_id == b_id else b_id


class _SingleEliminationThirdPlaceHost(Protocol):
    def _single_elim_third_place_enabled(self, tournament: 'Tournament') -> bool: ...

    def _single_elim_round_loser_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int] | None: ...

    def _single_elim_slot(
        self, tournament: 'Tournament', round_: int, index: int, cache: dict
    ) -> tuple[int | None, int | None, int | None]: ...

    def _single_elim_pair_winner(
        self,
        tournament: 'Tournament',
        round_: int,
        a_id: int | None,
        b_id: int | None,
    ) -> int | None: ...


class SingleEliminationThirdPlaceMixin:
    """Bronze-match behavior shared by one-game and two-game knock-outs."""

    def _third_place_host(self) -> _SingleEliminationThirdPlaceHost:
        return cast(_SingleEliminationThirdPlaceHost, self)

    @staticmethod
    def _third_place_label() -> str:
        return _('Third-place playoff')

    def _third_place_pairs(
        self,
        tournament: 'Tournament',
        *,
        stage: int,
        final_stage: int,
    ) -> list[tuple[int, int]]:
        """The bronze match in the final stage, when configured and known."""
        if stage < 2 or stage != final_stage:
            return []
        host = self._third_place_host()
        if not host._single_elim_third_place_enabled(tournament):
            return []
        losers = host._single_elim_round_loser_ids(tournament, stage - 1)
        if losers is None or len(losers) != 2:
            return []
        return [(losers[0], losers[1])]

    def _third_place_match_descriptor(
        self,
        tournament: 'Tournament',
        *,
        final_stage: int,
        app_round: int,
        cache: dict,
    ) -> 'MatchDescriptor | None':
        """The render descriptor for the bronze match, if it is enabled."""
        host = self._third_place_host()
        if final_stage < 2 or not host._single_elim_third_place_enabled(tournament):
            return None

        from data.pairings.knockout_helpers.layout import MatchDescriptor

        a0, b0, w0 = host._single_elim_slot(tournament, final_stage - 1, 0, cache)
        a1, b1, w1 = host._single_elim_slot(tournament, final_stage - 1, 1, cache)
        loser0 = match_loser_of(a0, b0, w0)
        loser1 = match_loser_of(a1, b1, w1)
        winner = (
            host._single_elim_pair_winner(tournament, final_stage, loser0, loser1)
            if loser0 is not None and loser1 is not None
            else None
        )
        return MatchDescriptor(
            id=THIRD_PLACE_MATCH_ID,
            section=THIRD_PLACE_SECTION,
            column=0,
            round_name=self._third_place_label(),
            app_round=app_round,
            a_id=loser0,
            b_id=loser1,
            winner_id=winner,
            source_top=None,
            source_bottom=None,
        )

    def _third_place_ranking_value(
        self,
        tournament: 'Tournament',
        participant_id: int,
        *,
        final_stage: int,
        after_stage: int,
    ) -> float | None:
        """The bronze winner's placement value, once the final stage is done."""
        if after_stage < final_stage:
            return None
        pairs = self._third_place_pairs(
            tournament, stage=final_stage, final_stage=final_stage
        )
        if not pairs or participant_id not in pairs[0]:
            return None
        winner = self._third_place_host()._single_elim_pair_winner(
            tournament, final_stage, *pairs[0]
        )
        if winner == participant_id:
            return float(final_stage) - 0.5
        return None

    def _is_third_place_participant_pair(
        self,
        tournament: 'Tournament',
        participant_ids: set[int],
        *,
        stage: int,
        final_stage: int,
    ) -> bool:
        """Whether these participants are the configured bronze match."""
        if not participant_ids:
            return False
        pairs = self._third_place_pairs(
            tournament, stage=stage, final_stage=final_stage
        )
        return bool(pairs) and participant_ids == set(pairs[0])
