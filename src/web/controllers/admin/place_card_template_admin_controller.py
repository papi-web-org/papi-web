import json
import logging
from tempfile import NamedTemporaryFile
from typing import Annotated, Any

from litestar import delete, get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest, HTMXTemplate
from litestar.response import File, Template
from litestar.status_codes import HTTP_200_OK

from common.i18n import _
from common.logger import get_logger
from data.access_levels.actions import AuthAction
from data.print_documents.place_cards.editor import (
    TEMPLATE_META_DEFAULTS,
    PlaceCardTemplateEditor,
    PlaceCardTemplateEditorError,
    convert_unit_value,
)
from data.print_documents.place_cards.content import (
    is_builder_friendly,
    parse_content,
    serialize_content,
)
from data.print_documents.place_cards.template import PlaceCardTemplate
from utils.file import image_file_inline_url
from utils.fonts import system_font_families
from web.controllers.admin.base_admin_controller import (
    AdminWebContext,
    BaseAdminController,
)
from web.controllers.base_controller import WebContext
from web.guards import ActionGuard

logger: logging.Logger = get_logger()

_MODALS_TEMPLATE = 'admin/modals.html'
# The place card pages live outside the admin nav tabs: this value replaces the
# tab id in their shell context so the sidebar highlights their own button
# instead of falling back to the first nav tab.
PLACE_CARD_ADMIN_TAB = 'place_card_templates'
# Sentinel: a form field left unchanged (invalid input) that patching must skip.
_SKIP = object()


