from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

from litestar.plugins.htmx import HTMXRequest

from web.session import (
    SessionAdminCollectionShowDetails,
    SessionAdminCollectionViewMode,
)


class AdminCollectionViewMode(StrEnum):
    CARDS = 'cards'
    LIST = 'list'


@dataclass
class ComponentPlacement:
    component_id: str
    css_class: str = ''
    template: str | None = field(default=None, kw_only=True)


BADGE_GROUP_COLUMN_CELL_CLASS: str = 'collection-list-cell-badge-group'


def badge_group_column_width(cap: str = '22rem') -> str:
    """Width of a column holding a wrapping group of badges: its content's
    width, clamped at ``cap``. A track sizing function rather than a
    ``min-width``, which would need Chrome-only ``calc-size()``. Use with
    :data:`BADGE_GROUP_COLUMN_CELL_CLASS`."""
    return f'fit-content({cap})'


BADGE_GROUP_COLUMN_WIDTH: str = badge_group_column_width()

# Name column sharing a row with a badge column: both intrinsic, so grid
# widens them in equal parts. The minimum is a length, not ``min-content`` —
# ``text-truncate`` stops the name wrapping, so its min-content is its whole
# width and would pin the column.
NAME_COLUMN_WIDTH: str = 'minmax(8rem, auto)'
NAME_COLUMN_CELL_CLASS: str = 'collection-list-cell-name-first'


@dataclass
class ListColumn(ComponentPlacement):
    label: str = ''
    width: str = 'minmax(min-content, max-content)'
    header_class: str = ''
    cell_class: str = ''


@dataclass
class CardLayout:
    header: tuple[ComponentPlacement, ...]
    summary: tuple[ComponentPlacement, ...] = ()
    summary_class: str = ''
    body: tuple[ComponentPlacement, ...] = ()
    details: tuple[ComponentPlacement, ...] = ()
    footer: tuple[ComponentPlacement, ...] = ()


@dataclass
class ListLayout:
    columns: tuple[ListColumn, ...]
    details: tuple[ComponentPlacement, ...] = ()


