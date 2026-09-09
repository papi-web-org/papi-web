from typing import override
from data.print_documents import (
    documents,
    options,
    player_splitters,
    player_sorters,
    pairing_styles,
    qrcode_types,
    individual_teams,
)
from data.print_documents.documents import PrintDocument
from data.print_documents.options import PrintOption
from data.print_documents.pairing_styles import PairingStyle
from data.print_documents.place_cards.crop_marks import (
    PlaceCardCropMarks,
    CornersPlaceCardCropMarks,
    SolidBorderPlaceCardCropMarks,
    DashedBorderPlaceCardCropMarks,
    NonePlaceCardCropMarks,
)
from data.print_documents.place_cards.types import (
    PlaceCardType,
    PlayerCardType,
    BoardCardType,
    PairingCardType,
    TeamCardType,
)
from data.print_documents.player_sorters import (
    GridPlayerSorter,
    ListPlayerSorter,
    TeamGridSorter,
)
from data.print_documents.player_splitters import PlayerSplitter
from data.print_documents.qrcode_types import QRCodeType
from data.print_documents.individual_teams import IndividualTeamType
from plugins.manager import plugin_manager
from utils.entity import EventBoundEntityManager, EntityManager


class PrintDocumentManager(EventBoundEntityManager[PrintDocument]):
    @override
    def entity_types(self) -> list[type[PrintDocument]]:
        print_documents = [
            documents.PlayerListPrintDocument,
            documents.PlayerCheckinListPrintDocument,
            documents.PairingPrintDocument,
            documents.RoundRobinSchedulePrintDocument,
            documents.MolterTablePrintDocument,
            documents.ScheveningenTablePrintDocument,
            documents.MatchSheetsPrintDocument,
            documents.ResultPrintDocument,
            documents.PlayerRankingPrintDocument,
            documents.TeamRankingPrintDocument,
            documents.IndividuelTeamRankingPrintDocument,
            documents.PlayerCrosstablePrintDocument,
            documents.BergerGridPrintDocument,
            documents.TeamBergerGridPrintDocument,
            documents.PlayerRoundPerformanceIndicatorPrintDocument,
            documents.PrizeListPrintDocument,
            documents.PrizeAssignmentPrintDocument,
            documents.PrizeReceiptsPrintDocument,
            documents.StatisticsPrintDocument,
            documents.TournamentNormsSummaryPrintDocument,
            documents.NormReportPrintDocument,
            documents.NormCalculationDetailsPrintDocument,
            documents.QRCodePrintDocument,
            documents.PlaceCardPrintDocument,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_print_document')(
            print_documents=print_documents
        )
        return print_documents


class PrintDocumentOptionManager(EventBoundEntityManager[PrintOption]):
    @override
    def entity_types(self) -> list[type[options.PrintOption]]:
        print_options = [
            options.QRCodePrintOption,
            options.PlaceCardPrintOption,
            options.PlaceCardTemplatePrintOption,
            options.TournamentPrintOption,
            options.TournamentsPrintOption,
            options.MandatoryPlayerPrintOption,
            options.OptionalPlayerPrintOption,
            options.OptionalPlayersPrintOption,
            options.OptionalTeamsPrintOption,
            options.PairingStylePrintOption,
            options.RoundPrintOption,
            options.MatchSheetSelectionPrintOption,
            options.MatchSheetArbiterPrintOption,
            options.TeamBergerGridPlayersPrintOption,
            options.PlayerSplitPrintOption,
            options.GridPlayerSortPrintOption,
            options.TeamGridSortPrintOption,
            options.ListPlayerSortPrintOption,
            options.ShowWarningsPrintOption,
            options.NonMonetaryPrintOption,
            options.FederationPrintOption,
            options.ClubThresholdPrintOption,
            options.Rule143ExemptionPrintOption,
            options.NormsForecastSortPrintOption,
            options.QRCodeNetworkPrintOption,
            options.PlaceCardBoardNumbersPrintOption,
            options.PlaceCardMirrorPrintOption,
            options.PlaceCardCropMarksPrintOption,
            options.PlayerHistoryOption,
            options.IndividualTeamTypePrintOption,
            options.IndividualTeamSizePrintOption,
            options.IndividualTeamMinGenderCountPrintOption,
            options.IndividualTeamMaxPerEntityPrintOption,
            options.IndividualTeamDisplayIncompletePrintOption,
            options.FixedBoardOrderPrintOption,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_print_option')(
            print_options=print_options
        )
        return print_options

    @override
    def objects(self) -> list[PrintOption]:
        return [type_(self.event) for type_ in self.entity_types()]


