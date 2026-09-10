"""Shared single-elimination bracket resolution for knock-out engines.

This module holds the bracket algorithm that is the same for individual and
team knock-outs: deriving later-round slots from feeder winners, preserving
structural byes in grouped brackets, building render descriptors, and collecting
round winners/losers. Concrete engines provide the participant-specific seams.
"""

from typing import TYPE_CHECKING, Protocol, cast

from common.i18n import _
from data.pairings.knockout_helpers import bracket as knockout_bracket
from data.pairings.knockout_helpers.third_place import (
    SingleEliminationThirdPlaceMixin,
)

if TYPE_CHECKING:
    from data.pairings.knockout_helpers.layout import MatchDescriptor
    from data.tournament import Tournament


def single_elimination_round_name(round_: int, rounds: int) -> str:
    """The stage name of a single-elimination round."""
    from_end = rounds - round_
    if from_end <= 0:
        return _('Final')
    if from_end == 1:
        return _('Semifinals')
    if from_end == 2:
        return _('Quarterfinals')
    return _('Round of {count}').format(count=2 ** (from_end + 1))


class _SingleEliminationBracketHost(Protocol):
    def _grouped_leaves(self, tournament: 'Tournament') -> list[int | None] | None: ...

    def _single_elim_first_round_pairs(
        self, tournament: 'Tournament'
    ) -> list[tuple[int | None, int | None]]: ...

    def _single_elim_pair_winner(
        self,
        tournament: 'Tournament',
        round_: int,
        a_id: int | None,
        b_id: int | None,
    ) -> int | None: ...


class SingleEliminationBracketMixin(SingleEliminationThirdPlaceMixin):
    """Single-elimination bracket graph shared by player and team engines."""

    def _single_elim_host(self) -> _SingleEliminationBracketHost:
        return cast(_SingleEliminationBracketHost, self)

    def _single_elim_bracket_pairs(
        self, tournament: 'Tournament', round_: int
    ) -> list[tuple[int | None, int | None]]:
        """The matches of *round_* in bracket order."""
        host = self._single_elim_host()
        if round_ <= 1:
            return host._single_elim_first_round_pairs(tournament)
        winners = self._single_elim_round_winner_ids(tournament, round_ - 1)
        if winners is None:
            return []
        pairs: list[tuple[int | None, int | None]] = knockout_bracket.advance_pairs(
            winners
        )
        return pairs + self._third_place_pairs(
            tournament, stage=round_, final_stage=tournament.rounds
        )

    def _single_elim_round_loser_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int] | None:
        """The losers of *round_*'s contested matches, in bracket order."""
        winners = self._single_elim_round_winner_ids(tournament, round_)
        if winners is None:
            return None
        losers: list[int] = []
        for (a_id, b_id), winner in zip(
            self._single_elim_bracket_pairs(tournament, round_), winners
        ):
            if a_id is None or b_id is None or winner is None:
                continue
            losers.append(b_id if winner == a_id else a_id)
        return losers

    def _single_elim_slot(
        self, tournament: 'Tournament', round_: int, index: int, cache: dict
    ) -> tuple[int | None, int | None, int | None]:
        """``(a_id, b_id, winner_id)`` of a structural bracket match."""
        host = self._single_elim_host()
        key = (round_, index)
        if key in cache:
            return cache[key]
        cache[key] = (None, None, None)  # guard against re-entry
        if '_leaves' not in cache:
            cache['_leaves'] = host._grouped_leaves(tournament)
        leaves = cache['_leaves']
        if round_ <= 1:
            pairs = host._single_elim_first_round_pairs(tournament)
            a_id, b_id = pairs[index] if index < len(pairs) else (None, None)
        else:
            _, _, a_id = self._single_elim_slot(
                tournament, round_ - 1, 2 * index, cache
            )
            _, _, b_id = self._single_elim_slot(
                tournament, round_ - 1, 2 * index + 1, cache
            )
        if leaves is not None:
            a_absent = self._slot_all_virtual(leaves, round_ - 1, 2 * index)
            b_absent = self._slot_all_virtual(leaves, round_ - 1, 2 * index + 1)
            if a_absent and b_absent:
                winner = None
            elif b_absent:
                winner = a_id
            elif a_absent:
                winner = b_id
            elif a_id is not None and b_id is not None:
                winner = host._single_elim_pair_winner(tournament, round_, a_id, b_id)
            else:
                winner = None
        elif round_ <= 1:
            winner = host._single_elim_pair_winner(tournament, round_, a_id, b_id)
        elif a_id is not None and b_id is not None:
            winner = host._single_elim_pair_winner(tournament, round_, a_id, b_id)
        else:
            winner = None
        cache[key] = (a_id, b_id, winner)
        return cache[key]

    @staticmethod
    def _slot_all_virtual(leaves: list[int | None], level: int, index: int) -> bool:
        """Whether a node's whole leaf subtree is virtual."""
        span = 1 << level
        return all(leaf is None for leaf in leaves[index * span : (index + 1) * span])

    def bracket_match_descriptors(
        self, tournament: 'Tournament'
    ) -> list['MatchDescriptor']:
        """The whole single-elimination bracket as render-ready descriptors."""
        from data.pairings.knockout_helpers.layout import MatchDescriptor

        rounds = tournament.rounds
        bracket_size = 2**rounds
        cache: dict = {}
        descriptors: list[MatchDescriptor] = []
        for round_ in range(1, rounds + 1):
            for index in range(bracket_size // (2**round_)):
                a_id, b_id, winner = self._single_elim_slot(
                    tournament, round_, index, cache
                )
                descriptors.append(
                    MatchDescriptor(
                        id=f'R{round_}.{index}',
                        section='main',
                        column=round_ - 1,
                        round_name=single_elimination_round_name(round_, rounds),
                        app_round=round_,
                        a_id=a_id,
                        b_id=b_id,
                        winner_id=winner,
                        source_top=(
                            f'R{round_ - 1}.{2 * index}' if round_ > 1 else None
                        ),
                        source_bottom=(
                            f'R{round_ - 1}.{2 * index + 1}' if round_ > 1 else None
                        ),
                    )
                )
        third_place = self._third_place_match_descriptor(
            tournament, final_stage=rounds, app_round=rounds, cache=cache
        )
        if third_place is not None:
            descriptors.append(third_place)
        return descriptors

    def _single_elim_round_winner_ids(
        self, tournament: 'Tournament', round_: int
    ) -> list[int | None] | None:
        """The winners of *round_*, in bracket order."""
        pairs = self._single_elim_bracket_pairs(tournament, round_)
        if round_ > 1 and not pairs:
            return None
        winners: list[int | None] = []
        host = self._single_elim_host()
        for a_id, b_id in pairs:
            winner = host._single_elim_pair_winner(tournament, round_, a_id, b_id)
            if winner is None and b_id is not None:
                return None
            winners.append(winner)
        return winners
