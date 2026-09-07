import copy
import logging
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Self, TYPE_CHECKING
from xml.etree.ElementTree import ElementTree

from PIL import Image, UnidentifiedImageError

from common.i18n import _
from common.i18n.utils import parse_jinja_string
from common.logger import get_logger
from data.print_documents.place_cards.data import (
    PlaceCardEvent,
    PlaceCardTournament,
    PlaceCardPlayer,
    PlaceCardBoard,
    PlaceCardPairing,
    PlaceCardTeam,
)
from data.print_documents.place_cards.item_style import PlaceCardItemStyle
from data.print_documents.place_cards.toml_container import TOMLContainer
from utils.file import image_file_inline_url

if TYPE_CHECKING:
    from data.print_documents.place_cards.template import PlaceCardTemplate


logger: logging.Logger = get_logger()


class PlaceCardItem(PlaceCardItemStyle, ABC):
    """A class to store an item of a place card (style and content)."""

    def __init__(
        self,
        data: TOMLContainer,
        section: str,
        template: 'PlaceCardTemplate',
    ):
        self.id: str = section
        super().__init__(
            data,
            section,
            template,
        )
        self.css_class: str = f'item-{self.id.replace("_", "-")}'
        self.display: bool = data.get_bool(
            section=section, prop='display', default=True
        )
        self.width: float | None = data.get_float(
            section=section,
            prop='width',
            default=None,
        )
        self.height: float | None = data.get_float(
            section=section,
            prop='height',
            default=None,
        )
        self.max_width: float | None = data.get_opt_float(
            section=section,
            prop='max_width',
            default=None,
        )
        self.css: str = data.get_str(
            section=section,
            prop='css',
            default='',
        )
        self.rotate: float | None = data.get_float(
            section=section,
            prop='rotate',
            default=None,
        )
        self.back: bool = (
            data.get_str(
                section=section,
                prop='side',
                default='front',
                values=[
                    'front',
                    'back',
                ],
            )
            == 'back'
        )

    @property
    @abstractmethod
    def type(self) -> str:
        """Returns a string corresponding to the type of the item."""
        pass

    def allowed_properties(
        self,
    ) -> set[str]:
        return (
            super()
            .allowed_properties()
            .union(
                {
                    'display',
                    'width',
                    'height',
                    'max_width',
                    'rotate',
                    'side',
                    'css',
                }
            )
        )

    def render_error(
        self,
        message: str,
    ) -> str:
        return f'<i class="bi bi-bug-fill"></i> {self.id}: {message}'

    def render_html(
        self,
        event: PlaceCardEvent,
        tournament: PlaceCardTournament,
        player: PlaceCardPlayer | None = None,
        board: PlaceCardBoard | None = None,
        pairing: PlaceCardPairing | None = None,
        team: PlaceCardTeam | None = None,
        preview: bool = False,
        editor: bool = False,
    ) -> str:
        """Returns the HTML to output for the item."""
        return f'<div class="card-item-wrapper {self.css_class}">{self._inner_html(event, tournament, player, board, pairing, team, preview, editor)}</div>'

    @abstractmethod
    def _inner_html(
        self,
        event: PlaceCardEvent,
        tournament: PlaceCardTournament,
        player: PlaceCardPlayer | None = None,
        board: PlaceCardBoard | None = None,
        pairing: PlaceCardPairing | None = None,
        team: PlaceCardTeam | None = None,
        preview: bool = False,
        editor: bool = False,
    ) -> str:
        """Returns the inner HTML of the item."""
        pass

    def _wrapper_css_properties(
        self,
    ) -> dict[str, str]:
        """Returns the CSS for the wrapper of the item."""
        wrapper_css: dict[str, str] = {
            'display': 'flex',
        }
        match self.h_align:
            case 'center':
                wrapper_css['justify-content'] = 'center'
        match self.v_align:
            case 'middle':
                wrapper_css['align-items'] = 'center'
        return wrapper_css

    def _item_css_properties(
        self,
        unit: str,
        preview: bool,
    ) -> dict[str, str]:
        """Returns the CSS for the item. ``preview`` marks the on-screen
        renders (editor, library thumbnail, tooltip) as opposed to printing."""
        # Items are absolutely positioned within their (full-size) wrapper so
        # that left/right/top/bottom offsets always apply - including centre and
        # middle, which are expressed as a 50% offset plus a translate. With the
        # default 0 offsets this renders identically to the previous model.
        item_css: dict[str, str] = {
            'opacity': f'{self.opacity}',
            'position': 'absolute',
        }
        # font-size must apply to subitems (for federation flags)
        if self.width:
            item_css['width'] = f'{self.width}{unit}'
        if self.height:
            item_css['height'] = f'{self.height}{unit}'
        transforms: list[str] = []
        match self.h_align:
            case 'left':
                item_css['left'] = f'{self.h_pos}{unit}'
            case 'right':
                item_css['right'] = f'{self.h_pos}{unit}'
            case 'center':
                item_css['left'] = '50%'
                transforms.append('translateX(-50%)')
        match self.v_align:
            case 'top':
                item_css['top'] = f'{self.v_pos}{unit}'
            case 'bottom':
                item_css['bottom'] = f'{self.v_pos}{unit}'
            case 'middle':
                item_css['top'] = '50%'
                transforms.append('translateY(-50%)')
        if self.max_width is not None:
            item_css['max-width'] = f'{self.max_width}{unit}'
        if self.rotate:
            transforms.append(f'rotate({self.rotate}deg)')
        if transforms:
            item_css['transform'] = ' '.join(transforms)
        if self.background_color:
            item_css['background-color'] = self.background_color
        if self.color:
            item_css['color'] = self.color
        if self.border_width and self.border_color:
            item_css['box-sizing'] = 'border-box'
            item_css['border'] = f'{self.border_width}{unit} solid {self.border_color}'
        return item_css

    def _inner_css_properties(
        self,
        unit: str,
    ) -> dict[str, str]:
        """Returns the CSS for the children of the item."""
        inner_css: dict[str, str] = {}
        return inner_css

    def render_css(
        self,
        template_css_class: str,
        unit: str,
        preview: bool,
    ) -> str:
        """Returns the CSS to print for the item."""
        return (
            f'.{template_css_class} .card-item-wrapper.{self.css_class} {{\n{";\n".join(f"{key}: {value};" for key, value in self._wrapper_css_properties().items())}\n}}\n'
            + f'.{template_css_class} .{self.css_class} .card-item {{\n{";\n".join(f"{key}: {value};" for key, value in self._item_css_properties(unit, preview).items())}\n}}\n'
            + f'.{template_css_class} .{self.css_class} .card-item * {{\n{";\n".join(f"{key}: {value};" for key, value in self._inner_css_properties(unit).items())}\n}}\n'
            + f'.{template_css_class} .{self.css_class} .card-item {{\n{self.css}\n}}\n'
        )

    def mirror(
        self,
        mirror_rotate: bool,
    ) -> Self:
        mirror_item: Self = copy.deepcopy(self)
        mirror_item.back = not self.back
        mirror_item.id = f'{self.id}_mirror'
        mirror_item.css_class = f'{self.css_class}-mirror'
        if not mirror_rotate:
            # real mirror mode (otherwise only rotate)
            match self.h_align:
                case 'left':
                    mirror_item._h_align = 'right'
                case 'right':
                    mirror_item._h_align = 'left'
            match self.text_align:
                case 'left':
                    mirror_item._text_align = 'right'
                case 'right':
                    mirror_item._text_align = 'left'
        return mirror_item


