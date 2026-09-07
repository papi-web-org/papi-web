import io
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from common import (
    CUSTOM_PLACE_CARDS_DIR,
    EMBEDDED_PLACE_CARDS_DIR,
    EXAMPLE_PLACE_CARDS_DIR,
    SharlyChessException,
)
from common.i18n import _
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from data.print_documents.place_cards.toml_container import TOMLContainer
from utils.enum import Extension
from utils.file import shutil_delete_onerror

logger: logging.Logger = get_logger()

SLUG_RE: re.Pattern[str] = re.compile(r'^[a-zA-Z0-9_-]+$')
IMAGES_SUBDIR: str = 'images'
FONTS_SUBDIR: str = 'fonts'
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}
)

# Template-wide properties the editor writes, with their parser default. A value
# equal to its default is deleted from the file rather than stored, so custom
# templates only carry the settings the user actually changed. ``type`` and
# ``name`` are handled separately (see PlaceCardTemplateEditor.save_metadata).
TEMPLATE_META_DEFAULTS: dict[str, Any] = {
    'creator': '',
    'unit': 'mm',
    'width': 116.0,
    'height': 36.0,
    'padding': 2.0,
    'css': '',
    'font_size': 14.0,
    'bold': False,
    'italic': False,
    'h_align': 'left',
    'v_align': 'top',
    'h_pos': 0.0,
    'v_pos': 0.0,
    'opacity': 1.0,
    'color': '',
    'background_color': '',
    'text_align': 'left',
}


# Per-item style/geometry properties that inherit from the template default
# when absent from the section. Empty in the form means "inherit" -> deleted.
ITEM_STR_FIELDS: tuple[str, ...] = (
    'h_align',
    'v_align',
    'text_align',
    'color',
    'background_color',
    'css',
)
ITEM_FLOAT_FIELDS: tuple[str, ...] = (
    'font_size',
    'h_pos',
    'v_pos',
    'opacity',
    'width',
    'height',
    'max_width',
    'rotate',
)
RESERVED_SECTIONS: frozenset[str] = frozenset({'default'})

# Properties, template-wide and per item, whose value is a length in the card's
# unit. Font size (pt) and rotation (degrees) are not among them.
UNIT_SCALED_PROPS: tuple[str, ...] = (
    'width',
    'height',
    'padding',
    'max_width',
    'h_pos',
    'v_pos',
    'border_width',
)

_MM_PER_INCH: float = 25.4


# Decimals kept per unit: a tenth of a millimetre is as fine as a card layout
# ever needs, and a thousandth of an inch (0.025 mm) is just finer than that, so
# converting there and back lands on the original value instead of drifting.
UNIT_DECIMALS: dict[str, int] = {'mm': 1, 'in': 3}


def convert_unit_value(value: float, from_unit: str, to_unit: str) -> float:
    """``value`` expressed in ``to_unit``: the same physical length, rounded to
    that unit's precision."""
    if from_unit == to_unit:
        return value
    scale = _MM_PER_INCH if from_unit == 'in' else 1 / _MM_PER_INCH
    return round(value * scale, UNIT_DECIMALS[to_unit])


def _fmt_float(value: float) -> str:
    # Three decimals: enough for the finest unit (thousandths of an inch).
    return f'{value:.3f}'.rstrip('0').rstrip('.')


class PlaceCardTemplateEditorError(SharlyChessException):
    """Raised when a custom place card template cannot be created or written."""


