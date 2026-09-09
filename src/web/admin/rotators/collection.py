from web.admin.collection import (
    AdminCollectionSpec,
    CardLayout,
    ComponentPlacement,
    ListColumn,
    ListLayout,
)
from web.admin.label import _


COLLECTION_SPEC: AdminCollectionSpec = AdminCollectionSpec(
    key='rotators',
    components_template='/admin/rotators/rotator_components.j2',
    card_href_component='row_href',
    row_href_component='row_href',
    card=CardLayout(
        header=(ComponentPlacement('identity', 'flex-grow-1 min-width-0'),),
        summary=(ComponentPlacement('screen_assignments', 'mx-auto'),),
        body=(
            ComponentPlacement('delay'),
            ComponentPlacement('timer'),
            ComponentPlacement('alert_message'),
        ),
        details=(ComponentPlacement('details'),),
        footer=(ComponentPlacement('actions'),),
    ),
    list=ListLayout(
        columns=(
            ListColumn(
                'identity',
                label=_('Rotator'),
                width='minmax(min-content, 1.3fr)',
            ),
            ListColumn('screen_assignments', label=_('Screens')),
            ListColumn('delay', label=_('Delay')),
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
