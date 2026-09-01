"""Pairing dimensions — ways to bucket a tournament's members by affiliation.

A *dimension* buckets a tournament's members (players for an individual
tournament, teams for a team tournament) by some affiliation key. The same
buckets drive two features: in Swiss they are groups whose members must not be
paired together (prohibited pairings, see :mod:`data.prohibited_pairings`); in a
knock-out they can seed the bracket so a group plays itself before it meets
other groups. Core ships ``club`` / ``federation`` (individual) and
``team-group`` (team); plugins contribute more (e.g. a federation "ligue", a
school) via the ``get_prohibited_pairing_dimensions`` hook.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from common.i18n import _


@dataclass(frozen=True)
class PairingDimension:
    """A grouping rule. ``group_key`` returns the bucket key for a member
    (a player for individual tournaments, a team for team ones), or
    ``None`` when the member has no affiliation (kept ungrouped in Swiss;
    pooled into one "unaffiliated" group when seeding a knock-out)."""

    id: str
    label: str
    is_team: bool
    group_key: Callable[[Any], str | None]


def core_pairing_dimensions() -> list[PairingDimension]:
    return [
        PairingDimension(
            id='club',
            label=_('Club'),
            is_team=False,
            group_key=lambda player: player.club.name or None,
        ),
        PairingDimension(
            id='federation',
            label=_('Federation'),
            is_team=False,
            group_key=lambda player: player.federation.name or None,
        ),
        PairingDimension(
            id='team-group',
            label=_('Affiliation'),
            is_team=True,
            group_key=lambda team: team.group.name if team.group is not None else None,
        ),
        PairingDimension(
            id='team-federation',
            label=_('Federation'),
            is_team=True,
            group_key=lambda team: team.federation or None,
        ),
    ]
