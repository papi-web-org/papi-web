from web.admin.collection import (
    AdminCollectionSpec,
    CardLayout,
    ComponentPlacement,
    ListColumn,
    ListLayout,
)
from web.admin.label import _


COLLECTION_SPEC: AdminCollectionSpec = AdminCollectionSpec(
    key='display-controllers',
    components_template=('/admin/display_controllers/display_controller_components.j2'),
    card_href_component='row_href',
    row_href_component='row_href',
    card=CardLayout(
        header=(ComponentPlacement('identity', 'flex-grow-1 min-width-0'),),
        body=(ComponentPlacement('assignment'),),
        footer=(ComponentPlacement('actions'),),
    ),
    list=ListLayout(
        columns=(
            ListColumn(
                'identity',
                label=_('Display controller'),
                width='minmax(min-content, 1.2fr)',
            ),
            ListColumn(
                'assignment',
                label=_('Assigned display'),
                width='minmax(min-content, 1.5fr)',
            ),
            ListColumn(
                'actions',
                label=_('Actions'),
                header_class='text-end',
                cell_class='justify-content-end',
            ),
        ),
    ),
)
