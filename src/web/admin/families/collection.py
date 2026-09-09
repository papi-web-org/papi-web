from web.admin.collection import (
    AdminCollectionSpec,
    CardLayout,
    ComponentPlacement,
    ListColumn,
    ListLayout,
)
from web.admin.label import _


COLLECTION_SPEC: AdminCollectionSpec = AdminCollectionSpec(
    key='families',
    components_template='/admin/families/family_components.j2',
    card=CardLayout(
        header=(ComponentPlacement('identity', 'flex-grow-1 min-width-0'),),
        summary=(
            ComponentPlacement('screen_type'),
            ComponentPlacement('screen_count'),
        ),
        body=(ComponentPlacement('screen_ranges'),),
        details=(ComponentPlacement('details'),),
        footer=(ComponentPlacement('actions'),),
    ),
    list=ListLayout(
        columns=(
            ListColumn(
                'identity',
                label=_('Multi-Screen'),
                width='minmax(min-content, 1.4fr)',
            ),
            ListColumn(
                'screen_type',
                label=_('Type'),
                width='minmax(min-content, 1fr)',
            ),
            ListColumn(
                'tournament',
                label=_('Tournament'),
                width='minmax(min-content, 1fr)',
            ),
            ListColumn('screen_count', label=_('Screens')),
            ListColumn('timer', label=_('Timer')),
            ListColumn(
                'actions',
                label=_('Actions'),
                header_class='text-end',
                cell_class='justify-content-end',
            ),
        ),
        details=(ComponentPlacement('details'),),
    ),
)