class PlaceCardText(PlaceCardItem):
    """A class to store a text item of a place card."""

    def __init__(
        self,
        data: TOMLContainer,
        section: str,
        template: 'PlaceCardTemplate',
    ):
        super().__init__(data, section, template)
        self.raw_text: str = data.get_str(
            section=section,
            prop='text',
        )
        self.preview_text: str = data.get_str(
            section=section,
            prop='preview_text',
            default='',
        )

    @property
    def type(self) -> str:
        return 'text'

    def allowed_properties(
        self,
    ) -> set[str]:
        return (
            super()
            .allowed_properties()
            .union(
                {
                    'text',
                    'preview_text',
                }
            )
        )

    def _inner_html(
        self,
        event: PlaceCardEvent,
        tournament: PlaceCardTournament,
        player: PlaceCardPlayer | None = None,
        board: PlaceCardBoard | None = None,
        pairing: PlaceCardPairing | None = None,
        team: PlaceCardTeam | None = None,
        preview: bool = False,
        editor: bool = False,
    ) -> str:
        if not self.display:
            return ''
        content: str = parse_jinja_string(
            template_string=self.preview_text
            if preview and self.preview_text
            else self.raw_text,
            context={
                'event': event,
                'tournament': tournament,
                'player': player,
                'board': board,
                'pairing': pairing,
                'team': team,
            },
            on_error=self.render_error('Jinja error'),
        )
        # In the editor an item that resolves to nothing (e.g. a field with no
        # value) would be invisible and impossible to select or drag. Show a
        # dimmed placeholder so it stays visible and editable.
        if editor and not content.strip():
            content = f'<span class="pc-empty-placeholder">{_("Text")}</span>'
        return f'<div class="card-item {self.css_class}">{content}</div>'

    def _item_css_properties(
        self,
        unit: str,
        preview: bool,
    ) -> dict[str, str]:
        item_css: dict[str, str] = {
            'font-size': f'{self.font_size}pt',
            'font-weight': 'bold' if self.bold else 'normal',
            'font-style': 'italic' if self.italic else 'normal',
        }
        decorations: list[str] = []
        if self.underline:
            decorations.append('underline')
        if self.strikethrough:
            decorations.append('line-through')
        item_css['text-decoration'] = ' '.join(decorations) if decorations else 'none'
        if self.uppercase:
            item_css['text-transform'] = 'uppercase'
        if self.font_family:
            item_css['font-family'] = self._font_family_css()
        if self.italic:
            # Italic glyphs overhang their advance width; without a
            # little slack the item's overflow:hidden clips the last
            # letter's slant.
            item_css['padding-right'] = '0.15em'
        match self.text_align:
            case 'left' | 'center' | 'right' | 'auto':
                item_css['text-align'] = self.text_align
        return super()._item_css_properties(unit, preview) | item_css

    def _inner_css_properties(
        self,
        unit: str,
    ) -> dict[str, str]:
        inner_css: dict[str, str] = {
            # the font style must be set to inner elements to apply to the federation flags.
            'font-size': f'{self.font_size}pt',
        }
        if self.font_family:
            # The template sets font-family on every element via `.<template> *`,
            # so an item override must also reach the item's children.
            inner_css['font-family'] = self._font_family_css()
        return super()._inner_css_properties(unit) | inner_css

    def _font_family_css(self) -> str:
        """The CSS font-family for this item. A bundled font file (``*.ttf``) is
        referenced by its embedded @font-face name; anything else is treated as a
        ready-made CSS font stack (a generic or web-safe family)."""
        if self.font_family.lower().endswith('.ttf'):
            return f'"{Path(self.font_family).stem}", sans-serif'
        return self.font_family

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self.raw_text=}, {self.back=})'


