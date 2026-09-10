"""Prohibited pairings for Swiss — members that must not meet.

The grouping keys come from :class:`~data.pairing_dimensions.PairingDimension`
(``club`` / ``federation`` / affiliation, plus plugin dimensions). This module
turns those buckets into forbidden pairs and picks the soft-relaxation cutoff for
a round. A knock-out reuses the same dimensions for a different purpose (seeding
groups), so the dimension type itself lives in :mod:`data.pairing_dimensions`.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class RoundProhibitedPairingGroup:
    """A prohibited-pairing group a plugin contributes for a specific round
    (typically results-based). ``name`` is the human label shown in the
    prohibited-pairings modal; ``member_ids`` are team ids in a team
    tournament, player ids otherwise."""

    name: str
    is_hard: bool
    member_ids: list[int]


# A prohibited pair is the unordered pair of the two members (player ids
# or team ids) that must not meet. ``Pair = frozenset({a, b})``.
Pair = frozenset


def resolve_soft_protect_rank(
    thresholds: list[int],
    feasible: Callable[[int], bool],
) -> tuple[int | None, bool]:
    """Pick the soft-relaxation cutoff ``N`` for this round — *protect the
    top N members*.

    Hard prohibitions are always enforced (baked into ``feasible``, which
    the caller closes over). A member whose standing rank is ``<= N`` is
    protected: it keeps *all* its soft separations. A soft separation is
    relaxed only when **both** its members rank below ``N`` — so any
    unavoidable club/league clash lands on two bottom-of-the-table
    members, on a low board, never on a strong one.

    ``thresholds`` are the distinct candidate cutoffs (the standing ranks
    of the members that appear in soft groups, sorted ascending; 1 = top).
    ``feasible(N)`` answers "can bbpPairings pair the field with the top N
    protected?" — monotone *decreasing* in ``N`` (a larger protected set
    only adds constraints), so we **bisect for the largest feasible N**.

    - Protecting everyone feasible → protect everyone (no clash forced).
    - Even protecting none infeasible → the hard constraints alone can't be
      paired → ``hard_infeasible`` (caller surfaces an error, never
      silently violates a hard prohibition).
    - No soft members at all → ``(None, False)``.

    Returns ``(protect_rank, hard_infeasible)``. ``protect_rank`` is the
    chosen cutoff, ``0`` to protect no one (all soft relaxed), or ``None``
    when there are no soft members to relax.
    """
    if not thresholds:
        return None, False
    if feasible(thresholds[-1]):
        return thresholds[-1], False
    if not feasible(0):
        return None, True
    best = 0
    low, high = 0, len(thresholds) - 1
    while low <= high:
        mid = (low + high) // 2
        if feasible(thresholds[mid]):
            best = thresholds[mid]
            low = mid + 1
        else:
            high = mid - 1
    return best, False


def expand_groups_to_pairs(
    member_ids: Iterable[int],
) -> list['frozenset[int]']:
    """Every unordered pair within a prohibited group (a group of N members
    forbids all N·(N−1)/2 internal pairings)."""
    members = list(member_ids)
    return [
        frozenset((members[i], members[j]))
        for i in range(len(members))
        for j in range(i + 1, len(members))
    ]
