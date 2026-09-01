"""Bracket arithmetic for a single-elimination (knock-out) tournament.

Pure functions over seeds and abstract winner tokens: no tournament, no
database, no framework types. The engine seeds the participants, reads the
winners of a finished round from the results, and asks this module who
plays whom next. Keeping the arithmetic here makes it unit-testable on its
own and keeps the engine about persistence.

A knock-out of ``n`` participants is played over ``ceil(log2(n))`` rounds.
Participants are seeded ``1..n`` by strength (seed 1 is the strongest). The
field is padded up to the next power of two ``m`` with virtual participants
taking the lowest seeds; a real participant drawn against a virtual one
gets a bye and advances. Seeds are laid out so the two strongest meet only
in the final: the standard recursion pairs each seed ``s`` in a bracket of
size ``m`` against ``m + 1 - s``.
"""

from math import ceil, log2


def round_count(participant_count: int) -> int:
    """Number of rounds needed to reduce *participant_count* to one winner.

    ``ceil(log2(n))`` — one round per halving. ``0`` for fewer than two
    participants, where there is nothing to play.
    """
    if participant_count < 2:
        return 0
    return ceil(log2(participant_count))


def bracket_size(participant_count: int) -> int:
    """The smallest power of two at least as large as *participant_count*.

    The size of the round-one bracket once padded with virtual seeds.
    """
    if participant_count < 2:
        return 0
    return 2 ** round_count(participant_count)


def seed_order(size: int) -> list[int]:
    """Seeds ``1..size`` in bracket-slot order for a power-of-two *size*.

    Reading the result two slots at a time gives the round-one matches;
    the layout guarantees seeds 1 and 2 fall in opposite halves and can
    only meet in the final. Built by the standard doubling recursion: a
    bracket of size ``2m`` expands each seed ``s`` of the size-``m``
    bracket into the pair ``(s, 2m + 1 - s)``.
    """
    if size < 1 or (size & (size - 1)) != 0:
        raise ValueError(f'size must be a power of two, got {size}')
    seeds = [1]
    while len(seeds) < size:
        current = 2 * len(seeds)
        seeds = [s for seed in seeds for s in (seed, current + 1 - seed)]
    return seeds


def first_round_pairs(participant_count: int) -> list[tuple[int, int | None]]:
    """Round-one matches as ``(top_seed, bottom_seed)`` pairs.

    ``bottom_seed`` is ``None`` when the slot falls on a virtual seed
    (greater than *participant_count*): the top seed gets a bye. Because
    the field is padded to the *next* power of two, the number of byes is
    strictly fewer than half the bracket, so a bye never faces a bye — the
    ``None`` is always the second element.
    """
    size = bracket_size(participant_count)
    order = seed_order(size)
    pairs: list[tuple[int, int | None]] = []
    for i in range(0, size, 2):
        high, low = order[i], order[i + 1]
        # The stronger (smaller) seed leads; virtual seeds sit lowest, so
        # a bye always lands on the second slot.
        if high > low:
            high, low = low, high
        pairs.append((high, low if low <= participant_count else None))
    return pairs


def advance_pairs[T](winners: list[T]) -> list[tuple[T, T]]:
    """Next-round matches from an in-order list of this round's *winners*.

    Winners must be given in bracket order — match ``i``'s winner at index
    ``i`` — so adjacent winners meet: ``(winners[0], winners[1])``,
    ``(winners[2], winners[3])``, and so on. The count must be an even
    power of two down to the two finalists.
    """
    count = len(winners)
    if count < 2 or (count & (count - 1)) != 0:
        raise ValueError(f'winner count must be a power of two >= 2, got {count}')
    return [(winners[i], winners[i + 1]) for i in range(0, count, 2)]