class PlaceCardTemplateEditor:
    """Write-side service for custom place card templates.

    Custom templates live at ``<CUSTOM_PLACE_CARDS_DIR>/<folder>/<name>.template``
    and their images at ``<folder>/images/``. Every write is confined to
    ``CUSTOM_PLACE_CARDS_DIR``; embedded and example templates are read-only.
    """

    _HISTORY_LIMIT: int = 100
    _undo_history: dict[str, list[str]] = {}
    _redo_history: dict[str, list[str]] = {}

    @staticmethod
    def is_custom(template_id: str) -> bool:
        return '/' in template_id

    @classmethod
    def _record_history(cls, template_id: str) -> None:
        """Snapshot the current template before a mutation, so it can be undone.
        A fresh edit clears the redo stack (the classic linear-history model)."""
        if not cls.is_custom(template_id):
            return
        file = cls._custom_file(template_id)
        if not file.exists():
            return
        stack = cls._undo_history.setdefault(template_id, [])
        stack.append(file.read_text(encoding='utf-8'))
        del stack[: -cls._HISTORY_LIMIT]
        cls._redo_history.pop(template_id, None)

    @classmethod
    def can_undo(cls, template_id: str) -> bool:
        return bool(cls._undo_history.get(template_id))

    @classmethod
    def can_redo(cls, template_id: str) -> bool:
        return bool(cls._redo_history.get(template_id))

    @classmethod
    def undo(cls, template_id: str) -> bool:
        """Restore the previous template snapshot. Returns False if nothing to
        undo."""
        return cls._step_history(template_id, cls._undo_history, cls._redo_history)

    @classmethod
    def redo(cls, template_id: str) -> bool:
        return cls._step_history(template_id, cls._redo_history, cls._undo_history)

    @classmethod
    def _step_history(
        cls,
        template_id: str,
        from_stack: dict[str, list[str]],
        to_stack: dict[str, list[str]],
    ) -> bool:
        if not cls.is_custom(template_id):
            return False
        stack = from_stack.get(template_id)
        file = cls._custom_file(template_id)
        if not stack or not file.exists():
            return False
        to_stack.setdefault(template_id, []).append(file.read_text(encoding='utf-8'))
        file.write_text(stack.pop(), encoding='utf-8')
        logger.info('Stepped history for template [%s].', template_id)
        return True

    @staticmethod
    def _type_ids() -> list[str]:
        from data.print_documents import PrintPlaceCardTypeManager

        return PrintPlaceCardTypeManager().ids()

    @staticmethod
    def _validate_slug(value: str, label: str) -> str:
        value = (value or '').strip()
        if not value or not SLUG_RE.match(value):
            raise PlaceCardTemplateEditorError(
                _(
                    'Invalid {label} [{value}]: use only letters, digits, '
                    'hyphens and underscores.'
                ).format(label=label, value=value)
            )
        return value

    @classmethod
    def _split_id(cls, template_id: str) -> tuple[str, str]:
        parts = template_id.split('/')
        if len(parts) != 2:
            raise PlaceCardTemplateEditorError(
                _('Invalid custom template id [{id}].').format(id=template_id)
            )
        return parts[0], parts[1]

    @classmethod
    def _custom_file(cls, template_id: str) -> Path:
        folder, name = cls._split_id(template_id)
        file = CUSTOM_PLACE_CARDS_DIR / folder / f'{name}.{Extension.TEMPLATE}'
        cls._assert_within(file)
        return file

    @staticmethod
    def _assert_within(path: Path) -> None:
        root = CUSTOM_PLACE_CARDS_DIR.resolve()
        try:
            path.resolve().relative_to(root)
        except ValueError:
            raise PlaceCardTemplateEditorError(_('Invalid template path.'))

    @staticmethod
    def _source_file(template_id: str) -> Path | None:
        """Resolve the ``.template`` file of any template, mirroring
        PlaceCardTemplate.load (embedded, then custom, then example)."""
        file_name = f'{template_id}.{Extension.TEMPLATE}'
        if '/' not in template_id:
            embedded = EMBEDDED_PLACE_CARDS_DIR / file_name
            return embedded if embedded.exists() else None
        for base in (CUSTOM_PLACE_CARDS_DIR, EXAMPLE_PLACE_CARDS_DIR):
            file = base / file_name
            if file.exists():
                return file
        return None

    @classmethod
    def _unique_folder(cls, base: str) -> str:
        """Return a slug whose custom subfolder does not exist yet."""
        base = cls._slugify(base) or 'template'
        candidate = base
        index = 2
        while (CUSTOM_PLACE_CARDS_DIR / candidate).exists():
            candidate = f'{base}-{index}'
            index += 1
        return candidate

    @staticmethod
    def _slugify(value: str) -> str:
        value = unicode_normalize((value or '').strip())
        return re.sub(r'[^a-zA-Z0-9_-]+', '-', value).strip('-')

    @classmethod
    def create(cls, name: str, card_type: str) -> str:
        """Create a custom template from a display name. The storage folder/id is
        auto-derived from the name (slugified, numbered to stay unique), so the
        user never deals with it."""
        name = (name or '').strip()
        if not name:
            raise PlaceCardTemplateEditorError(_('A template name is required.'))
        if card_type not in cls._type_ids():
            raise PlaceCardTemplateEditorError(
                _('Unknown place card type [{type}].').format(type=card_type)
            )
        folder = cls._unique_folder(name)
        file_stem = cls._slugify(name) or 'template'
        template_id = f'{folder}/{file_stem}'
        file = cls._custom_file(template_id)
        (file.parent / IMAGES_SUBDIR).mkdir(parents=True, exist_ok=True)
        container = TOMLContainer(file)
        container.set_value('type', value=card_type)
        container.set_value('name', value=name)
        container.save()
        logger.info('Created custom place card template [%s].', template_id)
        return template_id

    @classmethod
    def duplicate(cls, source_id: str, name: str = '') -> str:
        """Copy any template (including its images) into a fresh custom folder
        (auto-derived from ``name``) and return the new template id."""
        source_file = cls._source_file(source_id)
        if source_file is None:
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=source_id)
            )
        display_name = (name or '').strip() or source_id.split('/')[-1]
        folder = cls._unique_folder(display_name)
        file_stem = cls._slugify(display_name) or 'template'
        template_id = f'{folder}/{file_stem}'
        dest_file = cls._custom_file(template_id)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, dest_file)
        source_images = source_file.parent / IMAGES_SUBDIR
        dest_images = dest_file.parent / IMAGES_SUBDIR
        if source_images.is_dir():
            shutil.copytree(source_images, dest_images, dirs_exist_ok=True)
        else:
            dest_images.mkdir(exist_ok=True)
        # Give the copy a concrete display name (embedded names may be Jinja).
        container = TOMLContainer(dest_file)
        container.set_value('name', value=display_name)
        container.save()
        logger.info(
            'Duplicated place card template [%s] to [%s].', source_id, template_id
        )
        return template_id

    @classmethod
    def export_zip(cls, template_id: str) -> tuple[str, bytes]:
        """Build a zip archive of a template - its ``.template`` file plus its
        ``images/`` and ``fonts/`` folders - and return (filename, bytes)."""
        source_file = cls._source_file(template_id)
        if source_file is None:
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(source_file, arcname=source_file.name)
            for subdir in (IMAGES_SUBDIR, FONTS_SUBDIR):
                folder = source_file.parent / subdir
                if not folder.is_dir():
                    continue
                for file in sorted(folder.rglob('*')):
                    if file.is_file():
                        archive.write(
                            file, arcname=f'{subdir}/{file.relative_to(folder)}'
                        )
        stem = cls._slugify(template_id.split('/')[-1]) or 'template'
        return f'{stem}.zip', buffer.getvalue()

    @classmethod
    def import_zip(cls, source: Path, name: str = '') -> str:
        """Extract a template archive (as produced by :meth:`export_zip`) into a
        fresh custom folder and return the new template id. The archive must hold
        exactly one top-level ``.template`` file; ``images/`` and ``fonts/`` are
        copied across. The result is validated by loading it."""
        try:
            with zipfile.ZipFile(source) as archive:
                members = [m for m in archive.infolist() if not m.is_dir()]
                names = [m.filename for m in members]
                cls._assert_safe_archive(names)
                template_members = [
                    m
                    for m in members
                    if '/' not in m.filename
                    and m.filename.endswith(f'.{Extension.TEMPLATE}')
                ]
                if len(template_members) != 1:
                    raise PlaceCardTemplateEditorError(
                        _(
                            'The archive must contain exactly one template file. '
                            'Export a template to see the expected format.'
                        )
                    )
                template_member = template_members[0]
                display_name = (name or '').strip() or Path(
                    template_member.filename
                ).stem
                folder = cls._unique_folder(display_name)
                file_stem = cls._slugify(display_name) or 'template'
                template_id = f'{folder}/{file_stem}'
                dest_file = cls._custom_file(template_id)
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(template_member) as src, open(dest_file, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                for member in members:
                    top = member.filename.split('/', 1)[0]
                    if top not in (IMAGES_SUBDIR, FONTS_SUBDIR):
                        continue
                    target = dest_file.parent / member.filename
                    cls._assert_within(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile:
            raise PlaceCardTemplateEditorError(
                _('The file is not a valid template archive (expected a zipped file).')
            )
        # Validate the imported template actually loads; roll back if not.
        from data.print_documents.place_cards.template import PlaceCardTemplate

        try:
            PlaceCardTemplate.load(template_id)
        except Exception as error:
            shutil.rmtree(dest_file.parent, onerror=shutil_delete_onerror)
            raise PlaceCardTemplateEditorError(
                _('The archive is not a valid place card template.')
            ) from error
        # Store the chosen display name so the import is named as expected.
        container = TOMLContainer(dest_file)
        container.set_value('name', value=display_name)
        container.save()
        logger.info('Imported place card template [%s].', template_id)
        return template_id

    @staticmethod
    def _assert_safe_archive(names: list[str]) -> None:
        """Reject archives whose members would escape the extraction folder."""
        for name in names:
            pure = Path(name)
            if pure.is_absolute() or '..' in pure.parts:
                raise PlaceCardTemplateEditorError(_('Invalid template archive.'))

    @classmethod
    def delete(cls, template_id: str) -> None:
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be deleted.')
            )
        file = cls._custom_file(template_id)
        if not file.exists():
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        file.unlink()
        # A folder may hold several templates sharing an images/ folder; only
        # drop the whole folder once its last template is gone.
        if not list(file.parent.glob(f'*.{Extension.TEMPLATE}')):
            shutil.rmtree(file.parent, onerror=shutil_delete_onerror)
        # Drop its edit history so a later template reusing this id starts fresh.
        cls._undo_history.pop(template_id, None)
        cls._redo_history.pop(template_id, None)
        logger.info('Deleted custom place card template [%s].', template_id)

    @classmethod
    def list_images(cls, template_id: str) -> list[str]:
        """The image file names available to a template (its images/ folder)."""
        source_file = cls._source_file(template_id)
        if source_file is None:
            return []
        images_dir = source_file.parent / IMAGES_SUBDIR
        if not images_dir.is_dir():
            return []
        return sorted(
            file.name
            for file in images_dir.iterdir()
            if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS
        )

    @classmethod
    def image_path(cls, template_id: str, name: str) -> Path | None:
        """Resolve an image file name to a path within the template's images."""
        source_file = cls._source_file(template_id)
        if source_file is None or Path(name).name != name:
            return None
        file = source_file.parent / IMAGES_SUBDIR / name
        return file if file.is_file() else None

    @classmethod
    def save_image(cls, template_id: str, source: Path, filename: str) -> str:
        """Copy an uploaded image into the template's images/ folder (numbered to
        stay unique) and return its stored file name."""
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        ext = Path(filename).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            raise PlaceCardTemplateEditorError(
                _('Unsupported image type [{ext}].').format(ext=ext or '?')
            )
        stem = cls._slugify(Path(filename).stem) or 'image'
        images_dir = cls._custom_file(template_id).parent / IMAGES_SUBDIR
        images_dir.mkdir(parents=True, exist_ok=True)
        name = f'{stem}{ext}'
        index = 2
        while (images_dir / name).exists():
            name = f'{stem}-{index}{ext}'
            index += 1
        shutil.copyfile(source, images_dir / name)
        logger.info('Saved image [%s] to template [%s].', name, template_id)
        return name

    @classmethod
    def delete_image(cls, template_id: str, name: str) -> None:
        """Remove an image from the template's images/ folder and clear the
        reference from any item that was using it."""
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        path = cls.image_path(template_id, name)
        if path is None:
            return
        path.unlink()
        logger.info('Deleted image [%s] from template [%s].', name, template_id)
        container = TOMLContainer(cls._custom_file(template_id))
        changed = False
        for section in container.get_sections():
            section_data = container.data[section]
            if isinstance(section_data, dict) and section_data.get('image') == name:
                # Keep the (empty) image key so the item stays an image kind and
                # renders the placeholder box rather than becoming a text item.
                section_data['image'] = ''
                changed = True
        if changed:
            container.save()

    @classmethod
    def read_metadata(cls, template_id: str) -> dict[str, Any]:
        """Return the raw, typed template-wide values for the editor form."""
        source_file = cls._source_file(template_id)
        if source_file is None:
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        container = TOMLContainer(source_file)
        values: dict[str, Any] = {
            'type': container.get_str('type', default='player', values=cls._type_ids()),
            'name': container.get_str('name', default=''),
        }
        for prop, default in TEMPLATE_META_DEFAULTS.items():
            if isinstance(default, bool):
                values[prop] = container.get_bool(prop, default=default)
            elif isinstance(default, float):
                values[prop] = container.get_float(prop, default=default)
            else:
                values[prop] = container.get_str(prop, default=default)
        # Read separately so save_metadata (which only rewrites the defaults
        # loop) leaves it intact when saved from the raw-fields editor.
        values['two_sided'] = container.get_bool('two_sided', default=False)
        return values

    @classmethod
    def save_metadata(cls, template_id: str, values: dict[str, Any]) -> None:
        """Persist template-wide values, dropping any that equal their default."""
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        file = cls._custom_file(template_id)
        if not file.exists():
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        container = TOMLContainer(file)
        container.set_value('type', value=values['type'])
        name = (values.get('name') or '').strip()
        if name:
            container.set_value('name', value=name)
        else:
            container.delete_properties(['name'])
        for prop, default in TEMPLATE_META_DEFAULTS.items():
            value = values.get(prop)
            if value is None or value == default:
                container.delete_properties([prop])
            else:
                container.set_value(prop, value=value)
        container.save()
        logger.info('Saved custom place card template [%s].', template_id)

    @staticmethod
    def _convert_units(container: TOMLContainer, from_unit: str, to_unit: str) -> None:
        """Rescale every length in the file - template-wide and in each item
        section - so the card keeps its physical size in the new unit."""
        sections: list[dict[str, Any]] = [container.data] + [
            value for value in container.data.values() if isinstance(value, dict)
        ]
        for section in sections:
            for prop in UNIT_SCALED_PROPS:
                value = section.get(prop)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    section[prop] = convert_unit_value(float(value), from_unit, to_unit)

    @classmethod
    def patch_metadata(
        cls,
        template_id: str,
        updates: dict[str, Any],
        *,
        convert_from: str | None = None,
    ) -> None:
        """Merge template-wide ``updates``: None deletes the key (reverting to
        default), anything else sets it. Item sections are left untouched,
        except when ``convert_from`` (the unit the stored lengths are in)
        differs from the patched unit: every length is then converted first, so
        switching unit re-expresses the layout instead of resizing it. The
        ``updates`` lengths are expected in the new unit already."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        file = cls._custom_file(template_id)
        container = TOMLContainer(file)
        to_unit = updates.get('unit') or TEMPLATE_META_DEFAULTS['unit']
        if convert_from and convert_from != to_unit:
            cls._convert_units(container, convert_from, to_unit)
        for key, value in updates.items():
            if value is None:
                container.data.pop(key, None)
            else:
                container.data[key] = value
        container.save()
        logger.info('Patched metadata of template [%s].', template_id)

    # -------------------------------------------------------------- item CRUD

    @classmethod
    def list_items(cls, template_id: str) -> list[dict[str, str]]:
        """Return the editable items (sections) of a template, in file order."""
        source_file = cls._source_file(template_id)
        if source_file is None:
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        container = TOMLContainer(source_file)
        items: list[dict[str, str]] = []
        for section in container.get_sections():
            if section in RESERVED_SECTIONS:
                continue
            props = container.get_section_properties(section)
            kind = 'image' if 'image' in props else 'text'
            summary = container.get_str(
                'image' if kind == 'image' else 'text', section=section, default=''
            )
            items.append({'id': section, 'kind': kind, 'summary': summary})
        return items

    @classmethod
    def suggest_item_id(cls, template_id: str, kind: str) -> str:
        source_file = cls._source_file(template_id)
        existing = (
            set(TOMLContainer(source_file).get_sections()) if source_file else set()
        )
        candidate = kind
        index = 2
        while candidate in existing:
            candidate = f'{kind}_{index}'
            index += 1
        return candidate

    @classmethod
    def read_item_form_data(cls, template_id: str, section: str) -> dict[str, str]:
        """Return the raw per-item values for the item form. An empty value
        means the property is absent (inherited from the template)."""
        source_file = cls._source_file(template_id)
        if source_file is None:
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        container = TOMLContainer(source_file)
        if section not in container.get_sections():
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        props = container.get_section_properties(section)
        kind = 'image' if 'image' in props else 'text'
        data: dict[str, str] = {'section': section, 'kind': kind}
        for field in ITEM_STR_FIELDS:
            str_value = container.get_opt_str(field, section=section)
            data[field] = str_value if str_value is not None else ''
        for field in ITEM_FLOAT_FIELDS:
            float_value = container.get_opt_float(field, section=section)
            data[field] = _fmt_float(float_value) if float_value is not None else ''
        for field in ('bold', 'italic'):
            bool_value = container.get_opt_bool(field, section=section)
            data[field] = '' if bool_value is None else ('yes' if bool_value else 'no')
        display = container.get_opt_bool('display', section=section)
        data['display'] = 'off' if display is False else 'on'
        side = container.get_opt_str('side', section=section)
        data['side'] = 'back' if side == 'back' else 'front'
        if kind == 'image':
            data['image'] = container.get_str('image', section=section, default='')
        else:
            data['text'] = container.get_str('text', section=section, default='')
            data['preview_text'] = container.get_str(
                'preview_text', section=section, default=''
            )
        return data

    @classmethod
    def save_item(
        cls,
        template_id: str,
        section: str,
        kind: str,
        values: dict[str, Any],
        original_section: str = '',
    ) -> str:
        """Create or update one item (section). ``values`` holds already-typed
        values: floats as ``float | None`` (None = inherit), tri-state bools as
        ``'yes' | 'no' | ''``, and strings. Returns the item id written."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        section = cls._validate_slug(section, _('item id'))
        if section in RESERVED_SECTIONS:
            raise PlaceCardTemplateEditorError(
                _('[{id}] is a reserved item id.').format(id=section)
            )
        file = cls._custom_file(template_id)
        if not file.exists():
            raise PlaceCardTemplateEditorError(
                _('Template [{id}] not found.').format(id=template_id)
            )
        container = TOMLContainer(file)
        existing = set(container.get_sections())
        renaming = bool(original_section) and original_section != section
        if (renaming or not original_section) and section in existing:
            raise PlaceCardTemplateEditorError(
                _('An item [{id}] already exists.').format(id=section)
            )

        item: dict[str, Any] = {}
        if kind == 'image':
            # An empty image is allowed: the item renders as an empty placeholder
            # until one is chosen. The key is still written so the item keeps its
            # image kind.
            image = (values.get('image') or '').strip()
            if image and Path(image).name != image:
                raise PlaceCardTemplateEditorError(
                    _('Invalid image filename [{name}].').format(name=image)
                )
            item['image'] = image
        else:
            item['text'] = values.get('text', '') or ''
            preview_text = (values.get('preview_text') or '').strip()
            if preview_text:
                item['preview_text'] = preview_text
        if values.get('display') == 'off':
            item['display'] = False
        if values.get('side') == 'back':
            item['side'] = 'back'
        for field in ('bold', 'italic'):
            match values.get(field):
                case 'yes':
                    item[field] = True
                case 'no':
                    item[field] = False
        for field in ITEM_FLOAT_FIELDS:
            value = values.get(field)
            if value is not None:
                item[field] = value
        for field in ITEM_STR_FIELDS:
            value = (values.get(field) or '').strip()
            if value:
                item[field] = value

        if original_section:
            container.data.pop(original_section, None)
        container.data.pop(section, None)
        container.data[section] = item
        container.save()
        logger.info('Saved item [%s] of template [%s].', section, template_id)
        return section

    @classmethod
    def add_default_item(
        cls,
        template_id: str,
        kind: str,
        text: str | None = None,
        side: str | None = None,
    ) -> str:
        """Create a new item with sensible defaults, near the top-left corner,
        and return its id. Used by the visual editor 'Add' and field buttons."""
        section = cls.suggest_item_id(template_id, kind)
        values: dict[str, Any] = {
            'h_align': 'left',
            'v_align': 'top',
            'h_pos': 2.0,
            'v_pos': 2.0,
        }
        if side == 'back':
            values['side'] = 'back'
        if kind == 'image':
            # No image chosen yet: the item shows an empty placeholder box until
            # the user picks or uploads one.
            values['image'] = ''
            values['width'] = 20.0
        else:
            values['text'] = text or _('Text')
        cls.save_item(template_id, section, kind, values)
        if kind == 'image':
            # An image is a backdrop by default, so it goes under the text
            # already on the card; a new text item stays on top. Reordered
            # without its own history entry: adding is one undoable step.
            container = TOMLContainer(cls._custom_file(template_id))
            cls._move_section(container, section, 'back')
            container.save()
        return section

    @classmethod
    def patch_item(
        cls, template_id: str, section: str, updates: dict[str, Any]
    ) -> None:
        """Merge ``updates`` into an existing item: a value of ``None`` deletes
        the key (reverting to the template/inherited default), anything else
        sets it. Keys absent from ``updates`` (e.g. the drag-driven position)
        are left untouched."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        file = cls._custom_file(template_id)
        container = TOMLContainer(file)
        if section not in container.get_sections():
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        section_data = container.data[section]
        assert isinstance(section_data, dict)
        for key, value in updates.items():
            if value is None:
                section_data.pop(key, None)
            else:
                section_data[key] = value
        container.save()
        logger.info('Patched item [%s] of template [%s].', section, template_id)

    @classmethod
    def move_item(
        cls,
        template_id: str,
        section: str,
        h_align: str,
        v_align: str,
        h_pos: float,
        v_pos: float,
        side: str | None = None,
    ) -> None:
        """Reposition one item, keeping its current anchor. Offsets may be
        negative (the item overflows the card edge, clipped by the renderer).
        ``side`` (front/back), when given, moves it between the two faces.
        Only position/side keys are touched; text, style, etc. are preserved."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        if h_align not in ('left', 'center', 'right') or v_align not in (
            'top',
            'middle',
            'bottom',
        ):
            raise PlaceCardTemplateEditorError(_('Invalid alignment.'))
        file = cls._custom_file(template_id)
        container = TOMLContainer(file)
        if section not in container.get_sections():
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        section_data = container.data[section]
        assert isinstance(section_data, dict)
        section_data['h_align'] = h_align
        section_data['v_align'] = v_align
        section_data['h_pos'] = round(h_pos, 2)
        section_data['v_pos'] = round(v_pos, 2)
        if side is not None:
            if side == 'back':
                section_data['side'] = 'back'
            else:
                section_data.pop('side', None)
        container.save()
        logger.info('Moved item [%s] of template [%s].', section, template_id)

    @classmethod
    def set_anchor(
        cls, template_id: str, section: str, h_align: str, v_align: str
    ) -> None:
        """Set an item's alignment anchor (any of left/center/right and
        top/middle/bottom), preserving its offsets. ``center``/``middle`` centre
        the item and make the corresponding offset irrelevant in the renderer."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        if h_align not in ('left', 'center', 'right') or v_align not in (
            'top',
            'middle',
            'bottom',
        ):
            raise PlaceCardTemplateEditorError(_('Invalid alignment.'))
        file = cls._custom_file(template_id)
        container = TOMLContainer(file)
        if section not in container.get_sections():
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        section_data = container.data[section]
        assert isinstance(section_data, dict)
        section_data['h_align'] = h_align
        section_data['v_align'] = v_align
        container.save()
        logger.info('Set anchor of item [%s] of template [%s].', section, template_id)

    @classmethod
    def move_all_to_front(cls, template_id: str) -> None:
        """Drop the 'side' key from every item (all onto the front). Used when
        two-sided is turned off so the back face disappears."""
        if not cls.is_custom(template_id):
            return
        file = cls._custom_file(template_id)
        if not file.exists():
            return
        container = TOMLContainer(file)
        changed = False
        for section in container.get_sections():
            if section in RESERVED_SECTIONS:
                continue
            section_data = container.data[section]
            if isinstance(section_data, dict) and 'side' in section_data:
                section_data.pop('side', None)
                changed = True
        if changed:
            container.save()
            logger.info('Moved all items to the front of template [%s].', template_id)

    @staticmethod
    def _move_section(container: TOMLContainer, section: str, where: str) -> None:
        """Move an item section to the front or the back of the file. Not saved
        - the caller does that."""
        sections = container.get_sections()
        if section not in sections:
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        index = sections.index(section)
        match where:
            case 'front':
                target = len(sections) - 1
            case 'back':
                target = 0
            case _:
                raise PlaceCardTemplateEditorError(_('Invalid position.'))
        if target == index:
            return
        sections.insert(target, sections.pop(index))
        # TOML wants every top-level value before the first table, so the
        # rebuilt file keeps the template-wide properties up front.
        reordered: dict[str, Any] = {
            key: value
            for key, value in container.data.items()
            if not isinstance(value, dict)
        }
        for name in sections:
            reordered[name] = container.data[name]
        container.data = reordered

    @classmethod
    def reorder_item(cls, template_id: str, section: str, where: str) -> None:
        """Move an item within the file, which is what decides the stacking:
        the last section is painted on top."""
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        container = TOMLContainer(cls._custom_file(template_id))
        cls._move_section(container, section, where)
        container.save()
        logger.info('Moved item [%s] of template [%s] %s.', section, template_id, where)

    @classmethod
    def delete_item(cls, template_id: str, section: str) -> None:
        cls._record_history(template_id)
        if not cls.is_custom(template_id):
            raise PlaceCardTemplateEditorError(
                _('Only custom templates can be edited.')
            )
        file = cls._custom_file(template_id)
        container = TOMLContainer(file)
        if section not in container.get_sections():
            raise PlaceCardTemplateEditorError(
                _('Item [{id}] not found.').format(id=section)
            )
        container.data.pop(section, None)
        container.save()
        logger.info('Deleted item [%s] of template [%s].', section, template_id)
