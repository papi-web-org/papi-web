import re
from abc import ABC, abstractmethod
from functools import cached_property
from types import UnionType
from typing import TYPE_CHECKING, Optional, override, Any

from common.exception import OptionError
from common.i18n import _
from data.event import SharlyChessConfig
from data.print_documents.pairing_styles import BoardsPairingStyle, PairingStyle
from data.print_documents.place_cards.crop_marks import (
    CornersPlaceCardCropMarks,
    PlaceCardCropMarks,
)
from data.print_documents.place_cards.types import (
    PlayerCardType,
    PlaceCardType,
)
from data.print_documents.player_sorters import (
    GridPlayerSorter,
    ListPlayerSorter,
    NameListPlayerSorter,
    RankGridPlayerSorter,
    RankTeamGridSorter,
    TeamGridSorter,
)
from data.print_documents.player_splitters import PlayerSplitter, NoSplitPlayerSplitter
from data.print_documents.qrcode_types import NetworkQRCodeType, QRCodeType
from data.print_documents.individual_teams import (
    IndividualTeamType,
    ClubIndividualTeamType,
)
from utils.option import Option

if TYPE_CHECKING:
    from data.event import Event
    from data.print_documents import PrintIndividualTeamTypeManager
    from data.print_documents.documents import PlaceCardTemplate


class PrintOption(Option, ABC):
    """Parent class of all the options of print documents."""

    def __init__(self, event: Optional['Event'], value: Any | None = None):
        super().__init__(value)
        self.event = event

    @property
    def template_name(self) -> str:
        return f'/admin/event/print_options/{self.template_file_name}.html'

    @property
    def template_file_name(self) -> str:
        """Name of the file of the template representing the option."""
        return self.id.replace('-', '_')


class TournamentPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'tournament'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        # This is managed by the print controller
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is None:
            raise OptionError(_('Please choose the tournament.'), self)


class TournamentsPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'tournaments'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        # This is managed by the print controller
        return None


class PlayerPrintOption(PrintOption, ABC):
    @property
    def template_file_name(self) -> str:
        return 'player'

    @property
    def default_value(self) -> Any:
        return None

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    @abstractmethod
    def mandatory(self) -> bool:
        """Returns True if the selecting a player is needed to print."""

    @override
    def validate(self):
        super().validate()
        if self.mandatory and self.value is None:
            raise OptionError(_('Please choose a player.'), self)


class MandatoryPlayerPrintOption(PlayerPrintOption):
    @staticmethod
    def static_id() -> str:
        return 'mandatory-player'

    @property
    def mandatory(self) -> bool:
        return True


class OptionalPlayerPrintOption(PlayerPrintOption):
    @staticmethod
    def static_id() -> str:
        return 'optional-player'

    @property
    def mandatory(self) -> bool:
        return False


class PlayersPrintOption(PrintOption, ABC):
    @property
    @abstractmethod
    def mandatory(self) -> bool:
        """Returns True if at least one player must be selected."""

    @property
    def template_file_name(self) -> str:
        return 'players'

    @property
    def type(self) -> type | UnionType:
        return list[int]

    @property
    def default_value(self) -> Any:
        return []

    @override
    def validate(self):
        self._validate_list_type(int)
        if self.mandatory and not self.value:
            raise OptionError(_('Please select at least one player.'), self)


class OptionalPlayersPrintOption(PlayersPrintOption):
    @staticmethod
    def static_id() -> str:
        return 'optional-players'

    @property
    def mandatory(self) -> bool:
        return False


class TeamsPrintOption(PrintOption, ABC):
    @property
    @abstractmethod
    def mandatory(self) -> bool:
        """Returns True if at least one team must be selected."""

    @property
    def template_file_name(self) -> str:
        return 'teams'

    @property
    def type(self) -> type | UnionType:
        return list[int]

    @property
    def default_value(self) -> Any:
        return []

    @override
    def validate(self):
        self._validate_list_type(int)
        if self.mandatory and not self.value:
            raise OptionError(_('Please select at least one team.'), self)


class OptionalTeamsPrintOption(TeamsPrintOption):
    @staticmethod
    def static_id() -> str:
        return 'optional-teams'

    @property
    def mandatory(self) -> bool:
        return False


class RoundPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'round'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is not None and self.value < 1:
            raise OptionError(_('A positive integer is expected.'), self)


class MatchSheetSelectionPrintOption(PrintOption):
    """List of team_board ids to print, or empty to print every team
    match in the round."""

    @staticmethod
    def static_id() -> str:
        return 'match-sheet-selection'

    @property
    def type(self) -> type | UnionType:
        return list[int]

    @property
    def default_value(self) -> Any:
        return []

    @override
    def validate(self):
        self._validate_list_type(int)

    def match_options_by_tournament_round(
        self,
    ) -> 'dict[int, dict[int, list[tuple[int, str]]]]':
        """``{tournament_id: {round: [(id, label), ...]}}`` — every
        paired team match in every team tournament of the event (one
        row per board for flat fixed-table systems). Used by the print
        modal to show only the rows matching the currently-selected
        tournament + round."""
        result: dict[int, dict[int, list[tuple[int, str]]]] = {}
        if self.event is None or not self.event.is_team_event:
            return result
        for tournament in self.event.tournaments_by_id.values():
            if not tournament.is_team_tournament:
                continue
            flat = not tournament.pairing_system.paired_by_team
            by_round: dict[int, list[tuple[int, str]]] = {}
            for round_ in range(1, tournament.rounds + 1):
                rows: list[tuple[int, str]] = []
                if flat:
                    for board in sorted(
                        tournament.get_round_boards(round_), key=lambda b: b.index
                    ):
                        wtp = board.optional_white_tournament_player
                        btp = board.black_tournament_player
                        rows.append(
                            (
                                board.identifier,
                                f'{board.number}. '
                                f'{wtp.full_name if wtp else ""} - '
                                f'{btp.full_name if btp else ""}',
                            )
                        )
                else:
                    for tb in tournament.get_round_team_boards(round_):
                        stb = tb.stored_team_board
                        if stb.team_b_id is None or tb.team_b is None:
                            continue
                        rows.append(
                            (
                                tb.id,
                                f'{tb.display_number}. '
                                f'{tb.team_a.name} - {tb.team_b.name}',
                            )
                        )
                if rows:
                    by_round[round_] = rows
            if by_round:
                result[tournament.id] = by_round
        return result

    def default_round_by_tournament(self) -> 'dict[int, int]':
        """``{tournament_id: round}`` the selector falls back to when no
        round is entered — the current round, matching the document's
        ``at_round`` (``RoundPrintOption.value or current_round``). Without
        this the modal would look up an empty round and show no matches
        until a round is typed."""
        result: dict[int, int] = {}
        if self.event is None or not self.event.is_team_event:
            return result
        for tournament in self.event.tournaments_by_id.values():
            if not tournament.is_team_tournament:
                continue
            result[tournament.id] = tournament.current_round
        return result


class MatchSheetArbiterPrintOption(PrintOption):
    """Arbiter whose name is printed on the match-sheet signature line,
    chosen from the event's team-tournament staff (chief + deputy
    arbiters). Empty falls back to the tournament's chief arbiter."""

    @staticmethod
    def static_id() -> str:
        return 'match-sheet-arbiter'

    @property
    def template_file_name(self) -> str:
        return 'match_sheet_arbiter'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @property
    def label(self) -> str:
        return _('Arbiter:')

    @property
    def default_text(self) -> str:
        return _('Chief arbiter')

    def arbiter_options(self) -> 'dict[str, str]':
        """``{account_id: full_name}`` for all the arbiters
        of the event's team tournaments — the staff that can sign a sheet."""
        result: dict[str, str] = {}
        if self.event is None or not self.event.is_team_event:
            return result
        for tournament in self.event.tournaments_by_id.values():
            if not tournament.is_team_tournament:
                continue
            arbiters = []
            if tournament.chief_arbiter is not None:
                arbiters.append(tournament.chief_arbiter)
            arbiters.extend(tournament.deputy_arbiters)
            arbiters.extend(tournament.arbiters)
            for account in arbiters:
                result.setdefault(str(account.id), account.full_name)
        return result


