"""Grouped seeding for a knock-out.

Pure bracket arithmetic — no tournament or database types. Given the groups (in
group-strength order, each a list of member ids in within-group seed order), lay
out the round-one seat order so every group is its own sub-bracket: members play
within the group first, groups meet later, and the two strongest groups can only
meet in the final.

Padding is the ordinary knock-out bye mechanism at two levels. Every group is
padded to a common size ``M`` (the next power of two at least as large as the
biggest group) with virtual members, and the group count is padded to ``K`` (the
next power of two) with phantom, all-virtual groups. The result is a single
``K * M`` power-of-two bracket, so the standard engine seats it; a ``None`` slot
is a virtual (bye).
"""

from typing import TYPE_CHECKING, Any, Protocol, cast

from common.i18n import _
from data.pairings.knockout_helpers.bracket import seed_order
from data.pairings.settings import PairingSetting

if TYPE_CHECKING:
    from data.tournament import Tournament


def _next_pow2(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


def form_groups(members: list[tuple[int, str | None]]) -> list[list[int]]:
    """Bucket *members* — ``(id, group_key)`` in natural seed order, strongest
    first — into groups, each ranked by its strongest member (its first
    appearance). Members with ``group_key is None`` are pooled into a single
    "unaffiliated" group, ranked by first appearance like any other."""
    unaffiliated = object()
    buckets: dict[object, list[int]] = {}
    order: list[object] = []
    for member_id, key in members:
        bucket_key: object = key if key is not None else unaffiliated
        if bucket_key not in buckets:
            buckets[bucket_key] = []
            order.append(bucket_key)
        buckets[bucket_key].append(member_id)
    return [buckets[key] for key in order]


def grouped_dimensions(groups: list[list[int]]) -> tuple[int, int]:
    """``(K, M)`` — the padded group count and common group size (both powers of
    two), or ``(0, 0)`` for no groups."""
    if not groups:
        return 0, 0
    return _next_pow2(len(groups)), _next_pow2(max(len(group) for group in groups))


def grouped_round_count(groups: list[list[int]]) -> int:
    """Rounds the grouped bracket spans: ``log2(K) + log2(M)``."""
    k, m = grouped_dimensions(groups)
    return (k * m).bit_length() - 1 if k and m else 0


def grouped_leaves(groups: list[list[int]]) -> list[int | None]:
    """The round-one seat order for the grouped bracket. Consecutive pairs are
    the round-one matches; ``None`` marks a virtual (bye) slot. Length ``K * M``.
    """
    k, m = grouped_dimensions(groups)
    if not k:
        return []
    group_count = len(groups)
    outer = seed_order(k)
    inner = seed_order(m)
    leaves: list[int | None] = []
    for block in outer:
        group = groups[block - 1] if block - 1 < group_count else []
        for local in inner:
            leaves.append(group[local - 1] if local - 1 < len(group) else None)
    return leaves


class KnockoutGroupingSetting(PairingSetting['str | None']):
    """Optional seeding by a pairing dimension."""

    _NONE = ''

    @staticmethod
    def static_id() -> str:
        return 'KNOCKOUT_GROUPING'

    @staticmethod
    def static_name() -> str:
        return _('Group by')

    @property
    def template_path(self) -> str:
        return '/admin/pairings/settings/knockout_grouping.html'

    def tooltip_representation(self, value: 'str | None') -> str | None:
        return _('Grouped') if value else None

    def from_form_data(self, data: dict[str, str]) -> 'str | None':
        return data.get(self.id) or None

    def to_form_data(self, object_: 'str | None') -> dict[str, str]:
        return {self.id: object_ or self._NONE}

    def get_data_errors(
        self, tournament: 'Tournament', data: dict[str, str]
    ) -> dict[str, str]:
        return {}

    @classmethod
    def default_value(cls, tournament: 'Tournament') -> 'str | None':
        return None

    @classmethod
    def from_stored_value(cls, value: Any) -> 'str | None':
        return str(value) or None if value else None

    @classmethod
    def to_stored_value(cls, object_: 'str | None') -> Any:
        return object_ or None

    @classmethod
    def check_value(cls, tournament: 'Tournament', value: 'str | None') -> bool:
        if value is None:
            return True
        return any(
            dimension.id == value
            for dimension in tournament.prohibited_pairing_dimensions()
        )


class _KnockoutGroupingHost(Protocol):
    def _teams_for_tournament(self, tournament: 'Tournament') -> list[Any]: ...


class KnockoutGroupingMixin:
    """Optional group-aware seeding shared by every knock-out engine."""

    def _grouping_host(self) -> _KnockoutGroupingHost:
        return cast(_KnockoutGroupingHost, self)

    def _grouping_dimension(self, tournament: 'Tournament'):
        dimension_id = KnockoutGroupingSetting.get_value(tournament)
        if not dimension_id:
            return None
        for dimension in tournament.prohibited_pairing_dimensions():
            if dimension.id == dimension_id:
                return dimension
        return None

    def _grouping_members(
        self, tournament: 'Tournament', dimension
    ) -> list[tuple[int, str | None]]:
        """``(id, group_key)`` per participant in natural seed order."""
        if tournament.pairing_system.paired_by_team:
            entities: list = self._grouping_host()._teams_for_tournament(tournament)
        else:
            by_rank = tournament.tournament_players_by_starting_rank
            entities = [by_rank[rank] for rank in sorted(by_rank)]
        return [(entity.id, dimension.group_key(entity)) for entity in entities]

    def _grouped_leaves(self, tournament: 'Tournament') -> list[int | None] | None:
        """The grouped round-one seat order, or ``None`` when grouping is off."""
        dimension = self._grouping_dimension(tournament)
        if dimension is None:
            return None
        groups = form_groups(self._grouping_members(tournament, dimension))
        return grouped_leaves(groups)

    def _grouped_round_count(self, tournament: 'Tournament') -> int | None:
        dimension = self._grouping_dimension(tournament)
        if dimension is None:
            return None
        groups = form_groups(self._grouping_members(tournament, dimension))
        return grouped_round_count(groups)

    def grouping_preview(
        self, tournament: 'Tournament', dimension: Any
    ) -> dict[str, Any]:
        """A summary of what seeding by *dimension* would do to the bracket."""
        members = self._grouping_members(tournament, dimension)
        groups = form_groups(members)
        counts: dict[str, int] = {}
        order: list[str] = []
        for _member_id, key in members:
            label = key or ''
            if label not in counts:
                counts[label] = 0
                order.append(label)
            counts[label] += 1
        k, m = grouped_dimensions(groups)
        bracket_size = k * m
        players = len(members)
        return {
            'groups': [{'label': label, 'count': counts[label]} for label in order],
            'group_count': len(groups),
            'players': players,
            'bracket_size': bracket_size,
            'rounds': grouped_round_count(groups),
            'byes': bracket_size - players,
            'unaffiliated': counts.get('', 0),
            'blown_up': players > 0 and bracket_size > 2 * players,
        }