@dataclass
class AdminCollectionSpec:
    key: str
    components_template: str
    card: CardLayout
    list: ListLayout
    item_id_attribute: str = 'id'
    reorder_input_name: str | None = None
    card_href_component: str | None = None
    row_href_component: str | None = None
    default_view_mode: AdminCollectionViewMode = AdminCollectionViewMode.LIST

    def item_id(self, item: Any) -> str:
        return str(getattr(item, self.item_id_attribute))

    def add_card_detail(
        self,
        placement: ComponentPlacement,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.card.details = _insert_placement(
            self.card.details, placement, before=before, after=after
        )

    def add_list_column(
        self,
        column: ListColumn,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.list.columns = _insert_placement(
            self.list.columns, column, before=before, after=after
        )

    def ensure_list_column(
        self,
        column: ListColumn,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Add a list column unless one with the same id already exists.

        Lets several plugins contribute to a single shared column."""
        if any(
            existing.component_id == column.component_id
            for existing in self.list.columns
        ):
            return
        self.add_list_column(column, before=before, after=after)

    def add_list_detail(
        self,
        placement: ComponentPlacement,
        *,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        self.list.details = _insert_placement(
            self.list.details, placement, before=before, after=after
        )


Placement = TypeVar('Placement', bound=ComponentPlacement)


def _insert_placement(
    placements: tuple[Placement, ...],
    placement: Placement,
    *,
    before: str | None,
    after: str | None,
) -> tuple[Placement, ...]:
    if before and after:
        raise ValueError('Specify either before or after, not both.')
    if any(existing.component_id == placement.component_id for existing in placements):
        raise ValueError(f'Duplicate collection component [{placement.component_id}].')

    reference = before or after
    if reference is None:
        return (*placements, placement)

    try:
        reference_index = next(
            index
            for index, existing in enumerate(placements)
            if existing.component_id == reference
        )
    except StopIteration as error:
        raise ValueError(f'Unknown collection component [{reference}].') from error

    insertion_index = reference_index if before else reference_index + 1
    return (
        *placements[:insertion_index],
        placement,
        *placements[insertion_index:],
    )


def resolve_admin_collection_view_mode(
    request: HTMXRequest, collection_key: str
) -> AdminCollectionViewMode:
    session_value = SessionAdminCollectionViewMode(request, collection_key)
    requested_mode = request.query_params.get('collection_view')
    try:
        requested_view_mode = (
            AdminCollectionViewMode(requested_mode)
            if isinstance(requested_mode, str)
            else None
        )
    except ValueError:
        requested_view_mode = None
    if requested_view_mode is not None:
        session_value.set(requested_view_mode)
    stored_mode = session_value.get()
    try:
        return AdminCollectionViewMode(stored_mode)
    except ValueError:
        default_mode = get_admin_collection_spec(collection_key).default_view_mode
        session_value.set(default_mode)
        return default_mode


def resolve_admin_collection_show_details(
    request: HTMXRequest, collection_key: str
) -> bool:
    session_value = SessionAdminCollectionShowDetails(request, collection_key)
    requested_value = request.query_params.get('collection_details')
    if requested_value is not None:
        normalized_value = requested_value.lower()
        if normalized_value in {'true', '1', 'on'}:
            session_value.set(True)
        elif normalized_value in {'false', '0', 'off'}:
            session_value.set(False)
    return session_value.get()


from web.admin.accounts.collection import COLLECTION_SPEC as _accounts_spec  # noqa: E402
from web.admin.display_controllers.collection import (  # noqa: E402
    COLLECTION_SPEC as _display_controllers_spec,
)
from web.admin.events.collection import COLLECTION_SPEC as _events_spec  # noqa: E402
from web.admin.families.collection import COLLECTION_SPEC as _families_spec  # noqa: E402
from web.admin.championship.collection import (  # noqa: E402
    COLLECTION_SPEC as _championships_spec,
    SOURCE_COLLECTION_SPEC as _championship_sources_spec,
)
from web.admin.menus.collection import COLLECTION_SPEC as _menus_spec  # noqa: E402
from web.admin.place_card_templates.collection import (  # noqa: E402
    COLLECTION_SPEC as _place_card_templates_spec,
)
from web.admin.prizes.collection import COLLECTION_SPEC as _prizes_spec  # noqa: E402
from web.admin.rotators.collection import COLLECTION_SPEC as _rotators_spec  # noqa: E402
from web.admin.screens.collection import COLLECTION_SPEC as _screens_spec  # noqa: E402
from web.admin.teams.collection import COLLECTION_SPEC as _teams_spec  # noqa: E402
from web.admin.timers.collection import COLLECTION_SPEC as _timers_spec  # noqa: E402
from web.admin.tournaments.collection import COLLECTION_SPEC as _tournaments_spec  # noqa: E402

_SPECS: dict[str, AdminCollectionSpec] = {
    'accounts': _accounts_spec,
    'display-controllers': _display_controllers_spec,
    'events': _events_spec,
    'families': _families_spec,
    'championships': _championships_spec,
    'championship-sources': _championship_sources_spec,
    'menus': _menus_spec,
    'place-card-templates': _place_card_templates_spec,
    'prize-categories': _prizes_spec,
    'rotators': _rotators_spec,
    'screens': _screens_spec,
    'teams': _teams_spec,
    'timers': _timers_spec,
    'tournaments': _tournaments_spec,
}


def get_admin_collection_spec(collection_key: str) -> AdminCollectionSpec:
    try:
        spec = _SPECS[collection_key]
    except KeyError as error:
        raise ValueError(f'Unknown admin collection [{collection_key}].') from error
    return deepcopy(spec)
