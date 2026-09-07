import copy
import logging
import re
from pathlib import Path
from typing import Any, Self

from common import (
    BASE_DIR,
    SharlyChessException,
    CUSTOM_PLACE_CARDS_DIR,
    EMBEDDED_PLACE_CARDS_DIR,
    EXAMPLE_PLACE_CARDS_DIR,
)
from common.i18n import _
from common.i18n.utils import parse_jinja_string, parse_jinja_template, normalized_key
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.event import Event
from data.print_documents.place_cards.crop_marks import (
    PlaceCardCropMarks,
    CornersPlaceCardCropMarks,
    NonePlaceCardCropMarks,
)
from data.print_documents.place_cards.data import (
    PlaceCardBoard,
    PlaceCardPlayer,
    PlaceCardEvent,
    PlaceCardTournament,
    PlaceCardPairing,
    PlaceCardTeam,
)
from data.print_documents.place_cards.item_style import PlaceCardItemStyle
from data.print_documents.place_cards.items import (
    PlaceCardItem,
    PlaceCardImage,
    PlaceCardText,
)
from data.print_documents.place_cards.toml_container import TOMLContainer
from data.print_documents.place_cards.types import PlaceCardType
from data.player import Player
from data.tournament import Tournament
from utils.enum import Extension
from utils.file import ttf_file_inline_url, image_file_inline_url

logger: logging.Logger = get_logger()

# Varied sample identities for the editor's "example data" selector: a short
# name, a long/hyphenated one, accents... so the user can check the layout
# against real-world names, not one fixed placeholder.
_EXAMPLE_PLAYER_NAMES: list[tuple[str, str]] = [
    ('Emma', 'Roy'),
    ('Jean-Christophe', 'de la Tour-Boulingrin'),
    ('Li', 'Wu'),
    ('María-José', 'García-Hernández'),
]
_EXAMPLE_TEAM_NAMES: list[str] = [
    'Les Tours',
    'Cavaliers de Lyon',
    'Échecs Club Paris-Ouest',
    'Fous Volants',
]
_EXAMPLE_CLUB_NAMES: list[str] = [
    'Échiquier de Bourgogne',
    'Club de la Tour Noire',
    'Cercle des Échecs de Lyon',
    'Association Caïssa',
]