class PlaceCardImage(PlaceCardItem):
    """A class to store an image item of a place card."""

    def __init__(
        self,
        data: TOMLContainer,
        section: str,
        template: 'PlaceCardTemplate',
    ):
        super().__init__(data, section, template)
        self.image_paths: list[Path] = template.image_paths
        image_name: str = data.get_str(section=section, prop='image')
        image: Path | None = None
        if not (Path() / image_name).parent.samefile(Path()):
            logger.warning('Invalid image filename [%s].', image_name)
        else:
            for image_path in self.image_paths:
                file: Path = image_path / image_name
                if file.is_file():
                    image = file
                    break
                logger.debug('Image file [%s] not found.', file)
            if not image:
                logger.warning('Image file [%s] not found.', image_name)
        # No image chosen, a missing file, or one whose size can't be read: the
        # item renders as an empty outlined box everywhere - editor, preview and
        # print - rather than standing in something that would be printed.
        self.image: Path | None = image
        if not self.width and not self.height:
            self.width = self.height = 30.0 / (1.0 if template.unit == 'mm' else 25.4)
            logger.warning(
                'Use [width] or [height] in section [%s] to size the image (defaults to %sx%s).',
                section,
                self.width,
                self.height,
            )
        elif not self.width or not self.height:
            ratio: float = self.get_image_ratio(self.image) if self.image else 0.0
            if not ratio:
                if self.image:
                    logger.warning(
                        'Could not get ratio for image [%s].', self.image.name
                    )
                self.image = None
                ratio = 1.0
            if self.width:
                self.height = self.width / ratio
            else:
                assert self.height
                self.width = self.height * ratio
        self.has_image: bool = self.image is not None
        self.url = image_file_inline_url(self.image) if self.image else ''

    @staticmethod
    def get_image_ratio(image_file: Path) -> float:
        try:
            image = Image.open(image_file)
            return image.size[0] / image.size[1]
        except UnidentifiedImageError:
            # try to get the dimensions or view box of SVG files
            with open(image_file, 'rt') as f:
                svg_tree: ElementTree = ET.ElementTree(ET.fromstring(f.read()))
            if not svg_tree:
                return 0.0
            svg_root: ET.Element | None = svg_tree.getroot()
            if svg_root is None:
                return 0.0
            try:
                width = int(svg_root.attrib.get('width') or '0')
                height = int(svg_root.attrib.get('height') or '0')
                if width and height:
                    return width / height
            except ValueError:
                return 0.0
            view_box: str | None = svg_root.attrib.get('viewBox')
            if not view_box:
                return 0.0
            _, _, width_str, height_str = view_box.split()
            try:
                return int(width_str.strip() or '0') / int(height_str.strip() or '0')
            except ValueError:
                return 0.0

    @property
    def type(self) -> str:
        return 'image'

    def allowed_properties(
        self,
    ) -> set[str]:
        return (
            super()
            .allowed_properties()
            .union(
                {
                    'image',
                }
            )
        )

    def _inner_html(
        self,
        event: PlaceCardEvent,
        tournament: PlaceCardTournament,
        player: PlaceCardPlayer | None = None,
        board: PlaceCardBoard | None = None,
        pairing: PlaceCardPairing | None = None,
        team: PlaceCardTeam | None = None,
        preview: bool = False,
        editor: bool = False,
    ) -> str:
        if not self.has_image:
            # The icon needs the editor's icon font, so only the editor gets it.
            inner = '<i class="bi-image"></i>' if editor else ''
            return (
                f'<div class="card-item image pc-image-empty {self.css_class}">'
                f'{inner}</div>'
            )
        return f'<div class="card-item image {self.css_class}"></div>'

    def _item_css_properties(
        self,
        unit: str,
        preview: bool,
    ) -> dict[str, str]:
        item_css = super()._item_css_properties(unit, preview) | {
            'width': f'{self.width}{unit}',
            'height': f'{self.height}{unit}',
        }
        if not self.image:
            # On screen the empty box is outlined so the problem is visible;
            # printing leaves a blank space rather than marking the card.
            item_css |= {'background-color': 'transparent'}
            if preview:
                item_css |= {
                    'border': '1px dashed #adb5bd',
                    'box-sizing': 'border-box',
                }
            return item_css
        return item_css | {
            'background-image': f'url("{self.url}")',
            'background-size': 'contain',
        }

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self.image=}, {self.back=})'