class PrintPlayerSplitterManager(EventBoundEntityManager[PlayerSplitter]):
    @override
    def entity_types(self) -> list[type[PlayerSplitter]]:
        splitters = [
            player_splitters.NoSplitPlayerSplitter,
            player_splitters.CategoryPlayerSplitter,
            player_splitters.ClubPlayerSplitter,
            player_splitters.FederationPlayerSplitter,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_print_player_splitter_types')(
            player_splitter_types=splitters
        )
        return splitters


class PrintGridPlayerSorterManager(EventBoundEntityManager[GridPlayerSorter]):
    @override
    def entity_types(self) -> list[type[GridPlayerSorter]]:
        return [
            player_sorters.RankGridPlayerSorter,
            player_sorters.StartingRankGridPlayerSorter,
            player_sorters.NameGridPlayerSorter,
            player_sorters.PairingNumberGridPlayerSorter,
        ]


class PrintTeamGridSorterManager(EventBoundEntityManager[TeamGridSorter]):
    @override
    def entity_types(self) -> list[type[TeamGridSorter]]:
        return [
            player_sorters.RankTeamGridSorter,
            player_sorters.PairingNumberTeamGridSorter,
            player_sorters.NameTeamGridSorter,
        ]


class PrintListPlayerSorterManager(EventBoundEntityManager[ListPlayerSorter]):
    @override
    def entity_types(self) -> list[type[ListPlayerSorter]]:
        return [
            player_sorters.NameListPlayerSorter,
            player_sorters.StartingRankListPlayerSorter,
        ]


class PrintPairingStyleManager(EventBoundEntityManager[PairingStyle]):
    @override
    def entity_types(self) -> list[type[PairingStyle]]:
        return [
            pairing_styles.BoardsPairingStyle,
            pairing_styles.PlayersPairingStyleSorter,
        ]


class PrintQRCodeTypeManager(EventBoundEntityManager[QRCodeType]):
    @override
    def entity_types(self) -> list[type[QRCodeType]]:
        types: list[type[QRCodeType]] = [
            qrcode_types.NetworkQRCodeType,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_print_qrcode_types')(
            qrcode_types=types
        )
        return types


class PrintPlaceCardTypeManager(EntityManager[PlaceCardType]):
    @override
    def entity_types(self) -> list[type[PlaceCardType]]:
        return [
            PlayerCardType,
            PairingCardType,
            BoardCardType,
            TeamCardType,
        ]


class PrintPlaceCardCropMarksManager(EntityManager[PlaceCardCropMarks]):
    @override
    def entity_types(self) -> list[type[PlaceCardCropMarks]]:
        return [
            CornersPlaceCardCropMarks,
            NonePlaceCardCropMarks,
            SolidBorderPlaceCardCropMarks,
            DashedBorderPlaceCardCropMarks,
        ]


class PrintIndividualTeamTypeManager(EventBoundEntityManager[IndividualTeamType]):
    @override
    def entity_types(self) -> list[type[IndividualTeamType]]:
        individual_team_types = [
            individual_teams.ClubIndividualTeamType,
            individual_teams.FederationIndividualTeamType,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_print_individual_team_types')(
            individual_team_types=individual_team_types
        )
        return individual_team_types
