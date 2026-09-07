from web.admin.collection import (
    AdminCollectionSpec,
    AdminCollectionViewMode,
    CardLayout,
    ComponentPlacement,
    ListColumn,
    ListLayout,
)
from web.admin.label import _

COLLECTION_SPEC: AdminCollectionSpec = AdminCollectionSpec(
    key='place-card-templates',
    components_template=(
        '/admin/place_card_templates/place_card_template_components.j2'
    ),
    # template.id can contain a '/', which is awkward in a DOM id; the sanitised
    # css_class is unique and selector-safe.
    item_id_attribute='css_class',
    default_view_mode=AdminCollectionViewMode.CARDS,
    card=CardLayout(
        header=(ComponentPlacement('identity', 'flex-grow-1 min-width-0'),),
        summary=(ComponentPlacement('type_badge'),),
        summary_class='justify-content-center',
        body=(ComponentPlacement('preview'),),
        footer=(ComponentPlacement('actions'),),
    ),
    list=ListLayout(
        columns=(
            ListColumn('identity', label=_('Name'), width='minmax(min-content, 1fr)'),
            ListColumn('type_badge', label=_('Type')),
            ListColumn(
                'actions',
                label=_('Actions'),
                header_class='text-end',
                cell_class='justify-content-end',
            ),
        ),
        details=(ComponentPlacement('preview'),),
    ),
)
