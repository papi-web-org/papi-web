"""Bracket arithmetic for a double-elimination knock-out.

Pure, structural description of the match graph: every match names its two
sources (a seed, or the winner/loser of an earlier match) and the app round
it is played in. No tournament, database, or framework types -- the engine
resolves sources against real results and this module says who plays whom.

A double elimination of ``n`` participants runs two brackets. The winners'
bracket (upper) is an ordinary single-elimination over ``k = ceil(log2 n)``
rounds. Every player who loses a winners'-bracket game drops into the
losers' bracket (lower) instead of being eliminated; a second loss -- there
or in the winners' bracket -- knocks them out. The two bracket champions
meet in the grand final. Because the winners'-bracket champion has never
lost, if the losers'-bracket champion beats them there the score is one loss
each: an optional reset game (``with_reset``) is then played to settle it.

Rounds interleave. Winners' round ``r`` is played in app round ``1`` (for
``r == 1``) or ``2(r - 1)``; losers' round ``j`` (``1..2(k-1)``) in app round
``j + 1``; the grand final in ``2k`` and its reset in ``2k + 1``. So a single
app round can hold both a winners' and a losers' match set, the way the
third-place match shares the single-elimination final round.

Losers' rounds alternate *minor* (losers'-bracket survivors play each other)
and *major* (survivors meet the fresh winners'-bracket dropouts of the round
above). The dropouts enter a major round in reversed slot order, so two
players who just met in the winners' bracket do not immediately meet again.
"""

from dataclasses import dataclass

from data.pairings.knockout_helpers import bracket as knockout_bracket

WINNERS = 'W'
LOSERS = 'L'
GRAND_FINAL = 'GF'
GRAND_FINAL_RESET = 'GFR'


@dataclass(frozen=True)
class Seed:
    """A source that is the participant seeded ``seed`` (``1`` is strongest).
    A seed greater than the participant count is virtual -- the opponent
    gets a bye."""

    seed: int


@dataclass(frozen=True)
class WinnerOf:
    """A source that is the winner of an earlier match."""

    match_id: str


@dataclass(frozen=True)
class LoserOf:
    """A source that is the loser of an earlier match (its drop into the
    losers' bracket). Absent when that match was a bye -- nobody lost it."""

    match_id: str


Source = Seed | WinnerOf | LoserOf


@dataclass(frozen=True)
class Match:
    """One scheduled match: its stable id, the app round it is played in,
    which bracket it belongs to, and its two participant sources."""

    id: str
    round: int
    bracket: str
    a: Source
    b: Source


def _winners_round_app(round_: int) -> int:
    """The app round a winners'-bracket round is played in."""
    return 1 if round_ == 1 else 2 * (round_ - 1)


def schedule(participant_count: int, *, with_reset: bool = False) -> list[Match]:
    """The full match graph for a double elimination of *participant_count*.

    Matches are returned in a stable order (winners' bracket, then losers'
    bracket, then the grand final and its optional reset). Byes are not
    resolved here: a :class:`Seed` beyond the participant count, or a
    :class:`LoserOf` a bye match, is left in place for the engine to collapse
    when it resolves sources against real results.
    """
    if participant_count < 2:
        return []

    size = knockout_bracket.bracket_size(participant_count)
    rounds = knockout_bracket.round_count(participant_count)
    matches: list[Match] = []

    # --- Winners' bracket: an ordinary single elimination. ------------------
    order = knockout_bracket.seed_order(size)
    winners_ids_by_round: dict[int, list[str]] = {}
    round_ids: list[str] = []
    for i in range(size // 2):
        high, low = sorted((order[2 * i], order[2 * i + 1]))
        match_id = f'W1.{i}'
        matches.append(Match(match_id, 1, WINNERS, Seed(high), Seed(low)))
        round_ids.append(match_id)
    winners_ids_by_round[1] = round_ids

    for round_ in range(2, rounds + 1):
        app = _winners_round_app(round_)
        previous = winners_ids_by_round[round_ - 1]
        round_ids = []
        for i in range(len(previous) // 2):
            match_id = f'W{round_}.{i}'
            matches.append(
                Match(
                    match_id,
                    app,
                    WINNERS,
                    WinnerOf(previous[2 * i]),
                    WinnerOf(previous[2 * i + 1]),
                )
            )
            round_ids.append(match_id)
        winners_ids_by_round[round_] = round_ids
    winners_final_id = winners_ids_by_round[rounds][0]

    # --- Losers' bracket: minor/major rounds fed by winners' dropouts. ------
    losers_previous: list[str] = []
    for j in range(1, 2 * (rounds - 1) + 1):
        app = j + 1
        round_ids = []
        if j == 1:
            # First minor round: the winners'-bracket round-1 losers pair up.
            first_losers = winners_ids_by_round[1]
            for i in range(len(first_losers) // 2):
                match_id = f'L1.{i}'
                matches.append(
                    Match(
                        match_id,
                        app,
                        LOSERS,
                        LoserOf(first_losers[2 * i]),
                        LoserOf(first_losers[2 * i + 1]),
                    )
                )
                round_ids.append(match_id)
        elif j % 2 == 1:
            # Later minor round: losers'-bracket survivors play each other.
            for i in range(len(losers_previous) // 2):
                match_id = f'L{j}.{i}'
                matches.append(
                    Match(
                        match_id,
                        app,
                        LOSERS,
                        WinnerOf(losers_previous[2 * i]),
                        WinnerOf(losers_previous[2 * i + 1]),
                    )
                )
                round_ids.append(match_id)
        else:
            # Major round: survivors meet the winners'-bracket round-(t+1)
            # dropouts, entering in reversed slot order to avoid a rematch.
            dropout_round = j // 2 + 1
            dropouts = list(reversed(winners_ids_by_round[dropout_round]))
            for i in range(len(losers_previous)):
                match_id = f'L{j}.{i}'
                matches.append(
                    Match(
                        match_id,
                        app,
                        LOSERS,
                        WinnerOf(losers_previous[i]),
                        LoserOf(dropouts[i]),
                    )
                )
                round_ids.append(match_id)
        losers_previous = round_ids
    # Two participants play a single winners' match, so the losers' bracket is
    # empty: the grand final is that match's rematch, its second seat held by
    # the player who lost it.
    losers_final: Source = (
        WinnerOf(losers_previous[0]) if losers_previous else LoserOf(winners_final_id)
    )

    # --- Grand final (and its optional reset). ------------------------------
    matches.append(
        Match(
            GRAND_FINAL,
            2 * rounds,
            GRAND_FINAL,
            WinnerOf(winners_final_id),
            losers_final,
        )
    )
    if with_reset:
        matches.append(
            Match(
                GRAND_FINAL_RESET,
                2 * rounds + 1,
                GRAND_FINAL_RESET,
                WinnerOf(winners_final_id),
                losers_final,
            )
        )
    return matches


def round_count(participant_count: int, *, with_reset: bool = False) -> int:
    """Number of app rounds a double elimination spans. ``2k`` for the grand
    final, one more when the reset game is offered."""
    if participant_count < 2:
        return 0
    base = 2 * knockout_bracket.round_count(participant_count)
    return base + 1 if with_reset else base


def matches_for_round(matches: list[Match], round_: int) -> list[Match]:
    """The scheduled matches played in app round *round_*, in bracket order
    (winners' before losers')."""
    return [match for match in matches if match.round == round_]
