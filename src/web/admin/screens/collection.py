from web.admin.collection import (
    AdminCollectionSpec,
    CardLayout,
    ComponentPlacement,
    ListColumn,
    ListLayout,
)
from web.admin.label import _


COLLECTION_SPEC: AdminCollectionSpec = AdminCollectionSpec(
    key='screens',
    components_template='/admin/screens/screen_components.j2',
    card_href_component='row_href',
    row_href_component='row_href',
    card=CardLayout(
        header=(ComponentPlacement('identity', 'flex-grow-1 min-width-0'),),
        summary=(
            ComponentPlacement('screen_type'),
            ComponentPlacement('source'),
            ComponentPlacement('screen_sets'),
        ),
        body=(ComponentPlacement('summary'),),
        details=(ComponentPlacement('details'),),
        footer=(ComponentPlacement('actions'),),
    ),
    list=ListLayout(
        columns=(
            ListColumn(
                'identity',
                label=_('Screen'),
                width='minmax(min-content, 1.4fr)',
            ),
            ListColumn('screen_sets', label=_('Content')),
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