class PlaceCardTemplate(PlaceCardItemStyle):
    """A class representing the place cards templates."""

    def __init__(
        self,
        embedded: bool,
        toml_file: Path,
    ):
        from data.print_documents import PrintPlaceCardTypeManager
        from data.print_documents.place_cards.types import (
            PlaceCardType,
            PlayerCardType,
        )

        self.embedded: bool = embedded
        self.id: str
        self.default_font_file = (
            BASE_DIR / 'src/web/static/fonts/AtkinsonHyperlegibleNextVF-Variable.ttf'
        )
        if self.embedded:
            self.id = toml_file.stem
        else:
            self.id = f'{toml_file.parent.name}/{toml_file.stem}'
        self.css_class: str = f'template-{re.sub(r"[^a-zA-Z0-9_\-]", "-", self.id)}'
        self.font_paths: list[Path] = [
            toml_file.parent / 'fonts',
            BASE_DIR / 'src/web/static/fonts',
        ]
        self.image_paths: list[Path] = [
            toml_file.parent / 'images',
            BASE_DIR / 'src/web/static/images',
        ]
        custom_data = TOMLContainer(toml_file)
        super().__init__(custom_data)
        self.type: PlaceCardType = PrintPlaceCardTypeManager().get_object(
            custom_data.get_str(
                'type',
                default=PlayerCardType.static_id(),
                values=PrintPlaceCardTypeManager().ids(),
            )
        )
        self._name: str = custom_data.get_str('name', default='') or toml_file.stem
        self.creator: str = custom_data.get_str('creator', default=_('Unknown'))
        self.unit: str = custom_data.get_str(
            'unit',
            default='mm',
            values=[
                'mm',
                'in',
            ],
        )
        self.width: float = custom_data.get_float('width', default=116.0)
        self.height: float = custom_data.get_float('height', default=36.0)
        self.padding: float = custom_data.get_float('padding', default=2.0)
        self.css: str = custom_data.get_str('css', default='')
        self.font: str = custom_data.get_str('font', default='')
        self.two_sided: bool = custom_data.get_bool('two_sided', default=False)
        items: list[PlaceCardItem] = []
        for section in custom_data.get_sections():
            if section == 'default':
                pass
            elif 'image' in custom_data.get_section_properties(section):
                items.append(
                    PlaceCardImage(
                        custom_data,
                        section=section,
                        template=self,
                    )
                )
            else:
                items.append(
                    PlaceCardText(
                        custom_data,
                        section=section,
                        template=self,
                    )
                )
        # Declaration order is paint order: the last item of the file is drawn
        # on top. The editor reorders the sections to change the stacking.
        self.items: list[PlaceCardItem] = items

    def allowed_properties(
        self,
    ) -> set[str]:
        return (
            super()
            .allowed_properties()
            .union(
                {
                    'type',
                    'name',
                    'creator',
                    'unit',
                    'width',
                    'height',
                    'padding',
                    'css',
                    'font',
                    'two_sided',
                }
            )
        )

    @property
    def name(self) -> str:
        return parse_jinja_string(template_string=self._name)

    @property
    def template_name(self) -> str:
        return '/admin/print/place_cards/template.html'

    @property
    def is_two_sided(self) -> bool:
        """Effectively two-sided: the explicit flag, or any displayed back item
        (built-in two-sided templates use a back item rather than the flag)."""
        return self.two_sided or any(item.back and item.display for item in self.items)

    def available_fonts(self) -> list[Path]:
        """Every .ttf available to this template (its own fonts/ folder first,
        then the shared fonts), de-duplicated by file name."""
        seen: set[str] = set()
        fonts: list[Path] = []
        for font_path in self.font_paths:
            if not font_path.is_dir():
                continue
            for file in sorted(font_path.glob('*.ttf')):
                if file.name not in seen:
                    seen.add(file.name)
                    fonts.append(file)
        return fonts

    def resolve_font(self, name: str) -> Path | None:
        """Resolve a font file name to a Path within the template's font paths."""
        if not name or not (Path() / name).parent.samefile(Path()):
            return None
        for font_path in self.font_paths:
            file = font_path / name
            if file.is_file():
                return file
        return None

    @property
    def font_file(self) -> Path:
        if not self.font:
            return self.default_font_file
        if not (Path() / self.font).parent.samefile(Path()):
            logger.debug('Invalid font filename [%s].', self.font)
            return self.default_font_file
        for font_path in self.font_paths:
            file: Path = font_path / self.font
            if not file.is_file():
                logger.warning('Font file [%s] not found.', file)
                continue
            return file
        logger.warning('Font file [%s] not found.', self.font)
        return self.default_font_file

    def render_css(
        self,
        place_card_crop_marks: PlaceCardCropMarks,
        back_side: bool,
        federations: set[str],
    ) -> str:
        file: Path = self.font_file
        # Register @font-face for every font actually used: the template font
        # plus any per-item font overrides. (@font-face can't share a dict key,
        # so these are emitted as a separate string below.)
        used_fonts: dict[str, Path] = {file.stem: file}
        for item in self.items:
            item_font = self.resolve_font(getattr(item, 'font_family', ''))
            if item_font is not None:
                used_fonts.setdefault(item_font.stem, item_font)
        font_faces: str = '\n'.join(
            f'@font-face {{\n\tfont-family: "{font.stem}";\n'
            f'\tsrc: url("{ttf_file_inline_url(font)}") format("truetype");\n}}'
            for font in used_fonts.values()
        )
        css_properties: dict[str, dict[str, str]] = {
            f'.{self.css_class} *': {
                'font-family': f'{file.stem}, sans-serif',
            },
            f'.card-wrapper.{self.css_class}': {
                'float': 'left',
                'display': 'flex',
                'flex-direction': 'column',
                'width': f'{self.width}{self.unit}',
                'height': f'{(2 if back_side else 1) * self.height}{self.unit}',
                'page-break-inside': 'avoid',
                'position': 'relative',
            },
            f'.{self.css_class} .card': {
                'display': 'grid',
                'width': f'{self.width}{self.unit}',
                'height': f'{self.height}{self.unit}',
                'grid-template-columns': f'{self.padding}{self.unit} auto {self.padding}{self.unit}',
                'grid-auto-flow': 'row',
            },
            f'.{self.css_class} .card.side-back .card-content': {
                'transform': 'rotate(180deg)',
                'transform-origin': 'center center',
            },
            f'.{self.css_class} .card-cell.top, .{self.css_class} .card-cell.bottom': {
                'height': f'{self.padding}{self.unit}',
            },
            f'.{self.css_class} .card-cell.middle, .{self.css_class} .card-content': {
                'height': f'{self.height - 2 * self.padding}{self.unit}',
            },
            f'.{self.css_class} .card-cell.left, .{self.css_class} .card-cell.right': {
                'width': f'{self.padding}{self.unit}',
            },
            f'.{self.css_class} .card-cell.center, .{self.css_class} .card-content': {
                'width': f'{self.width - 2 * self.padding}{self.unit}',
            },
            f'.{self.css_class} .card-content': {
                'position': 'relative',
                'background-color': 'rgba(255, 255, 255, 0.6)',
            },
            f'.{self.css_class} .card-item-wrapper': {
                'position': 'absolute',
                'top': '0.0',
                'left': '0.0',
                'overflow': 'hidden',
                'white-space': 'nowrap',
                'text-overflow': 'ellipsis',
                'background-color': 'transparent',
                'width': f'{self.width - 2 * self.padding}{self.unit}',
                'height': f'{self.height - 2 * self.padding}{self.unit}',
            },
            f'.{self.css_class} .card-item': {
                'overflow': 'hidden',
                'white-space': 'nowrap',
                'text-overflow': 'ellipsis',
                'background-color': 'transparent',
                'max-width': f'{self.width - 2 * self.padding}{self.unit}',
            },
            f'.{self.css_class} .federation-flag': {
                'height': '0.7em',
                'width': '0.93em',
            },
        }
        css_properties |= {
            f'.federation-flag.{federation}': {
                'background-image': f'url("{image_file_inline_url(BASE_DIR / f"src/web/static/images/federations/{federation}.svg")}")'
            }
            for federation in federations
            if federation in SharlyChessConfig().federations
        }
        return (
            font_faces
            + '\n'
            + '\n'.join(
                f'{locator} {{\n{"\n".join(f"\t{key}: {value};" for key, value in properties.items())}\n}}'
                for locator, properties in css_properties.items()
            )
            + place_card_crop_marks.render_css(self.css_class)
            + self.css
        )

    @staticmethod
    def get_federations(
        players: list[PlaceCardPlayer],
        pairings: list[PlaceCardPairing],
    ) -> set[str]:
        """Return the federations of the players in the template data."""
        return (
            set(
                pairing.white_player.federation
                for pairing in pairings
                if pairing.black_player
            )
            .union(
                set(
                    pairing.black_player.federation
                    for pairing in pairings
                    if pairing.black_player
                )
            )
            .union(set(player.federation for player in players))
        )

    def _template_context(
        self,
        event: PlaceCardEvent,
        tournament: PlaceCardTournament,
        round_: int,
        mirror: bool,
        place_card_crop_marks: PlaceCardCropMarks,
        players: list[PlaceCardPlayer],
        boards: list[PlaceCardBoard],
        pairings: list[PlaceCardPairing],
        teams: list[PlaceCardTeam],
        card_width: str,
        card_height: str,
        preview: bool,
    ) -> dict[str, Any]:
        items: list[PlaceCardItem] = copy.deepcopy(self.items)
        if mirror:
            # duplicate all the items on the back side
            back_items: list[PlaceCardItem] = [
                PlaceCardItem.mirror(item, self.type.mirror_rotate) for item in items
            ]
            items += back_items
        back_side: bool = self.two_sided or any(
            item.back and item.display for item in items
        )
        federations: set[str] = self.get_federations(players, pairings)
        return {
            'event': event,
            'tournament': tournament,
            'round': round_,
            'back_side': back_side,
            'unit': self.unit,
            'template_css_class': self.css_class,
            'template_css': self.render_css(
                place_card_crop_marks, back_side, federations
            ),
            'card_width': card_width,
            'card_height': card_height,
            'players': players,
            'boards': boards,
            'pairings': pairings,
            'teams': teams,
            'items': items,
            'preview': preview,
        }

    def template_context(
        self,
        event: Event,
        tournament: Tournament,
        round_: int,
        mirror: bool,
        place_card_crop_marks: PlaceCardCropMarks,
        board_numbers: set[int],
        player_ids: list[int],
    ) -> dict[str, Any]:
        return self._template_context(
            event=PlaceCardEvent(event),
            tournament=PlaceCardTournament(tournament),
            round_=round_,
            mirror=mirror,
            place_card_crop_marks=place_card_crop_marks,
            players=self.type.tournament_players(tournament, player_ids=player_ids),
            boards=self.type.boards(tournament, board_numbers=board_numbers),
            pairings=self.type.pairings(
                tournament, round_, board_numbers=board_numbers
            ),
            teams=self.type.teams(tournament),
            card_width=f'{self.width}{self.unit}',
            card_height=f'{(2 if mirror or self.is_two_sided else 1) * self.height}{self.unit}',
            preview=False,
        )

    def preview(self, crop_marks: bool = True) -> str:
        """Returns a string to preview the template with mock data. With
        ``crop_marks`` (the hover tooltip) the card renders at half-scale with
        corner crop marks and a 1mm bleed margin, mimicking the printed sheet.
        Without them (the library thumbnail) it renders edge-to-edge, no marks."""
        faces = 2 if self.is_two_sided else 1
        margin = (1.0 if crop_marks else 0.0) * (1.0 if self.unit == 'mm' else 1 / 25.4)
        return parse_jinja_template(
            '/admin/print/place_cards/tooltip_preview.html',
            self._template_context(
                event=PlaceCardEvent(),
                tournament=PlaceCardTournament(),
                round_=1,
                mirror=False,
                place_card_crop_marks=(
                    CornersPlaceCardCropMarks()
                    if crop_marks
                    else NonePlaceCardCropMarks()
                ),
                players=self.type.preview_players(),
                boards=self.type.preview_boards(),
                pairings=self.type.preview_pairings(),
                teams=self.type.preview_teams(),
                card_width=f'{self.width / 2 + margin}{self.unit}',
                card_height=f'{faces * self.height / 2 + margin}{self.unit}',
                preview=True,
            ),
        )

    def editor_card_html(self, example: int = 0) -> str:
        """Render a single sample card as an inline HTML fragment (no iframe)
        for the visual editor. Each item is wrapped with a ``.pc-edit-item``
        element carrying its section id so the editor can attach drag handles.
        ``example`` seeds the sample data so the user can preview several."""
        import random

        scale: int = 2 if self.is_two_sided else 1
        # The sample data is randomised; seed it (per chosen example) so it stays
        # identical across the re-renders that follow every drag/add/delete.
        random_state = random.getstate()
        random.seed(example)
        try:
            players = self.type.preview_players()
            boards = self.type.preview_boards()
            pairings = self.type.preview_pairings()
            teams = self.type.preview_teams()
        finally:
            random.setstate(random_state)
        self._apply_example(example, players, boards, pairings, teams)
        context = self._template_context(
            event=PlaceCardEvent(),
            tournament=PlaceCardTournament(),
            round_=1,
            mirror=False,
            place_card_crop_marks=NonePlaceCardCropMarks(),
            players=players,
            boards=boards,
            pairings=pairings,
            teams=teams,
            card_width=f'{self.width}{self.unit}',
            card_height=f'{scale * self.height}{self.unit}',
            preview=True,
        )
        context['editor'] = True
        context['padding'] = self.padding
        return parse_jinja_template(
            '/admin/print/place_cards/place_cards.html', context
        )

    @staticmethod
    def _name_player(player: PlaceCardPlayer, example: int) -> None:
        """Give the player a full, distinct identity for an example: name, club
        and team, so every field token resolves to a real (non-placeholder)
        value that varies from one example to the next."""
        first, last = _EXAMPLE_PLAYER_NAMES[example % len(_EXAMPLE_PLAYER_NAMES)]
        player.first_name = first
        player.last_name = last
        player.full_name = Player.player_full_name(first, last)
        player.club = _EXAMPLE_CLUB_NAMES[example % len(_EXAMPLE_CLUB_NAMES)]
        player.team_name = _EXAMPLE_TEAM_NAMES[example % len(_EXAMPLE_TEAM_NAMES)]

    def _apply_example(
        self,
        example: int,
        players: list[PlaceCardPlayer],
        boards: list[PlaceCardBoard],
        pairings: list[PlaceCardPairing],
        teams: list[PlaceCardTeam],
    ) -> None:
        """Give each example a distinct, recognisable identity (name, board
        number, team name) so the selector previews real variety rather than
        the same placeholder with only a different rating."""
        for player in players:
            self._name_player(player, example)
        for pairing in pairings:
            if pairing.white_player:
                self._name_player(pairing.white_player, example)
            if pairing.black_player:
                self._name_player(pairing.black_player, example + 1)
        for offset, board in enumerate(boards):
            board.number = example + 1 + offset
        for offset, team in enumerate(teams):
            team.name = _EXAMPLE_TEAM_NAMES[
                (example + offset) % len(_EXAMPLE_TEAM_NAMES)
            ]

    def example_label(self, example: int) -> str:
        """A short human label for one example, shown on the selector button
        (the primary entity's identity for this template's card type)."""
        import random

        random_state = random.getstate()
        random.seed(example)
        try:
            players = self.type.preview_players()
            boards = self.type.preview_boards()
            pairings = self.type.preview_pairings()
            teams = self.type.preview_teams()
        finally:
            random.setstate(random_state)
        self._apply_example(example, players, boards, pairings, teams)
        if players:
            return players[0].full_name
        if pairings:
            pairing = pairings[0]
            white = pairing.white_player.full_name if pairing.white_player else '?'
            black = pairing.black_player.full_name if pairing.black_player else '?'
            return f'{white} – {black}'
        if boards:
            return _('Board {number}').format(number=boards[0].number)
        if teams:
            return teams[0].name
        return str(example + 1)

    @classmethod
    def load(
        cls,
        template_id: str,
    ) -> Self:
        """Loads a place card template from an ID."""
        template_file: Path
        file_name = f'{template_id}.{Extension.TEMPLATE}'
        if embedded := ('/' not in template_id):
            template_file = EMBEDDED_PLACE_CARDS_DIR / file_name
            if template_file.exists():
                return cls(embedded, template_file)
        template_file = CUSTOM_PLACE_CARDS_DIR / file_name
        if template_file.exists():
            return cls(embedded, template_file)
        template_file = EXAMPLE_PLACE_CARDS_DIR / file_name
        if template_file.exists():
            return cls(embedded, template_file)
        # Should never happen
        raise SharlyChessException(
            f'Could not load place card template file [{template_file}].'
        )

    @classmethod
    def get_place_card_templates_by_id(
        cls,
        *,
        custom: bool = True,
        examples: bool = False,
    ) -> dict[str, Self]:
        """Returns a dict of all the place card templates."""
        place_card_templates_by_id: dict[str, PlaceCardTemplate] = {}
        for template_file in EMBEDDED_PLACE_CARDS_DIR.glob(f'*.{Extension.TEMPLATE}'):
            template_id: str = template_file.stem
            place_card_templates_by_id[template_id] = cls.load(template_id)
        # custom templates override embedded ones
        if custom:
            for template_file in CUSTOM_PLACE_CARDS_DIR.glob(
                f'*/*.{Extension.TEMPLATE}'
            ):
                template_id: str = f'{template_file.parent.name}/{template_file.stem}'
                place_card_templates_by_id[template_id] = cls.load(template_id)
        # example templates are loaded at the very end
        if examples:
            for template_file in EXAMPLE_PLACE_CARDS_DIR.glob(
                f'*/*.{Extension.TEMPLATE}'
            ):
                template_id: str = f'{template_file.parent.name}/{template_file.stem}'
                place_card_templates_by_id[template_id] = cls.load(template_id)
        return place_card_templates_by_id  # type: ignore

    @classmethod
    def get_place_card_templates_by_type(
        cls,
        *,
        custom: bool = True,
        examples: bool = False,
    ) -> dict[PlaceCardType, list[Self]]:
        """Returns a dict of all the place cards templates for each type."""
        from data.print_documents import PrintPlaceCardTypeManager

        place_card_templates: list[PlaceCardTemplate] = list(
            cls.get_place_card_templates_by_id(
                custom=custom,
                examples=examples,
            ).values()
        )
        return {
            place_card_type: sorted(
                (
                    place_card_template  # type: ignore
                    for place_card_template in place_card_templates
                    if place_card_template.type == place_card_type
                ),
                key=lambda template: (
                    template.embedded,
                    template.id if template.embedded else normalized_key(template.name),
                ),
            )
            for place_card_type in PrintPlaceCardTypeManager().objects()
        }

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self.id=}, {self.embedded=}, {self.template_name=}, {self.creator=})'