class TeamBergerGridPlayersPrintOption(PrintOption):
    """If on, the team Berger grid details down to the players: one row
    per player (grouped by team), individual game results in the
    cells."""

    @staticmethod
    def static_id() -> str:
        return 'team-berger-grid-players'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class PlayerSplitPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'player-split'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return NoSplitPlayerSplitter.static_id()

    @property
    def player_splitter_options(self) -> dict[str, str]:
        from data.print_documents import PrintPlayerSplitterManager

        return PrintPlayerSplitterManager(self.event).options()

    @cached_property
    def player_splitter(self) -> PlayerSplitter:
        from data.print_documents import PrintPlayerSplitterManager

        return PrintPlayerSplitterManager(self.event).get_object(self.value)

    @override
    def validate(self):
        try:
            _splitter = self.player_splitter
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown player splitter: {self.value}', self)


class GridPlayerSortPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'grid-player-sort'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return RankGridPlayerSorter.static_id()

    @property
    def grid_player_sorter_options(self) -> dict[str, str]:
        from data.print_documents import PrintGridPlayerSorterManager

        return PrintGridPlayerSorterManager(self.event).options()

    @cached_property
    def grid_player_sorter(self) -> GridPlayerSorter:
        from data.print_documents import PrintGridPlayerSorterManager

        return PrintGridPlayerSorterManager(self.event).get_object(self.value)

    @override
    def validate(self):
        super().validate()
        try:
            _sorter = self.grid_player_sorter
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown grid player sorter: {self.value}', self)


class TeamGridSortPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'team-grid-sort'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return RankTeamGridSorter.static_id()

    @property
    def team_grid_sorter_options(self) -> dict[str, str]:
        from data.print_documents import PrintTeamGridSorterManager

        return PrintTeamGridSorterManager(self.event).options()

    @cached_property
    def team_grid_sorter(self) -> TeamGridSorter:
        from data.print_documents import PrintTeamGridSorterManager

        return PrintTeamGridSorterManager(self.event).get_object(self.value)

    @override
    def validate(self):
        super().validate()
        try:
            _sorter = self.team_grid_sorter
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown team grid sorter: {self.value}', self)


class ListPlayerSortPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'list-player-sort'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return NameListPlayerSorter.static_id()

    @property
    def list_player_sorter_options(self) -> dict[str, str]:
        from data.print_documents import PrintListPlayerSorterManager

        return PrintListPlayerSorterManager(self.event).options()

    @cached_property
    def list_player_sorter(self) -> ListPlayerSorter:
        from data.print_documents import PrintListPlayerSorterManager

        return PrintListPlayerSorterManager(self.event).get_object(self.value)

    @override
    def validate(self):
        super().validate()
        try:
            _sorter = self.list_player_sorter
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown list player sorter: {self.value}', self)


class FixedBoardOrderPrintOption(PrintOption):
    """Ordering of the board pairings when the round is numbered compactly
    around fixed boards: by displayed board number (default) or in the natural
    pairing order. Only relevant when a tournament has fixed boards and isn't
    numbered with gaps."""

    BY_BOARD_NUMBER = 'board'
    NATURAL = 'natural'

    @staticmethod
    def static_id() -> str:
        return 'fixed-board-order'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return self.BY_BOARD_NUMBER

    @property
    def order_options(self) -> dict[str, str]:
        return {
            self.BY_BOARD_NUMBER: _('Board number'),
            self.NATURAL: _('Natural (pairing order)'),
        }

    @property
    def pairing_document_id(self) -> str:
        from data.print_documents.documents import PairingPrintDocument

        return PairingPrintDocument.static_id()

    @property
    def boards_pairing_style_id(self) -> str:
        return BoardsPairingStyle.static_id()

    @property
    def applies(self) -> bool:
        """Whether the option is relevant for the current event: at least one
        tournament is numbered compactly and has a player on a fixed board."""
        if self.event is None:
            return False
        return any(
            not tournament.leave_fixed_board_holes
            and any(player.fixed for player in tournament.tournament_players)
            for tournament in self.event.tournaments
        )

    @override
    def validate(self):
        super().validate()
        if self.value not in self.order_options:
            # Untranslated; should not happen via UI
            raise OptionError(f'Unknown fixed board order: {self.value}', self)


class PairingStylePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'pairing-style'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        return BoardsPairingStyle.static_id()

    @property
    def pairing_style_options(self) -> dict[str, str]:
        from data.print_documents import PrintPairingStyleManager

        return PrintPairingStyleManager(self.event).options()

    @cached_property
    def pairing_style(self) -> PairingStyle:
        from data.print_documents import PrintPairingStyleManager

        return PrintPairingStyleManager(self.event).get_object(self.value)

    @override
    def validate(self):
        super().validate()
        try:
            _style = self.pairing_style
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown pairing style: {self.value}', self)


class ShowWarningsPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'show-warnings'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return True


class KnockoutSchedulePrintOption(PrintOption):
    """On the knock-out bracket document: show the chronological schedule
    (matches round by round) instead of the bracket diagram."""

    @staticmethod
    def static_id() -> str:
        return 'knockout-schedule'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class NonMonetaryPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'non-monetary'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class FederationPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'federation'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class ClubThresholdPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'club-threshold'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is not None and self.value < 0:
            raise OptionError(_('A positive value is expected.'), self)


class Rule143ExemptionPrintOption(PrintOption):
    """Selects which FIDE 1.4.3 exemption (a/b/c) applies, based on the
    type of event the tournament is part of. The arbiter sets this on the
    print doc — there's no automatic detection because nothing in the
    tournament metadata identifies a "National Championship final" or a
    "Zonal".

    Spec mapping:
    - 'none'  → no exemption (default).
    - '1.4.3a' → National men's/open championship final stage.
                  Exempts 1.4.3 ONLY for players from the event's
                  registering federation.
    - '1.4.3b' → National team championships.
                  Same player filter as 1.4.3a.
    - '1.4.3c' → Zonal / Sub-zonal tournament.
                  Exempts 1.4.3 for ALL players (no federation filter).

    None of a/b/c exempt 1.4.4 — only 1.4.3d does that (see
    `compute_big_tournament_exemption`).
    """

    @staticmethod
    def static_id() -> str:
        return 'rule-143-exemption'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return 'none'

    @property
    def exemption_choices(self) -> dict[str, str]:
        """{value: label} for the dropdown. Labels include the spec
        reference so the arbiter sees the rule being invoked."""
        return {
            'none': _('Regular event'),
            '1.4.3a': _('National championship final (1.4.3a)'),
            '1.4.3b': _('National team championship (1.4.3b)'),
            '1.4.3c': _('Zonal or sub-zonal (1.4.3c)'),
        }

    @override
    def validate(self):
        super().validate()
        if self.value not in ('none', '1.4.3a', '1.4.3b', '1.4.3c'):
            # Untranslated; should not happen via UI
            raise OptionError(f'Unknown 1.4.3 exemption: {self.value}', self)


class NormsForecastSortPrintOption(PrintOption):
    """Row ordering for the forecast table of the Tournament Norms Summary.

    - 'rank'  → current standings position (default).
    - 'table' → board number of the forecast round's pairing.
    - 'name'  → alphabetical by player name.
    """

    @staticmethod
    def static_id() -> str:
        return 'norms-forecast-sort'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return 'rank'

    @property
    def sort_choices(self) -> dict[str, str]:
        """{value: label} for the dropdown."""
        return {
            'rank': _('Ranking'),
            'table': _('Table number'),
            'name': _('Alphabetical'),
        }

    @override
    def validate(self):
        super().validate()
        if self.value not in ('rank', 'table', 'name'):
            # Untranslated; should not happen via UI
            raise OptionError(f'Unknown forecast sort: {self.value}', self)


class NormChoicePrintOption(PrintOption):
    """Which norm to render in the Norm Calculation Details document.
    The detail doc shows only one norm at a time, so the arbiter picks
    which one to audit via the deep-link from the IT1."""

    @staticmethod
    def static_id() -> str:
        return 'norm-choice'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return 'GM'

    @property
    def norm_choices(self) -> dict[str, str]:
        """{value: label} mapping for the dropdown. Mirrors `TitleNorm`'s
        four members in `values()` order (WIM, WGM, IM, GM)."""
        from utils.enum import TitleNorm

        return {tn.name: tn.name for tn in TitleNorm.values()}

    @override
    def validate(self):
        super().validate()
        from utils.enum import TitleNorm

        valid = {tn.name for tn in TitleNorm.values()}
        if self.value not in valid:
            # Untranslated, should not happen via UI
            raise OptionError(f'Unknown norm: {self.value}', self)


class QRCodePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'qrcode-type'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        return NetworkQRCodeType.static_id()

    @property
    def qrcode_print_document_id(self) -> str:
        from data.print_documents.documents import QRCodePrintDocument

        return QRCodePrintDocument.static_id()

    @property
    def qrcode_type_options(self) -> dict[str, str]:
        from data.print_documents import PrintQRCodeTypeManager

        return PrintQRCodeTypeManager(self.event).options()

    @cached_property
    def qrcode_type(self) -> QRCodeType:
        from data.print_documents import PrintQRCodeTypeManager

        return PrintQRCodeTypeManager(self.event).get_object(self.value)

    @property
    def valid_option_ids_per_type_id(self) -> dict[str, list[str]]:
        from data.print_documents import PrintQRCodeTypeManager

        type_options = PrintQRCodeTypeManager(self.event).type_by_id()
        return {
            type_id: type_options[type_id].get_valid_option_ids()
            for type_id in type_options
        }

    @override
    def validate(self):
        super().validate()
        try:
            _style = self.qrcode_type
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown QR Code type: {self.value}', self)


class QRCodeNetworkPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'qrcode-network'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        return None

    @property
    def network_options(self) -> dict[str, str]:
        config = SharlyChessConfig()
        return {
            str(iface['ip']): f'{iface["label"]} ({iface["type"]})'
            if 'type' in iface and iface['type'] and iface['type'] != iface['label']
            else f'{iface["label"]}'
            for iface in config.lan_ifaces
        }


class PlaceCardPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'place-card-type'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        return PlayerCardType.static_id()

    @property
    def place_card_print_document_id(self) -> str:
        from data.print_documents.documents import PlaceCardPrintDocument

        return PlaceCardPrintDocument.static_id()

    @property
    def place_card_type_options(self) -> dict[str, str]:
        from data.print_documents import PrintPlaceCardTypeManager
        from data.print_documents.documents import (
            PlaceCardTemplate,
        )

        place_card_templates_by_type: dict[PlaceCardType, list[PlaceCardTemplate]] = (
            PlaceCardTemplate.get_place_card_templates_by_type()
        )
        is_team_event = self.event is not None and self.event.is_team_event
        return {
            place_card_type.static_id(): place_card_type.static_name()
            for place_card_type in PrintPlaceCardTypeManager().objects()
            if place_card_templates_by_type[place_card_type]
            and place_card_type.supports_event_type(is_team_event)
        }

    @cached_property
    def place_card_type(self) -> PlaceCardType:
        from data.print_documents import PrintPlaceCardTypeManager

        return PrintPlaceCardTypeManager().get_object(self.value)

    @property
    def valid_option_ids_per_type_id(self) -> dict[str, list[str]]:
        from data.print_documents import PrintPlaceCardTypeManager

        type_options = PrintPlaceCardTypeManager().type_by_id()
        return {
            type_id: type_options[type_id].get_valid_option_ids()
            for type_id in type_options
        }

    @override
    def validate(self):
        super().validate()
        try:
            _style = self.place_card_type
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown Place Card type: {self.value}', self)


class PlaceCardTemplatePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'place-card-template'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        # This is managed by the print controller
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is None:
            raise OptionError(_('Please choose the template.'), self)

    @cached_property
    def place_card_template(self) -> 'PlaceCardTemplate':
        from data.print_documents.place_cards.template import PlaceCardTemplate

        return PlaceCardTemplate.load(self.value)

    @property
    def place_card_templates_per_type(self) -> dict[str, list[dict[str, Any]]]:
        from data.print_documents.place_cards.template import PlaceCardTemplate

        return {
            place_card_type.static_id(): [
                {
                    'id': place_card_template.id,
                    'name': place_card_template.name,
                    'tooltip': place_card_template.preview(),
                }
                for place_card_template in place_card_templates
            ]
            for place_card_type, place_card_templates in PlaceCardTemplate.get_place_card_templates_by_type().items()
        }


class PlaceCardMirrorPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'place-card-mirror'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class PlaceCardCropMarksPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'place-card-crop-marks'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return CornersPlaceCardCropMarks.static_id()

    @property
    def place_card_crop_marks_options(self) -> dict[str, str]:
        from data.print_documents import PrintPlaceCardCropMarksManager

        return PrintPlaceCardCropMarksManager().options()

    @cached_property
    def place_card_crop_marks(self) -> PlaceCardCropMarks:
        from data.print_documents.managers import PrintPlaceCardCropMarksManager

        return PrintPlaceCardCropMarksManager().get_object(self.value)

    @override
    def validate(self):
        super().validate()
        try:
            _crop_marks = self.place_card_crop_marks
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown place card crop marks: {self.value}', self)


class PlaceCardBoardNumbersPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'place-card-board-numbers'

    @property
    def type(self) -> type | UnionType:
        return str | None

    @property
    def default_value(self) -> Any:
        return None

    @cached_property
    def board_numbers(self) -> set[int]:
        board_numbers: set[int] = set()
        value = self.value
        if value:
            value = re.sub(r'\s*-\s*', '-', value)
            value = re.sub(r'[\s,;]+', ' ', value)
            for part in re.split(' ', value):
                if re.match(r'^(\d*)$', part):
                    board_numbers.add(int(part))
                elif matches := re.match(r'^(\d*)-(\d*)$', part):
                    board_numbers.update(range(int(matches[1]), int(matches[2]) + 1))
                else:
                    raise OptionError(
                        _('Invalid expression [{expression}]').format(expression=part),
                        self,
                    )
        return board_numbers

    @override
    def validate(self):
        super().validate()
        _board_numbers = self.board_numbers


class AccountPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'account'

    @property
    def template_file_name(self) -> str:
        return 'account'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @property
    def default_text(self) -> str:
        """Returns the default text for this option."""
        return _('Select an account')

    @property
    @abstractmethod
    def label(self) -> str:
        """Returns the label for this option."""
        return _('Account:')


class PlayerHistoryOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'player-history'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return False


class IndividualTeamTypePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'individual-team-type'

    @property
    def type(self) -> type | UnionType:
        return str

    @property
    def default_value(self) -> Any:
        return ClubIndividualTeamType.static_id()

    @property
    def manager(self) -> 'PrintIndividualTeamTypeManager':
        from data.print_documents import PrintIndividualTeamTypeManager

        return PrintIndividualTeamTypeManager(self.event)

    @property
    def team_type_options(self) -> dict[str, str]:
        return self.manager.options()

    @cached_property
    def team_type(self) -> IndividualTeamType:
        return self.manager.get_object(self.value)

    @property
    def max_per_entity_label_per_type(self) -> dict[str, str]:
        return {
            team_type.id: team_type.max_per_entity_label
            for team_type in self.manager.objects()
        }

    @override
    def validate(self):
        try:
            _type = self.team_type
        except KeyError:
            # Untranslated, should not happen
            raise OptionError(f'Unknown team type: {self.value}', self)


class IndividualTeamSizePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'individual-team-size'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return 4

    @override
    def validate(self):
        super().validate()
        if self.value is None or self.value < 2:
            raise OptionError(_('An integer greater than 1 is expected.'), self)


class IndividualTeamMaxPerEntityPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'individual-team-max-per-entity'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is not None and self.value < 1:
            raise OptionError(_('A positive integer is expected.'), self)


class IndividualTeamMinGenderCountPrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'individual-team-min-gender-count'

    @property
    def type(self) -> type | UnionType:
        return int | None

    @property
    def default_value(self) -> Any:
        return None

    @override
    def validate(self):
        super().validate()
        if self.value is not None and self.value < 0:
            raise OptionError(_('A positive integer is expected.'), self)


class IndividualTeamDisplayIncompletePrintOption(PrintOption):
    @staticmethod
    def static_id() -> str:
        return 'individual-team-display-incomplete'

    @property
    def type(self) -> type | UnionType:
        return bool

    @property
    def default_value(self) -> Any:
        return True