class PlaceCardTemplateAdminController(BaseAdminController):
    """Global (non-event) editor for custom place card templates."""

    guards = [ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)]

    @staticmethod
    def _type_options() -> dict[str, str]:
        from data.print_documents import PrintPlaceCardTypeManager

        return {
            place_card_type.static_id(): place_card_type.static_name()
            for place_card_type in PrintPlaceCardTypeManager().objects()
        }

    def _render_library_page(
        self,
        web_context: AdminWebContext,
        *,
        errors: dict[str, str] | None = None,
    ) -> Template:
        """Full-page template library (admin shell + template lists)."""
        from web.controllers.admin.index_admin_controller import IndexAdminController

        from data.print_documents import PrintPlaceCardTypeManager

        templates = PlaceCardTemplate.get_place_card_templates_by_id(
            custom=True, examples=False
        )
        type_order = {
            place_card_type: index
            for index, place_card_type in enumerate(
                PrintPlaceCardTypeManager().objects()
            )
        }
        custom = sorted(
            (t for t in templates.values() if not t.embedded), key=lambda t: t.id
        )
        embedded = sorted(
            (t for t in templates.values() if t.embedded),
            key=lambda t: (type_order[t.type], t.id),
        )
        previews: dict[str, str] = {}
        for template in custom + embedded:
            try:
                previews[template.id] = template.preview(crop_marks=False)
            except Exception:
                logger.exception('Could not preview [%s].', template.id)
                previews[template.id] = ''
        context = IndexAdminController.admin_shell_context(web_context) | {
            'custom_templates': custom,
            'embedded_templates': embedded,
            'previews': previews,
            'errors': errors or {},
            'admin_tab': PLACE_CARD_ADMIN_TAB,
        }
        return HTMXTemplate(
            template_name='admin/place_card_templates/library_page.html',
            context=context,
        )

    @classmethod
    def _create_modal_context(
        cls,
        web_context: AdminWebContext,
        *,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return web_context.template_context | {
            'modal': 'place-card-template-create',
            'type_options': cls._type_options(),
            'data': data or {},
            'errors': errors or {},
        }

    @staticmethod
    def _canvas_context(
        template_id: str, select_section: str | None = None, example: int = 0
    ) -> dict[str, Any]:
        template = PlaceCardTemplate.load(template_id)
        return {
            'template_id': template_id,
            'unit': template.unit,
            'card_html': template.editor_card_html(example),
            'select_section': select_section,
            'example': example,
            'can_undo': PlaceCardTemplateEditor.can_undo(template_id),
            'can_redo': PlaceCardTemplateEditor.can_redo(template_id),
        }

    @staticmethod
    def _example(data: dict[str, str] | None) -> int:
        try:
            return int(WebContext.form_data_to_str(data or {}, 'example') or 0)
        except ValueError:
            return 0

    @staticmethod
    def _plugin_field_groups() -> list[dict[str, Any]]:
        """Field-token groups contributed by plugins (e.g. a federation league).
        Plugins declare them via the ``place_card_field_tokens`` hook, so the
        core never names a specific plugin."""
        from plugins.manager import plugin_manager

        grouped: dict[str, list[dict[str, str]]] = {}
        order: list[str] = []
        try:
            results = plugin_manager.hook.place_card_field_tokens()
        except Exception:
            logger.exception('Could not collect plugin place card field tokens.')
            results = []
        for result in results or []:
            for token in result or []:
                group = token.get('group') or _('Plugin')
                if group not in grouped:
                    grouped[group] = []
                    order.append(group)
                grouped[group].append({'label': token['label'], 'expr': token['expr']})
        return [{'label': group, 'tokens': grouped[group]} for group in order]

    @classmethod
    def _field_tokens(cls, type_id: str) -> list[dict[str, Any]]:
        """Field tokens grouped by object type, for the card type. Each group is
        {'label': str, 'tokens': [{'label': str, 'expr': str}, ...]}."""

        def group(label: str, pairs: list[tuple[str, str]]) -> dict[str, Any]:
            return {
                'label': label,
                'tokens': [{'label': lbl, 'expr': expr} for lbl, expr in pairs],
            }

        groups: list[dict[str, Any]] = []

        def player_group(prefix: str, label: str) -> dict[str, Any]:
            fields = (
                (_('Full name'), 'full_name'),
                (_('First name'), 'first_name'),
                (_('Last name'), 'last_name'),
                (_('Rating'), 'rating'),
                (_('Rating type'), 'rating_type'),
                (_('Title'), 'title'),
                (_('Category'), 'category'),
                (_('Federation'), 'federation'),
                (_('Flag'), 'federation_flag | safe'),
                (_('Club'), 'club'),
                (_('Year of birth'), 'year_of_birth'),
                (_('Gender'), 'gender'),
                (_('Team name'), 'team_name'),
            )
            return group(
                label,
                [(lbl, '{{ ' + prefix + '.' + attr + ' }}') for lbl, attr in fields],
            )

        if type_id == 'player':
            groups.append(player_group('player', _('Player')))
        elif type_id == 'board':
            groups.append(
                group(
                    _('Board'),
                    [
                        (_('Board number'), '{{ board.number }}'),
                        (_('Table'), '{{ board.table }}'),
                    ],
                )
            )
        elif type_id == 'pairing':
            groups.append(
                group(_('Pairing'), [(_('Board number'), '{{ pairing.number }}')])
            )
            groups.append(player_group('pairing.white_player', _('White player')))
            groups.append(player_group('pairing.black_player', _('Black player')))
        elif type_id == 'team':
            groups.append(
                group(
                    _('Team'),
                    [
                        (_('Team name'), '{{ team.name }}'),
                        (_('Captain'), '{{ team.captain }}'),
                    ],
                )
            )
        for obj, obj_label in (('event', _('Event')), ('tournament', _('Tournament'))):
            groups.append(
                group(
                    obj_label,
                    [
                        (_('Name'), '{{ ' + obj + '.name }}'),
                        (_('Start day'), '{{ ' + obj + '.start.day }}'),
                        (_('Start month'), '{{ ' + obj + '.start.month }}'),
                        (_('Start year'), '{{ ' + obj + '.start.year }}'),
                        (_('End day'), '{{ ' + obj + '.stop.day }}'),
                        (_('End month'), '{{ ' + obj + '.stop.month }}'),
                        (_('End year'), '{{ ' + obj + '.stop.year }}'),
                    ],
                )
            )
        groups.extend(cls._plugin_field_groups())
        return groups

    @classmethod
    def _props_context(
        cls, template_id: str, section: str, mode: str | None = None
    ) -> dict[str, Any]:
        template = PlaceCardTemplate.load(template_id)
        data = cls._item_props_data(template_id, section, mode)
        return {
            'template_id': template_id,
            'section': section,
            'unit': template.unit,
            'kind': data['kind'],
            'field_tokens': cls._field_tokens(template.type.static_id()),
            'font_groups': cls._font_groups(template),
            'images': cls._image_options(template_id),
            'data': data,
            # Image-upload validation errors; empty unless an upload just failed.
            'errors': {},
        }

    @staticmethod
    def _image_options(template_id: str) -> list[dict[str, str]]:
        """Available images (name + inline data URL for a thumbnail)."""
        options: list[dict[str, str]] = []
        for name in PlaceCardTemplateEditor.list_images(template_id):
            path = PlaceCardTemplateEditor.image_path(template_id, name)
            url = ''
            if path is not None:
                try:
                    url = image_file_inline_url(path)
                except Exception:
                    logger.exception('Could not inline image [%s].', name)
            options.append({'name': name, 'url': url})
        return options

    @staticmethod
    def _font_groups(template: PlaceCardTemplate) -> list[dict[str, Any]]:
        """Font options for the item picker: web-safe families that work
        everywhere, plus any fonts bundled with the template."""
        # Generic families and the classic web-safe names - stored as ready-made
        # CSS stacks (no font file needed).
        standard = [
            {'value': stack, 'label': label}
            for label, stack in (
                (_('Sans-serif'), 'sans-serif'),
                (_('Serif'), 'serif'),
                (_('Monospace'), 'monospace'),
                ('Arial', 'Arial, sans-serif'),
                ('Georgia', 'Georgia, serif'),
                ('Times New Roman', '"Times New Roman", serif'),
                ('Courier New', '"Courier New", monospace'),
                ('Verdana', 'Verdana, sans-serif'),
            )
        ]
        groups: list[dict[str, Any]] = [{'label': _('Standard'), 'fonts': standard}]
        bundled = [
            {'value': font.name, 'label': font.stem}
            for font in template.available_fonts()
        ]
        if bundled:
            groups.append({'label': _('Template fonts'), 'fonts': bundled})
        # Fonts installed on this computer, stored as a quoted CSS family with a
        # generic fallback so they render the same way the standard names do.
        installed = [
            {'value': f'"{family}", sans-serif', 'label': family}
            for family in system_font_families()
        ]
        if installed:
            groups.append({'label': _('On this computer'), 'fonts': installed})
        return groups

    @classmethod
    def _card_context(cls, template_id: str) -> dict[str, Any]:
        return {
            'template_id': template_id,
            'type_name': PlaceCardTemplate.load(
                template_id
            ).type.static_singular_name(),
            'data': cls._card_props_data(template_id),
        }

    def _render_editor_page(
        self, web_context: AdminWebContext, template_id: str
    ) -> Template:
        """Render the full visual editor page (admin shell + canvas + palette)."""
        from web.controllers.admin.index_admin_controller import IndexAdminController

        template = PlaceCardTemplate.load(template_id)
        examples = [
            {'index': index, 'label': template.example_label(index)}
            for index in range(4)
        ]
        context = (
            IndexAdminController.admin_shell_context(web_context)
            | self._canvas_context(template_id)
            | {
                'field_tokens': self._field_tokens(template.type.static_id()),
                'examples': examples,
                'template_name': template.name,
                'admin_tab': PLACE_CARD_ADMIN_TAB,
            }
        )
        return HTMXTemplate(
            template_name='admin/place_card_templates/visual_editor_page.html',
            context=context,
        )

    @classmethod
    def _parse_item_patch(cls, data: dict[str, str], kind: str) -> dict[str, Any]:
        """Build a merge dict for patch_item from the properties panel: a value
        of None deletes the key (inherit), _SKIP leaves it untouched."""

        def num(field: str) -> Any:
            try:
                return WebContext.form_data_to_float(data, field, empty_value=None)
            except ValueError:
                return _SKIP

        updates: dict[str, Any] = {}
        if 'side' in data:
            side = WebContext.form_data_to_str(data, 'side')
            updates['side'] = 'back' if side == 'back' else None
        opacity = num('opacity')
        if opacity is not _SKIP:
            # The slider always sends a value; 1.0 (fully opaque) == the default.
            updates['opacity'] = (
                opacity if opacity is not None and 0.0 <= opacity < 1.0 else None
            )
        # Border + raw CSS apply to every item kind. A border needs both a
        # width and a colour.
        border_width = num('border_width')
        border_color = WebContext.form_data_to_str(data, 'border_color')
        if border_width is not _SKIP:
            if border_width and border_color:
                updates['border_width'] = border_width
                updates['border_color'] = border_color
            else:
                updates['border_width'] = None
                updates['border_color'] = None
        updates['css'] = WebContext.form_data_to_str(data, 'css') or None
        if kind == 'image':
            image = WebContext.form_data_to_str(data, 'image')
            if image:
                updates['image'] = image
            width = num('width')
            if width is not _SKIP:
                updates['width'] = width if width is None or width > 0 else None
            # Height is always derived from the width and the image's aspect ratio.
            updates['height'] = None
        else:
            # The content builder posts its parts as a JSON array; serialise them
            # back to the Jinja string stored on the item.
            if 'content' in data:
                try:
                    parts = json.loads(
                        WebContext.form_data_to_str(data, 'content') or '[]'
                    )
                except (ValueError, TypeError):
                    parts = []
                updates['text'] = serialize_content(parts)
            else:
                updates['text'] = WebContext.form_data_to_str(
                    data, 'text', empty_value=''
                )
            width = num('width')
            if width is not _SKIP:
                updates['width'] = width if width is None or width > 0 else None
            # The editor uses a single fixed width; drop any legacy max_width so
            # the two never coexist.
            updates['max_width'] = None
            font_size = num('font_size')
            if font_size is not _SKIP and (font_size is None or font_size > 0):
                updates['font_size'] = font_size
            updates['bold'] = WebContext.form_data_to_bool(data, 'bold')
            updates['italic'] = WebContext.form_data_to_bool(data, 'italic')
            updates['underline'] = WebContext.form_data_to_bool(data, 'underline')
            updates['strikethrough'] = WebContext.form_data_to_bool(
                data, 'strikethrough'
            )
            updates['uppercase'] = WebContext.form_data_to_bool(data, 'uppercase')
            updates['font_family'] = (
                WebContext.form_data_to_str(data, 'font_family') or None
            )
            text_align = WebContext.form_data_to_str(data, 'text_align') or 'left'
            updates['text_align'] = (
                text_align if text_align in ('left', 'center', 'right') else 'left'
            )
            updates['color'] = WebContext.form_data_to_str(data, 'color') or None
            # A fill exists only when a colour is set (empty == no fill).
            updates['background_color'] = (
                WebContext.form_data_to_str(data, 'background_color') or None
            )
        return updates

    @staticmethod
    def _fmt(value: float | None) -> str:
        if value is None:
            return ''
        return f'{value:.2f}'.rstrip('0').rstrip('.')

    @classmethod
    def _item_props_data(
        cls, template_id: str, section: str, mode: str | None = None
    ) -> dict[str, Any]:
        """Panel values, resolved (no inherit): the item's effective style,
        falling back to the template defaults, is shown as concrete values.
        ``mode`` ('basic'/'advanced') overrides the auto-detected editor; 'basic'
        is honoured only when the content can actually be parsed to blocks."""
        raw = PlaceCardTemplateEditor.read_item_form_data(template_id, section)
        kind = raw.get('kind', 'text')
        template = PlaceCardTemplate.load(template_id)
        item = next((it for it in template.items if it.id == section), None)
        friendly = is_builder_friendly(raw.get('text', ''))
        if mode == 'advanced':
            content_mode = 'advanced'
        elif mode == 'basic' and friendly:
            content_mode = 'simple'
        else:
            content_mode = 'simple' if friendly else 'advanced'
        return {
            'kind': kind,
            'two_sided': 'on' if template.is_two_sided else 'off',
            'side': 'back' if item and item.back else 'front',
            'text': raw.get('text', ''),
            'parts': parse_content(raw.get('text', '')),
            # Complex Jinja (loops, if/elif, with...) can't be built from parts;
            # the panel shows a raw Jinja box instead (auto, or per the toggle).
            'content_mode': content_mode,
            'can_be_basic': friendly,
            'css': (item.css if item else '') or '',
            'border_color': (item.border_color if item else '') or '',
            'border_width': cls._fmt(item.border_width) if item else '',
            'image': raw.get('image', ''),
            # A legacy max_width shows in the single width control (it becomes a
            # fixed width on the next save).
            'width': raw.get('width', '') or raw.get('max_width', ''),
            'height': raw.get('height', ''),
            'anchor_h': item.h_align if item else 'left',
            'anchor_v': item.v_align if item else 'top',
            'h_pos': cls._fmt(item.h_pos) if item else '0',
            'v_pos': cls._fmt(item.v_pos) if item else '0',
            'font_size': cls._fmt(item.font_size) if item else '',
            'bold': 'on' if item and item.bold else 'off',
            'italic': 'on' if item and item.italic else 'off',
            'underline': 'on' if item and item.underline else 'off',
            'strikethrough': 'on' if item and item.strikethrough else 'off',
            'uppercase': 'on' if item and item.uppercase else 'off',
            'font_family': item.font_family if item else '',
            'text_align': (item.text_align if item else 'left'),
            'color': (item.color if item and item.color else '#000000'),
            # Empty == no fill; the swatch shows a transparent (checkerboard) state.
            'background_color': (
                item.background_color if item and item.background_color else ''
            ),
            'opacity': cls._fmt(item.opacity) if item else '1',
        }

    @classmethod
    def _card_props_data(cls, template_id: str) -> dict[str, str]:
        raw = PlaceCardTemplateEditor.read_metadata(template_id)
        # The switch reflects effective two-sidedness: built-in two-sided cards
        # use a back-side item rather than the explicit flag.
        raw['two_sided'] = PlaceCardTemplate.load(template_id).is_two_sided
        return WebContext.values_dict_to_form_data(raw)

    @classmethod
    def _parse_card_patch(
        cls, data: dict[str, str], *, from_unit: str = 'mm'
    ) -> dict[str, Any]:
        """Merge dict for patch_metadata: value == default -> None (drop).

        The form's lengths are in ``from_unit`` (what the fields displayed);
        they are converted to the submitted unit before the comparison, so the
        defaults - which are millimetres - are compared against millimetres.

        Only card geometry/name/two-sided is edited here. The template-level
        default style is user-authored (it seeds new items) and read-only, so it
        is deliberately never touched by a card edit.
        """
        defaults = TEMPLATE_META_DEFAULTS
        updates: dict[str, Any] = {}
        name = WebContext.form_data_to_str(data, 'name')
        updates['name'] = name or None
        unit = WebContext.form_data_to_str(data, 'unit') or 'mm'
        unit = unit if unit in ('mm', 'in') else 'mm'
        updates['unit'] = None if unit == defaults['unit'] else unit

        def num(field: str) -> Any:
            default = defaults[field]
            try:
                value = WebContext.form_data_to_float(data, field, empty_value=default)
            except ValueError:
                return _SKIP
            value = convert_unit_value(value, from_unit, unit)
            return None if value == default else value

        for field in ('width', 'height', 'padding'):
            value = num(field)
            if value is not _SKIP and not (value is not None and value <= 0):
                updates[field] = value
        updates['two_sided'] = (
            True if WebContext.form_data_to_bool(data, 'two_sided') else None
        )
        return updates

    # ------------------------------------------------------------------ routes

    @get(path='/place-card-templates', name='place-card-templates')
    async def htmx_library_page(self, request: HTMXRequest) -> Template:
        web_context = AdminWebContext(request)
        return self._render_library_page(web_context)

    @get(
        path='/place-card-template-create-modal',
        name='place-card-template-create-modal',
    )
    async def htmx_create_modal(self, request: HTMXRequest) -> Template:
        web_context = AdminWebContext(request)
        return self._render_modal(
            _MODALS_TEMPLATE, self._create_modal_context(web_context)
        )

    @post(path='/place-card-template-create', name='place-card-template-create')
    async def htmx_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        try:
            template_id = PlaceCardTemplateEditor.create(
                WebContext.form_data_to_str(data, 'name') or '',
                WebContext.form_data_to_str(data, 'type') or 'player',
            )
        except PlaceCardTemplateEditorError as error:
            return self._render_modal(
                _MODALS_TEMPLATE,
                self._create_modal_context(
                    web_context, data=data, errors={'name': str(error)}
                ),
            )
        return self._render_editor_page(web_context, template_id)

    @get(
        path='/place-card-template-duplicate-modal/{template_id:path}',
        name='place-card-template-duplicate-modal',
    )
    async def htmx_duplicate_modal(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request)
        template_id = template_id.strip('/')
        source = PlaceCardTemplate.load(template_id)
        return self._render_modal(
            _MODALS_TEMPLATE,
            self._duplicate_modal_context(
                web_context,
                template_id,
                data={'name': _('{name} copy').format(name=source.name)},
            ),
        )

    @staticmethod
    def _duplicate_modal_context(
        web_context: AdminWebContext,
        template_id: str,
        *,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return web_context.template_context | {
            'modal': 'place-card-template-duplicate',
            'template_id': template_id,
            'data': data or {},
            'errors': errors or {},
        }

    @post(
        path='/place-card-template-duplicate/{template_id:path}',
        name='place-card-template-duplicate',
    )
    async def htmx_duplicate(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        template_id = template_id.strip('/')
        try:
            new_id = PlaceCardTemplateEditor.duplicate(
                template_id, WebContext.form_data_to_str(data, 'name') or ''
            )
        except PlaceCardTemplateEditorError as error:
            return self._render_modal(
                _MODALS_TEMPLATE,
                self._duplicate_modal_context(
                    web_context, template_id, data=data, errors={'name': str(error)}
                ),
            )
        return self._render_editor_page(web_context, new_id)

    @get(
        path='/place-card-template-delete-modal/{template_id:path}',
        name='place-card-template-delete-modal',
    )
    async def htmx_delete_modal(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request)
        template_id = template_id.strip('/')
        return self._render_modal(
            _MODALS_TEMPLATE,
            web_context.template_context
            | {
                'modal': 'place-card-template-delete',
                'template_id': template_id,
                'template_name': PlaceCardTemplate.load(template_id).name,
            },
        )

    @delete(
        path='/place-card-template-delete/{template_id:path}',
        name='place-card-template-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_delete(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request)
        try:
            PlaceCardTemplateEditor.delete(template_id.strip('/'))
        except PlaceCardTemplateEditorError as error:
            return self._render_library_page(
                web_context, errors={'library': str(error)}
            )
        return self._render_library_page(web_context)

    @get(
        path='/place-card-template-export/{template_id:path}',
        name='place-card-template-export',
    )
    async def htmx_export(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> File:
        filename, payload = PlaceCardTemplateEditor.export_zip(template_id.strip('/'))
        temp_file = NamedTemporaryFile(delete=False, mode='wb', suffix='.zip')
        temp_file.write(payload)
        temp_file.close()
        return File(path=temp_file.name, filename=filename)

    @post(
        path='/place-card-template-import',
        name='place-card-template-import',
    )
    async def htmx_import(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        normalized = await WebContext.normalize_multipart_data(data)
        file_path = WebContext.form_data_to_path(normalized, 'file')
        if file_path is None:
            return self._render_library_page(
                web_context, errors={'library': _('No file was uploaded.')}
            )
        try:
            if file_path.suffix.lower() != '.zip':
                raise PlaceCardTemplateEditorError(
                    _(
                        'Invalid file extension [{extension}] (expected: {expected}).'
                    ).format(
                        extension=file_path.suffix or '?',
                        expected='.zip',
                    )
                )
            template_id = PlaceCardTemplateEditor.import_zip(file_path)
        except PlaceCardTemplateEditorError as error:
            return self._render_library_page(
                web_context, errors={'library': str(error)}
            )
        finally:
            file_path.unlink(missing_ok=True)
        return self._render_editor_page(web_context, template_id)

    # --------------------------------------------------- visual (WYSIWYG) editor

    @get(
        path='/place-card-visual-editor/{template_id:path}',
        name='place-card-visual-editor',
    )
    async def htmx_visual_editor(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> Template:
        # Render inside the full admin shell (global sidebar) so the URL can be
        # pushed and a refresh reloads the editor rather than bouncing to /home.
        web_context = AdminWebContext(request)
        return self._render_editor_page(web_context, template_id.strip('/'))

    def _render_canvas(
        self,
        template_id: str,
        data: dict[str, str] | None = None,
        select_section: str | None = None,
    ) -> Template:
        return Template(
            template_name='admin/place_card_templates/visual_editor_canvas.html',
            context=self._canvas_context(
                template_id, select_section, self._example(data)
            ),
        )

    @post(
        path='/place-card-item-add/{template_id:path}',
        name='place-card-item-add',
    )
    async def htmx_item_add(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        kind = (
            'image' if WebContext.form_data_to_str(data, 'kind') == 'image' else 'text'
        )
        side = WebContext.form_data_to_str(data, 'side')
        section = PlaceCardTemplateEditor.add_default_item(template_id, kind, side=side)
        return self._render_canvas(template_id, data, select_section=section)

    @post(path='/place-card-undo/{template_id:path}', name='place-card-undo')
    async def htmx_undo(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        PlaceCardTemplateEditor.undo(template_id)
        return self._render_canvas(template_id, data)

    @post(path='/place-card-redo/{template_id:path}', name='place-card-redo')
    async def htmx_redo(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        PlaceCardTemplateEditor.redo(template_id)
        return self._render_canvas(template_id, data)

    @post(
        path='/place-card-item-move/{template_id:path}',
        name='place-card-item-move',
    )
    async def htmx_item_move(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        section = WebContext.form_data_to_str(data, 'section') or ''
        h_align = WebContext.form_data_to_str(data, 'h_align') or 'left'
        v_align = WebContext.form_data_to_str(data, 'v_align') or 'top'
        h_pos = WebContext.form_data_to_float(data, 'h_pos', empty_value=0.0) or 0.0
        v_pos = WebContext.form_data_to_float(data, 'v_pos', empty_value=0.0) or 0.0
        side = WebContext.form_data_to_str(data, 'side')  # None when absent
        PlaceCardTemplateEditor.move_item(
            template_id, section, h_align, v_align, h_pos, v_pos, side=side
        )
        # No select_section: the client keeps the current selection and panel.
        return self._render_canvas(template_id, data)

    @post(
        path='/place-card-canvas-delete/{template_id:path}',
        name='place-card-canvas-delete',
    )
    async def htmx_canvas_delete(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        section = WebContext.form_data_to_str(data, 'section') or ''
        PlaceCardTemplateEditor.delete_item(template_id, section)
        return self._render_canvas(template_id, data)

    @get(
        path='/place-card-item-props/{template_id:path}',
        name='place-card-item-props',
    )
    async def htmx_item_props(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        section: FromQuery[str],
        mode: FromQuery[str | None] = None,
    ) -> Template:
        web_context = AdminWebContext(request)
        return Template(
            template_name='admin/place_card_templates/item_props_form.html',
            context=web_context.template_context
            | self._props_context(template_id.strip('/'), section, mode),
        )

    @post(
        path='/place-card-item-image-upload/{template_id:path}',
        name='place-card-item-image-upload',
    )
    async def htmx_item_image_upload(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        section: FromQuery[str],
        data: Annotated[
            dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        template_id = template_id.strip('/')
        normalized = await WebContext.normalize_multipart_data(data)
        file_path = WebContext.form_data_to_path(normalized, 'image')
        errors: dict[str, str] = {}
        if file_path is None:
            errors['image'] = _('No image file was uploaded.')
        else:
            try:
                name = PlaceCardTemplateEditor.save_image(
                    template_id, file_path, file_path.name
                )
                # Apply the freshly uploaded image to the item straight away.
                PlaceCardTemplateEditor.patch_item(
                    template_id, section, {'image': name}
                )
            except PlaceCardTemplateEditorError as error:
                errors['image'] = str(error)
        context = web_context.template_context | self._props_context(
            template_id, section
        )
        context['errors'] = errors
        return Template(
            template_name='admin/place_card_templates/item_props_form.html',
            context=context,
        )

    @post(
        path='/place-card-item-image-delete/{template_id:path}',
        name='place-card-item-image-delete',
    )
    async def htmx_item_image_delete(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        section: FromQuery[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = AdminWebContext(request)
        template_id = template_id.strip('/')
        name = WebContext.form_data_to_str(data, 'image') or ''
        if name:
            PlaceCardTemplateEditor.delete_image(template_id, name)
        return Template(
            template_name='admin/place_card_templates/item_props_form.html',
            context=web_context.template_context
            | self._props_context(template_id, section),
        )

    @post(
        path='/place-card-item-patch/{template_id:path}',
        name='place-card-item-patch',
    )
    async def htmx_item_patch(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        section = WebContext.form_data_to_str(data, 'section') or ''
        kind = WebContext.form_data_to_str(data, 'kind') or 'text'
        if section:
            try:
                PlaceCardTemplateEditor.patch_item(
                    template_id, section, self._parse_item_patch(data, kind)
                )
            except PlaceCardTemplateEditorError:
                logger.exception('Could not patch item [%s].', section)
        return self._render_canvas(template_id, data)

    @post(
        path='/place-card-item-add-field/{template_id:path}',
        name='place-card-item-add-field',
    )
    async def htmx_item_add_field(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        token = WebContext.form_data_to_str(data, 'token') or ''
        side = WebContext.form_data_to_str(data, 'side')
        section = PlaceCardTemplateEditor.add_default_item(
            template_id, 'text', text=token or None, side=side
        )
        return self._render_canvas(template_id, data, select_section=section)

    @post(
        path='/place-card-item-anchor/{template_id:path}',
        name='place-card-item-anchor',
    )
    async def htmx_item_anchor(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        section = WebContext.form_data_to_str(data, 'section') or ''
        h_align = WebContext.form_data_to_str(data, 'h_align') or 'left'
        v_align = WebContext.form_data_to_str(data, 'v_align') or 'top'
        if section:
            try:
                PlaceCardTemplateEditor.set_anchor(
                    template_id, section, h_align, v_align
                )
            except PlaceCardTemplateEditorError:
                logger.exception('Could not set anchor of [%s].', section)
        return self._render_canvas(template_id, data)

    @get(
        path='/place-card-card-props/{template_id:path}',
        name='place-card-card-props',
    )
    async def htmx_card_props(
        self, request: HTMXRequest, template_id: FromPath[str]
    ) -> Template:
        web_context = AdminWebContext(request)
        return Template(
            template_name='admin/place_card_templates/card_props_form.html',
            context=web_context.template_context
            | self._card_context(template_id.strip('/')),
        )

    @post(
        path='/place-card-card-patch/{template_id:path}',
        name='place-card-card-patch',
    )
    async def htmx_card_patch(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        template_id = template_id.strip('/')
        template = PlaceCardTemplate.load(template_id)
        was_two_sided = template.is_two_sided
        old_unit = template.unit
        updates = self._parse_card_patch(data, from_unit=old_unit)
        try:
            PlaceCardTemplateEditor.patch_metadata(
                template_id, updates, convert_from=old_unit
            )
            # Turning two-sided off flattens the back face onto the front.
            if was_two_sided and not updates.get('two_sided'):
                PlaceCardTemplateEditor.move_all_to_front(template_id)
        except PlaceCardTemplateEditorError:
            logger.exception('Could not patch card [%s].', template_id)
        return self._render_canvas(template_id, data)

    @post(
        path='/place-card-example/{template_id:path}',
        name='place-card-example',
    )
    async def htmx_example(
        self,
        request: HTMXRequest,
        template_id: FromPath[str],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        # Re-render the canvas with a different sample-data example.
        return self._render_canvas(template_id.strip('/'), data)
