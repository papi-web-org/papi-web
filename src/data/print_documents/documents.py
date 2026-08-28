import itertools
import logging
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property, partial
from typing import Any, Callable, override

from common.exception import SharlyChessException, OptionError
from common.i18n import _, ngettext
from common.i18n.utils import unicode_normalize
from common.logger import get_logger
from data.access_levels.actions import AuthAction
from data.access_levels.client import Client
from data.board import Board
from data.columns import player_table as columns
from data.columns.board_table import BoardColumn, ResultColumn, NoResultColumn
from data.columns.handlers import PlayerColumnHandler, BoardColumnHandler
from data.columns.player_table import ColumnUsage, TournamentPlayerTableColumn
from data.event import Event
from data.norms import ForecastRequirement
from data.pairings.engines import (
    BergerPairingEngine,
    RoundRobinPairingEngine,
    TeamRoundRobinPairingEngine,
)
from data.pairings.fixed_table import PairingTableProvider
from data.pairings.molter import MolterPairingSystem
from data.pairings.scheveningen import ScheveningenPairingSystem
from data.pairings.settings import BergerNumbersSetting
from data.pairings.systems import (
    RoundRobinPairingSystem,
    SwissPairingSystem,
    TeamRoundRobinPairingSystem,
)
from data.player import TournamentPlayer, TournamentRating
from data.print_documents.options import (
    PairingStylePrintOption,
    MandatoryPlayerPrintOption,
    NormChoicePrintOption,
    NormsForecastSortPrintOption,
    OptionalPlayerPrintOption,
    Rule143ExemptionPrintOption,
    PlayerSplitPrintOption,
    PrintOption,
    QRCodeNetworkPrintOption,
    QRCodePrintOption,
    RoundPrintOption,
    MatchSheetSelectionPrintOption,
    MatchSheetArbiterPrintOption,
    TeamBergerGridPlayersPrintOption,
    GridPlayerSortPrintOption,
    TeamGridSortPrintOption,
    ListPlayerSortPrintOption,
    ShowWarningsPrintOption,
    NonMonetaryPrintOption,
    FederationPrintOption,
    ClubThresholdPrintOption,
    TournamentPrintOption,
    TournamentsPrintOption,
    PlaceCardPrintOption,
    PlaceCardTemplatePrintOption,
    PlaceCardMirrorPrintOption,
    PlaceCardCropMarksPrintOption,
    PlaceCardBoardNumbersPrintOption,
    OptionalPlayersPrintOption,
    PlayerHistoryOption,
    IndividualTeamTypePrintOption,
    IndividualTeamSizePrintOption,
    IndividualTeamMinGenderCountPrintOption,
    IndividualTeamMaxPerEntityPrintOption,
    IndividualTeamDisplayIncompletePrintOption,
    FixedBoardOrderPrintOption,
)
from data.print_documents.place_cards.crop_marks import PlaceCardCropMarks
from data.print_documents.place_cards.template import (
    PlaceCardTemplate,
)
from data.print_documents.place_cards.types import PlaceCardType
from data.print_documents.individual_teams import IndividualTeamType, IndividualTeam
from data.tournament import Tournament
from plugins.manager import plugin_manager
from utils import Utils
from utils.enum import (
    Result,
    TitleNorm,
    PlayerGender,
    ScoreType,
)
from utils.option import Option, OptionHandler
from utils.types import PlayerTitle

logger: logging.Logger = get_logger()


class PrintDocument(OptionHandler[PrintOption], ABC):
    def __init__(
        self,
        client: Client | None = None,
        options: list[PrintOption] | None = None,
    ):
        self.client: Client | None = client
        self.event: Event | None = None if self.client is None else self.client.event
        super().__init__(options)

    def get_client(self) -> Client:
        assert self.client is not None
        return self.client

    def get_event(self) -> Event:
        assert self.event is not None
        return self.event

    def get_allowed_tournaments(self) -> list[Tournament]:
        return self.get_client().allowed_tournaments_for_action(
            AuthAction.GENERATE_DOCUMENTS
        )

    hide_for_team_events: bool = False
    hide_for_individual_events: bool = False

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not allowed_tournaments and (
            TournamentPrintOption in cls.available_options()
            or TournamentsPrintOption in cls.available_options()
        ):
            return False
        if (
            cls.hide_for_team_events
            and allowed_tournaments
            and any(t.event.is_team_event for t in allowed_tournaments)
        ):
            return False
        if (
            cls.hide_for_individual_events
            and allowed_tournaments
            and any(not t.event.is_team_event for t in allowed_tournaments)
        ):
            return False
        return True

    @override
    def default_options(self) -> list[PrintOption]:
        return [option_type(self.event) for option_type in self.available_options()]

    @override
    def _get_option[V: Option](self, option_type: type[V]) -> V:
        return next(
            (option for option in self.options if isinstance(option, option_type)),
            option_type(self.get_event()),
        )

    @property
    def tournament(self) -> Tournament:
        """The tournament for which the document is printed."""
        tournament_id = self._get_option(TournamentPrintOption).value
        if tournament_id:
            return self.get_event().tournaments_by_id[tournament_id]
        return self.tournaments[0]

    @property
    def tournaments(self) -> list[Tournament]:
        """The tournaments for which the document is printed."""
        tournament_ids = self._get_option(TournamentsPrintOption).value
        if not tournament_ids:
            return self.get_allowed_tournaments()
        return [
            self.get_event().tournaments_by_id[int(tournament_id)]
            for tournament_id in tournament_ids.split(';')
        ]

    @cached_property
    def mandatory_player(self) -> TournamentPlayer:
        return self.tournament.tournament_players_by_id[
            self._get_option(MandatoryPlayerPrintOption).value
        ]

    @cached_property
    def optional_player(self) -> TournamentPlayer | None:
        if player_id := self._get_option(OptionalPlayerPrintOption).value:
            return self.tournament.tournament_players_by_id[player_id]
        else:
            return None

    @cached_property
    def optional_players(self) -> list[TournamentPlayer]:
        return [
            self.tournament.tournament_players_by_id[player_id]
            for player_id in self._get_option(OptionalPlayersPrintOption).value
        ]

    @property
    def subtitle(self) -> str:
        """Subtitle of the print document."""
        return (
            self.get_event().name
            if len(self.tournaments) == len(list(self.get_event().tournaments))
            else ', '.join(tournament.name for tournament in self.tournaments)
        )

    @property
    @abstractmethod
    def title(self) -> str:
        """Header of the print document."""

    @property
    def tab_title(self) -> str:
        title = self.name
        if TournamentPrintOption in self.available_options():
            title += f' - {self.tournament.name}'
        return title

    @property
    @abstractmethod
    def template_name(self) -> str:
        """Name of the template representing the printed document.
        Template is intended to be used with a context where
        "document" refers to the PrintDocument object
        """

    @property
    @abstractmethod
    def template_context(self) -> dict[str, Any]:
        """Context to pass to the template *template_name*.
        If multiple classes use the same template, an abstract class per
        template should be defined with the required context, with each
        context variable being a property of this class."""


class PlayerPrintDocument(PrintDocument, ABC):
    @property
    def template_name(self) -> str:
        return '/admin/print/players.html'

    @property
    @abstractmethod
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        """List of players in the order they should appear in the document."""

    @property
    def ordered_split_players(self) -> dict[str, list[TournamentPlayer]]:
        splitter = self._get_option(PlayerSplitPrintOption).player_splitter
        return splitter.split_players(self.get_event(), self.ordered_tournament_players)

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentsPrintOption, PlayerSplitPrintOption]

    @property
    def column_handler(self) -> PlayerColumnHandler:
        return PlayerColumnHandler(self.get_event(), ColumnUsage.PRINT)

    @property
    def multiple_tournaments(self) -> bool:
        return True

    @override
    @property
    def subtitle(self) -> str:
        """Subtitle of the print document."""
        return (
            self.tournament.name if not self.multiple_tournaments else super().subtitle
        )

    @property
    @abstractmethod
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        """List of all the columns to display in the tables of the document."""

    @property
    def template_context(self) -> dict[str, Any]:
        return {
            'tournament': self.tournament,
            'tournaments': self.tournaments,
            'subtitle': self.subtitle,
            'ordered_split_players': self.ordered_split_players,
            'player_columns': self.player_columns,
            'row_count': [1],
        }


class PlayerListPrintDocument(PlayerPrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'player-list'

    @staticmethod
    def static_name() -> str:
        return _('List of players')

    @property
    def title(self) -> str:
        return _('List of players')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return PlayerPrintDocument.available_options() + [ListPlayerSortPrintOption]

    @property
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        tournament_ids = [tournament.id for tournament in self.tournaments]
        tournament_players: list[TournamentPlayer] = [
            player.single_tournament_player
            for player in self.get_event().tournament_players
            if player.single_tournament.id in tournament_ids
        ]
        list_player_sorter = self._get_option(
            ListPlayerSortPrintOption
        ).list_player_sorter
        return list_player_sorter.sort_tournament_players(tournament_players)

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_player_list_columns(len(self.tournaments) > 1)


class PlayerCheckinListPrintDocument(PlayerPrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'player-checkin-list'

    @staticmethod
    def static_name() -> str:
        return _('Players check-in list')

    @property
    def title(self) -> str:
        return _('Players check-in list')

    @property
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        tournament_ids = [tournament.id for tournament in self.tournaments]
        return [
            player.single_tournament_player
            for player in self.get_event().sorted_players
            if player.single_tournament.id in tournament_ids
        ]

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_player_checkin_list_columns(
            len(self.tournaments) > 1
        )


class AbstractPlayerRankingPrintDocument(PlayerPrintDocument, ABC):
    @property
    def ranking_round(self) -> int:
        return (
            self._get_option(RoundPrintOption).value
            or self.tournament.max_ranking_round
        )

    @property
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        return list(
            self.tournament.compute_tournament_player_ranks(
                after_round=self.ranking_round
            ).values()
        )

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption, PlayerSplitPrintOption, RoundPrintOption]

    @override
    @property
    def multiple_tournaments(self) -> bool:
        return False

    @override
    def validate_options(self):
        super().validate_options()
        ranking_round = self._get_option(RoundPrintOption)
        if ranking_round.value is None:
            return
        if ranking_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                ranking_round,
            )
        if ranking_round.value > self.tournament.max_ranking_round:
            raise OptionError(
                _('This round is not finished (last finished: #{round}).').format(
                    round=self.tournament.max_ranking_round
                ),
                ranking_round,
            )


class PlayerRankingPrintDocument(AbstractPlayerRankingPrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'individual-ranking'

    @staticmethod
    def static_name() -> str:
        return _('Individual ranking')

    @property
    def title(self) -> str:
        if self.ranking_round == 0:
            return _('Ranking before the first round')
        return _('Ranking after round #{round}').format(round=self.ranking_round)

    @property
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        return [
            player
            for player in super().ordered_tournament_players
            if not player.is_excluded_from_standings
        ]

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_player_ranking_columns(self.tournament)


class PlayerCrosstablePrintDocument(AbstractPlayerRankingPrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'crosstable'

    @staticmethod
    def static_name() -> str:
        return _('Crosstable')

    @property
    def title(self) -> str:
        if self.ranking_round == 0:
            return _('Crosstable before the first round')
        return _('Crosstable after round #{round}').format(round=self.ranking_round)

    @property
    def include_player_history(self) -> bool:
        return self._get_option(PlayerHistoryOption).value

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_player_crosstable_columns(
            self.tournament, self.ranking_round
        )

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return AbstractPlayerRankingPrintDocument.available_options() + [
            PlayerHistoryOption
        ]

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'include_player_history': self.include_player_history,
            'max_round': self.ranking_round,
        }


class PlayerRoundPerformanceIndicatorPrintDocument(PrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'round-performance-indicators'

    @staticmethod
    def static_name() -> str:
        return _('Round performance indicators')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption, RoundPrintOption]

    @property
    def title(self) -> str:
        return _('Performance indicators for round #{round}').format(
            round=self.ranking_round
        )

    @property
    def ranking_round(self) -> int:
        return (
            self._get_option(RoundPrintOption).value
            or self.tournament.max_ranking_round
        )

    @property
    def template_name(self) -> str:
        return '/admin/print/round_performance.html'

    @property
    def ordered_players(
        self,
    ) -> list[tuple[TournamentPlayer, TournamentPlayer, Result, float]]:
        ranking_round = self.ranking_round
        if not ranking_round:
            return []
        results: list[tuple[TournamentPlayer, TournamentPlayer, Result, float]] = []
        for tournament_player in self.tournament.tournament_players:
            pairing = tournament_player.pairings[ranking_round]
            rating_change = tournament_player.round_performance(ranking_round)
            if pairing.opponent_id and pairing.played and rating_change is not None:
                opponent = self.tournament.tournament_players_by_id[pairing.opponent_id]
                results.append(
                    (tournament_player, opponent, pairing.result, rating_change)
                )
        return sorted(results, key=lambda p: -p[3])

    @override
    def validate_options(self):
        super().validate_options()
        ranking_round = self._get_option(RoundPrintOption)
        if ranking_round.value is None:
            if self.tournament.max_ranking_round < 1:
                raise OptionError(
                    _('The tournament has not yet started.'),
                    ranking_round,
                )
            return
        if ranking_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                ranking_round,
            )
        if ranking_round.value > self.tournament.max_ranking_round:
            raise OptionError(
                _('This round is not finished (last finished: #{round}).').format(
                    round=self.tournament.max_ranking_round
                ),
                ranking_round,
            )

    @property
    def template_context(self) -> dict[str, Any]:
        return {
            'tournament': self.tournament,
            'subtitle': self.tournament.name,
            'scores': self.ordered_players,
        }


class BoardPrintDocument(PrintDocument, ABC):
    @property
    def template_name(self) -> str:
        return '/admin/print/boards.html'

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption, RoundPrintOption]

    @property
    def show_results(self) -> bool:
        return False

    @property
    def show_federation(self) -> bool:
        return False

    @property
    def board_columns(self) -> list[BoardColumn]:
        return BoardColumnHandler(ColumnUsage.PRINT).get_pairings_columns(
            self.tournament,
            self.at_round,
            ResultColumn if self.show_results else NoResultColumn,
            show_federation=self.show_federation,
        )

    @property
    def boards(self) -> list[Board]:
        self.tournament.set_for_round(self.at_round)
        return self.tournament.get_round_boards(self.at_round)

    @property
    def template_context(self) -> dict[str, Any]:
        return {
            'tournament': self.tournament,
            'subtitle': self.tournament.name,
            'boards': self.boards,
            'board_columns': self.board_columns,
        }

    @property
    def at_round(self) -> int:
        return self._get_option(RoundPrintOption).value or self.tournament.current_round

    @override
    def validate_options(self):
        super().validate_options()
        at_round = self._get_option(RoundPrintOption)
        if at_round.value is None:
            return
        if at_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                at_round,
            )
        if at_round.value > self.tournament.current_round:
            if self.tournament.pairing_system == SwissPairingSystem():
                raise OptionError(
                    _(
                        'There are no pairings for this round (last round with pairings: #{round}).'
                    ).format(round=self.tournament.current_round),
                    at_round,
                )
            else:
                raise OptionError(
                    _("This round hasn't started (current round: #{round}).").format(
                        round=self.tournament.current_round
                    ),
                    at_round,
                )


class PairingPrintDocument(PrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'pairings'

    @staticmethod
    def static_name() -> str:
        return _('Pairings')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            PairingStylePrintOption,
            RoundPrintOption,
            FixedBoardOrderPrintOption,
            FederationPrintOption,
        ]

    @cached_property
    def sub_document(self) -> PrintDocument:
        return self._get_option(
            PairingStylePrintOption
        ).pairing_style.print_document_type(self.client, options=self.options)

    @property
    def title(self) -> str:
        return self.sub_document.title

    @property
    def template_name(self) -> str:
        return self.sub_document.template_name

    @property
    def template_context(self) -> dict[str, Any]:
        return self.sub_document.template_context


class BoardPairingPrintDocument(BoardPrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'board-pairings'

    @staticmethod
    def static_name() -> str:
        return _('Board Pairings')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return BoardPrintDocument.available_options() + [
            FixedBoardOrderPrintOption,
            FederationPrintOption,
        ]

    @property
    def show_federation(self) -> bool:
        return bool(self._get_option(FederationPrintOption).value)

    @property
    def title(self) -> str:
        return _('Pairings for round #{round}').format(round=self.at_round)

    @property
    def boards(self) -> list[Board]:
        boards = super().boards
        if self.tournament.leave_fixed_board_holes:
            return boards
        if (
            self._get_option(FixedBoardOrderPrintOption).value
            == FixedBoardOrderPrintOption.NATURAL
        ):
            return boards
        return sorted(boards, key=lambda board: board.number)


class PlayerPairingPrintDocument(PlayerPrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'player-pairings'

    @staticmethod
    def static_name() -> str:
        return _('Player pairings')

    @property
    def title(self) -> str:
        return _('Pairings for round #{round}').format(round=self.at_round)

    @property
    def at_round(self) -> int:
        return self._get_option(RoundPrintOption).value or self.tournament.current_round

    @override
    @property
    def multiple_tournaments(self) -> bool:
        return False

    @override
    @property
    def ordered_tournament_players(self) -> list[TournamentPlayer]:
        self.tournament.set_for_round(self.at_round)
        return self.tournament.sorted_tournament_players

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_alpha_board_player_columns()

    @property
    def opponent_columns(self) -> list[TournamentPlayerTableColumn]:
        return self.column_handler.get_alpha_board_opponent_columns()

    @property
    def template_name(self) -> str:
        return '/admin/print/pairings_by_player.html'

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'pairings_round': self.at_round,
            'opponent_columns': self.opponent_columns,
        }


class ResultPrintDocument(BoardPrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'results'

    @staticmethod
    def static_name() -> str:
        return _('Results')

    @property
    def title(self) -> str:
        return _('Results for round #{round}').format(round=self.at_round)

    @override
    @property
    def show_results(self) -> bool:
        return True


class MatchSheetsPrintDocument(PrintDocument):
    """One signature-ready table per team match in the round. Used by
    arbiters to capture each match's individual results + captains'
    signatures. Selection option lets the arbiter print only a subset
    of matches; the page-break option prints one match per page."""

    hide_for_individual_events = True

    @staticmethod
    def static_id() -> str:
        return 'match-sheets'

    @staticmethod
    def static_name() -> str:
        return _('Match sheets')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            RoundPrintOption,
            MatchSheetSelectionPrintOption,
            MatchSheetArbiterPrintOption,
        ]

    @property
    def template_name(self) -> str:
        return '/admin/print/match_sheets.html'

    @property
    def at_round(self) -> int:
        return self._get_option(RoundPrintOption).value or self.tournament.current_round

    @property
    def title(self) -> str:
        return _('Match sheets for round #{round}').format(round=self.at_round)

    @property
    def page_break(self) -> bool:
        # Match sheets always start on a fresh page (one match per page).
        return True

    @property
    def flat_mode(self) -> bool:
        """Fixed-table team systems pair flat boards with no match
        envelopes — the sheet becomes a single round sheet listing the
        boards, and the selection option selects boards."""
        return not self.tournament.pairing_system.paired_by_team

    @property
    def team_boards(self):
        if self.flat_mode:
            return []
        self.tournament.set_for_round(self.at_round)
        all_boards = [
            tb
            for tb in self.tournament.get_round_team_boards(self.at_round)
            if tb.stored_team_board.team_b_id is not None
        ]
        selected_ids = set(self._get_option(MatchSheetSelectionPrintOption).value or [])
        if not selected_ids:
            return all_boards
        return [tb for tb in all_boards if tb.id in selected_ids]

    @property
    def flat_boards(self):
        if not self.flat_mode:
            return []
        self.tournament.set_for_round(self.at_round)
        boards = sorted(
            self.tournament.get_round_boards(self.at_round),
            key=lambda b: b.index,
        )
        selected_ids = set(self._get_option(MatchSheetSelectionPrintOption).value or [])
        if not selected_ids:
            return boards
        return [b for b in boards if b.identifier in selected_ids]

    @property
    def flat_board_refs(self) -> dict[int, tuple[str, str]]:
        """``board.index`` → table cell codes ``(white_ref, black_ref)`` for
        fixed-table (Molter) systems; empty otherwise. Used only as the
        fallback code for an empty seat (a hole), to show which player is
        missing on a forfeit board — a seated player's code comes from their
        own line-up slot."""
        from data.pairings.fixed_table import FixedTablePairingEngine

        engine = self.tournament.pairing_variation.engine
        if not isinstance(engine, FixedTablePairingEngine):
            return {}
        return dict(enumerate(engine.board_references(self.tournament, self.at_round)))

    @property
    def team_letter_by_id(self) -> dict[int, str]:
        """Team id → table letter for round-robin team systems, whose
        FFE sheets reference players as ``A1``/``B2`` (team letter +
        board). Empty for other systems."""
        if not isinstance(self.tournament.pairing_system, TeamRoundRobinPairingSystem):
            return {}
        teams = sorted(
            self.tournament.teams,
            key=lambda t: (
                t.pairing_number if t.pairing_number is not None else float('inf'),
                t.name.lower(),
            ),
        )
        return {team.id: chr(ord('A') + i) for i, team in enumerate(teams)}

    @property
    def match_sheet_options(self) -> list[tuple[int, str]]:
        """``(id, label)`` rows feeding the selection checkboxes: one per
        paired team match, or one per board for flat systems."""
        self.tournament.set_for_round(self.at_round)
        rows: list[tuple[int, str]] = []
        if self.flat_mode:
            for board in sorted(
                self.tournament.get_round_boards(self.at_round),
                key=lambda b: b.index,
            ):
                wtp = board.optional_white_tournament_player
                btp = board.black_tournament_player
                label = _('%(a)s vs %(b)s').format(
                    a=wtp.full_name if wtp else '',
                    b=btp.full_name if btp else '',
                )
                rows.append((board.identifier, f'{board.number}. {label}'))
            return rows
        for tb in self.tournament.get_round_team_boards(self.at_round):
            stb = tb.stored_team_board
            if stb.team_b_id is None:
                continue
            label = _('%(a)s vs %(b)s').format(
                a=tb.team_a.name,
                b=tb.team_b.name if tb.team_b else '',
            )
            rows.append((tb.id, label))
        return rows

    @override
    def validate_options(self):
        super().validate_options()
        at_round = self._get_option(RoundPrintOption)
        if at_round.value is None:
            return
        if at_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                at_round,
            )
        if at_round.value > self.tournament.current_round:
            raise OptionError(
                _(
                    'There are no pairings for this round (last round '
                    'with pairings: #{round}).'
                ).format(round=self.tournament.current_round),
                at_round,
            )

    def player_national_id(self, tournament_player) -> str:
        """The player's national id, when a plugin provides one (via the
        same hook that fills the TRF national records)."""
        from data.input_output.trf.trf_data import TrfNationalPlayer

        national_player = TrfNationalPlayer(player_id=0)
        plugin_manager.hook_for_event(
            self.tournament.event, 'augment_trf_national_player'
        )(player=tournament_player, trf_national_player=national_player)
        return national_player.national_id

    @property
    def arbiter_name(self) -> str | None:
        account_id = self._get_option(MatchSheetArbiterPrintOption).value
        if account_id is not None:
            account = self.tournament.event.accounts_by_id.get(account_id)
            if account is not None:
                return account.full_name
        arbiter = self.tournament.chief_arbiter
        return arbiter.full_name if arbiter else None

    @property
    def template_context(self) -> dict[str, Any]:
        return {
            'tournament': self.tournament,
            'subtitle': self.tournament.name,
            'team_boards': self.team_boards,
            'flat_mode': self.flat_mode,
            'flat_boards': self.flat_boards,
            'flat_board_refs': self.flat_board_refs,
            'team_letter_by_id': self.team_letter_by_id,
            'page_break': self.page_break,
            'at_round': self.at_round,
            'arbiter_name': self.arbiter_name,
            'player_national_id': self.player_national_id,
        }


class TeamRankingPrintDocument(PrintDocument):
    """Team-tournament equivalent of :class:`PlayerRankingPrintDocument`.
    Renders the team standings table (rank, team, played, W/D/L, MP/GP,
    team tie-breaks) for the team event."""

    hide_for_individual_events = True

    @staticmethod
    def static_id() -> str:
        return 'team-ranking'

    @staticmethod
    def static_name() -> str:
        return _('Team ranking')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption, RoundPrintOption]

    @property
    def template_name(self) -> str:
        return '/admin/print/team_ranking.html'

    @property
    def ranking_round(self) -> int:
        return (
            self._get_option(RoundPrintOption).value
            or self.tournament.max_ranking_round
        )

    @property
    def title(self) -> str:
        if self.ranking_round == 0:
            return _('Team ranking before the first round')
        return _('Team ranking after round #{round}').format(round=self.ranking_round)

    @override
    def validate_options(self):
        super().validate_options()
        ranking_round = self._get_option(RoundPrintOption)
        if ranking_round.value is None:
            return
        if ranking_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                ranking_round,
            )
        if ranking_round.value > self.tournament.max_ranking_round:
            raise OptionError(
                _('This round is not finished (last finished: #{round}).').format(
                    round=self.tournament.max_ranking_round
                ),
                ranking_round,
            )

    @property
    def template_context(self) -> dict[str, Any]:
        primary_is_mp = (
            self.tournament.pairing_system.paired_by_team
            and self.tournament.primary_score == ScoreType.MATCH_POINTS
        )
        team_tie_breaks = self.tournament.team_tie_breaks
        standings = [
            row
            for row in self.tournament.team_standings(after_round=self.ranking_round)
            if not row['team'].is_excluded_from_standings
        ]
        return {
            'tournament': self.tournament,
            'subtitle': self.tournament.name,
            'standings': standings,
            'primary_is_mp': primary_is_mp,
            'team_tie_breaks': team_tie_breaks,
        }


class BergerGridPrintDocument(PrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'berger-grid'

    @staticmethod
    def static_name() -> str:
        return _('Berger grid')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption, GridPlayerSortPrintOption]

    @property
    def title(self) -> str:
        return self.name

    @property
    def template_name(self) -> str:
        return '/admin/print/berger_grid.html'

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(
            tournament.pairing_system == RoundRobinPairingSystem()
            and tournament.is_fully_paired
            for tournament in allowed_tournaments
        )

    def validate_options(self):
        super().validate_options()
        option = self._get_option(TournamentPrintOption)
        tournament = self.tournament
        if tournament.pairing_system != RoundRobinPairingSystem():
            raise OptionError(
                _('This document is only available for Round-Robin tournaments.'),
                option,
            )
        if not tournament.is_fully_paired:
            raise OptionError(
                _('This document is not available for unpaired tournaments.'),
                option,
            )

    @cached_property
    def grid_id_by_player_id(self) -> dict[int, int]:
        grid_player_sorter = self._get_option(
            GridPlayerSortPrintOption
        ).grid_player_sorter
        return {
            tournament_player.id: index + 1
            for index, tournament_player in enumerate(
                grid_player_sorter.sorted_tournament_players(self.tournament)
            )
        }

    def grid_results_points(self, results: list[list[Result | None]]) -> str:
        return Utils.points_str(
            sum(
                result.points(self.tournament.point_values)
                for result in itertools.chain.from_iterable(results)
                if result is not None
            )
        )

    def build_result_grid(self) -> dict[int, list[list[Result | None]]]:
        """Build the player results in a grid format ordered by berger numbers.
        Such a grid is returned per player encounter."""
        pairing_engine = self.tournament.pairing_variation.engine
        assert isinstance(pairing_engine, RoundRobinPairingEngine)
        result_grid: dict[int, list[list[Result | None]]] = {
            tournament_player.id: [
                [None] * pairing_engine.player_encounters
                for __ in range(self.tournament.player_count)
            ]
            for tournament_player in sorted(
                self.tournament.tournament_players,
                key=lambda p: self.grid_id_by_player_id[p.id],
            )
        }
        for tournament_player in self.tournament.tournament_players:
            for pairing in tournament_player.pairings.values():
                if not pairing.opponent_id:
                    continue
                opponent_grid_id = self.grid_id_by_player_id[pairing.opponent_id]
                if not self._set_encounter_result(
                    tournament_player.id,
                    opponent_grid_id,
                    pairing.result,
                    result_grid,
                ):
                    opponent = self.tournament.tournament_players_by_id[
                        pairing.opponent_id
                    ]
                    raise SharlyChessException(
                        f'More than {len(result_grid[tournament_player.id][opponent_grid_id - 1])} encounters between '
                        f'players {tournament_player.full_name} and {opponent.full_name}.'
                    )
        return result_grid

    @staticmethod
    def _set_encounter_result(
        player_id: int,
        opponent_grid_id: int,
        result: Result,
        result_grid: dict[int, list[list[Result | None]]],
    ) -> bool:
        for round_, round_result in enumerate(
            result_grid[player_id][opponent_grid_id - 1]
        ):
            if round_result is None:
                result_grid[player_id][opponent_grid_id - 1][round_] = result
                return True
        return False

    @property
    def template_context(self) -> dict[str, Any]:
        self.tournament.compute_tournament_player_ranks()
        return {
            'document': self,
            'tournament': self.tournament,
            'result_grid': self.build_result_grid(),
            'grid_id_by_player_id': self.grid_id_by_player_id,
        }


class TeamBergerGridPrintDocument(PrintDocument):
    """Berger crosstable for team round-robins. Unlike the individual
    grid, team round-robins are paired round by round (lineups change
    between rounds), so the encounter schedule is computed from the
    Berger tables: played encounters show the match score, future ones
    the round in which they will take place."""

    hide_for_individual_events = True

    @staticmethod
    def static_id() -> str:
        return 'team-berger-grid'

    @staticmethod
    def static_name() -> str:
        return _('Berger grid')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            RoundPrintOption,
            TeamGridSortPrintOption,
            TeamBergerGridPlayersPrintOption,
        ]

    @property
    def title(self) -> str:
        return self.name

    @property
    def ranking_round(self) -> int:
        """Round the grid is tallied up to — the chosen round, else the
        last finished one (same default as the team-ranking document, so
        the points and tie-breaks match it)."""
        return (
            self._get_option(RoundPrintOption).value
            or self.tournament.max_ranking_round
        )

    @property
    def template_name(self) -> str:
        return '/admin/print/team_berger_grid.html'

    @property
    def by_player(self) -> bool:
        return bool(self._get_option(TeamBergerGridPlayersPrintOption).value)

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(
            isinstance(tournament.pairing_system, TeamRoundRobinPairingSystem)
            for tournament in allowed_tournaments
        )

    def validate_options(self):
        super().validate_options()
        option = self._get_option(TournamentPrintOption)
        if not isinstance(self.tournament.pairing_system, TeamRoundRobinPairingSystem):
            raise OptionError(
                _('This document is only available for Round-Robin tournaments.'),
                option,
            )
        round_option = self._get_option(RoundPrintOption)
        if round_option.value is not None:
            if round_option.value > self.tournament.rounds:
                raise OptionError(
                    _(
                        'This round is not valid (the tournament has {rounds} rounds).'
                    ).format(rounds=self.tournament.rounds),
                    round_option,
                )
            if round_option.value > self.tournament.max_ranking_round:
                raise OptionError(
                    _('This round is not finished (last finished: #{round}).').format(
                        round=self.tournament.max_ranking_round
                    ),
                    round_option,
                )

    @property
    def template_context(self) -> dict[str, Any]:
        tournament = self.tournament
        # Tally only up to the displayed round (the entire stored schedule
        # would over-count rounds that aren't finished yet, so the points
        # and tie-breaks wouldn't match the team-ranking document).
        bound_round = self.ranking_round
        subtitle = (
            _('Before the first round')
            if bound_round == 0
            else _('After round #{round}').format(round=bound_round)
        )
        engine = tournament.pairing_variation.engine
        assert isinstance(engine, TeamRoundRobinPairingEngine)
        teams = self._get_option(TeamGridSortPrintOption).team_grid_sorter.sorted_teams(
            tournament
        )
        grid_id_by_team_id = {team.id: i + 1 for i, team in enumerate(teams)}

        # One cell list per (team, opponent): each encounter is the
        # scheduled round plus the match score once played.
        cells: dict[int, dict[int, list[dict[str, Any]]]] = {
            team.id: {opp.id: [] for opp in teams if opp.id != team.id}
            for team in teams
        }
        boards_by_round_pair: dict[tuple[int, frozenset], Any] = {}
        for round_ in range(1, tournament.rounds + 1):
            for tb in tournament.get_round_team_boards(round_):
                stb = tb.stored_team_board
                if stb.team_b_id is None:
                    continue
                boards_by_round_pair[
                    (round_, frozenset({stb.team_a_id, stb.team_b_id}))
                ] = tb
        for round_, pairs in engine.full_schedule(tournament).items():
            for a_id, b_id in pairs:
                if b_id is None:
                    continue
                match_tb = boards_by_round_pair.get((round_, frozenset({a_id, b_id})))
                if (
                    round_ <= bound_round
                    and match_tb is not None
                    and match_tb.match_score_pair is not None
                ):
                    played_match = match_tb
                    a_gp_eff, b_gp_eff = match_tb.effective_game_points
                    team_a_id = match_tb.stored_team_board.team_a_id
                else:
                    played_match = None
                    a_gp_eff = b_gp_eff = team_a_id = None
                for mine, theirs in ((a_id, b_id), (b_id, a_id)):
                    if mine not in cells or theirs not in cells[mine]:
                        continue
                    # The cell shows the *match outcome* for ``mine`` (win 1,
                    # draw ½, loss 0) — or F when ``mine`` forfeited the whole
                    # match. Decided on effective game points so round
                    # penalties / bonuses count, same basis as the standings.
                    score = None
                    if played_match is not None and team_a_id is not None:
                        if played_match.team_all_forfeit(mine):
                            score = 'F'
                        else:
                            mine_gp = a_gp_eff if team_a_id == mine else b_gp_eff
                            theirs_gp = b_gp_eff if team_a_id == mine else a_gp_eff
                            if mine_gp > theirs_gp:
                                score = '1'
                            elif mine_gp < theirs_gp:
                                score = '0'
                            else:
                                score = '½'
                    cells[mine][theirs].append({'round': round_, 'score': score})

        standings_by_team_id = {
            entry['team'].id: entry
            for entry in tournament.team_standings(after_round=bound_round)
        }

        # Player-level detail: one grid row per player, grouped by
        # team, individual game results in the cells.
        player_rows: list[dict[str, Any]] = []
        player_cells: dict[int, dict[int, list[str]]] = {}
        if self.by_player:
            ordered_players = [
                tournament.tournament_players_by_id[player.id]
                for team in teams
                for player in team.players
                if player.id in tournament.tournament_players_by_id
            ]
            grid_id_by_player_id = {
                tp.id: i + 1 for i, tp in enumerate(ordered_players)
            }
            for team in teams:
                first = True
                for player in team.players:
                    tp = tournament.tournament_players_by_id.get(player.id)
                    if tp is None:
                        continue
                    player_rows.append(
                        {
                            'tournament_player': tp,
                            'grid_id': grid_id_by_player_id[tp.id],
                            'team': team,
                            'first_of_team': first,
                        }
                    )
                    first = False
            player_cells = {
                tp.id: {opp.id: [] for opp in ordered_players if opp.id != tp.id}
                for tp in ordered_players
            }
            points_by_player_id: dict[int, float] = {
                tp.id: 0.0 for tp in ordered_players
            }
            for tp in ordered_players:
                for pairing in tp.pairings.values():
                    if pairing.round > bound_round:
                        continue
                    opponent_id = pairing.opponent_id
                    if not opponent_id or opponent_id not in player_cells[tp.id]:
                        continue
                    if pairing.result == Result.NO_RESULT:
                        continue
                    player_cells[tp.id][opponent_id].append(
                        pairing.result.to_berger_table
                    )
                    points_by_player_id[tp.id] += pairing.result.points(
                        tournament.point_values
                    )
            for row in player_rows:
                row['points_str'] = Utils.points_str(
                    points_by_player_id[row['tournament_player'].id]
                )
            return {
                'tournament': self.tournament,
                'subtitle': subtitle,
                'by_player': True,
                'player_rows': player_rows,
                'player_cells': player_cells,
                'grid_id_by_player_id': grid_id_by_player_id,
            }

        return {
            'tournament': self.tournament,
            'subtitle': subtitle,
            'by_player': False,
            'teams': teams,
            'grid_id_by_team_id': grid_id_by_team_id,
            'cells': cells,
            'standings_by_team_id': standings_by_team_id,
            # Mirror the team-ranking document so the Pts column and the
            # tie-break columns match it exactly.
            'primary_is_mp': (
                tournament.pairing_system.paired_by_team
                and tournament.primary_score == ScoreType.MATCH_POINTS
            ),
            'team_tie_breaks': tournament.team_tie_breaks,
        }


class FixedPairingTablePrintDocument(PrintDocument, ABC):
    """The fixed pairing schedule of a table-driven team system: one row
    per board, one column per round. Cells show ``<team letter><board> –
    <team letter><board>``; a legend maps each letter to its team.

    The whole schedule is known before a move is played, so this prints
    as soon as the teams are entered."""

    hide_for_individual_events = True

    @staticmethod
    @abstractmethod
    def system_type() -> type:
        """The pairing system this document belongs to."""

    @property
    @abstractmethod
    def wrong_system_message(self) -> str:
        """Shown when the chosen tournament uses another system."""

    @property
    @abstractmethod
    def no_table_message(self) -> str:
        """Shown when the tournament's shape has no table."""

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption]

    @property
    def title(self) -> str:
        return self.name

    @property
    def template_name(self) -> str:
        return '/admin/print/fixed_pairing_table.html'

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(
            isinstance(tournament.pairing_system, cls.system_type())
            for tournament in allowed_tournaments
        )

    def validate_options(self):
        super().validate_options()
        option = self._get_option(TournamentPrintOption)
        tournament = self.tournament
        if not isinstance(tournament.pairing_system, self.system_type()):
            raise OptionError(self.wrong_system_message, option)
        if self._table() is None:
            raise OptionError(self.no_table_message, option)

    def _ordered_teams(self) -> list:
        # Canonical order = pairing order; letter A = first team, B = second…
        return sorted(
            self.tournament.teams,
            key=lambda t: (
                t.pairing_number if t.pairing_number is not None else float('inf'),
                t.name.lower(),
            ),
        )

    def _table(self):
        tournament = self.tournament
        teams = self._ordered_teams()
        players_per_team = tournament.team_player_count or 0
        system = tournament.pairing_system
        assert isinstance(system, PairingTableProvider)
        return system.get_table(len(teams), players_per_team, tournament)

    @property
    def template_context(self) -> dict[str, Any]:
        tournament = self.tournament
        teams = self._ordered_teams()
        team_by_letter = {chr(ord('A') + i): team for i, team in enumerate(teams)}
        table = self._table()
        assert table is not None  # guarded by validate_options

        all_rounds = list(table.rounds)
        round_names = [f'{_("R")}{i + 1}' for i in range(table.regular_round_count)]

        def cell(p) -> str:
            return f'{p.white_team}{p.white_index} – {p.black_team}{p.black_index}'

        board_count = len(all_rounds[0]) if all_rounds else 0
        board_rows = [
            [cell(round_[board]) for round_ in all_rounds]
            for board in range(board_count)
        ]
        legend = [
            {'letter': letter, 'team': team_by_letter[letter]}
            for letter in sorted(team_by_letter)
        ]
        return {
            'tournament': tournament,
            'round_names': round_names,
            'board_rows': board_rows,
            'legend': legend,
        }


class MolterTablePrintDocument(FixedPairingTablePrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'molter-table'

    @staticmethod
    def static_name() -> str:
        return _('Molter table')

    @staticmethod
    def system_type() -> type:
        return MolterPairingSystem

    @property
    def wrong_system_message(self) -> str:
        return _('This document is only available for Molter tournaments.')

    @property
    def no_table_message(self) -> str:
        return _('No Molter table is available for this tournament size.')


class ScheveningenTablePrintDocument(FixedPairingTablePrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'scheveningen-table'

    @staticmethod
    def static_name() -> str:
        return _('Scheveningen table')

    @staticmethod
    def system_type() -> type:
        return ScheveningenPairingSystem

    @property
    def wrong_system_message(self) -> str:
        return _('This document is only available for Scheveningen tournaments.')

    @property
    def no_table_message(self) -> str:
        return _('No Scheveningen table is available for this tournament size.')


class RoundRobinSchedulePrintDocument(PrintDocument):
    """Round-by-round pairing schedule for a round-robin tournament
    (individual or team). Built from the Berger tables, so it's available
    before the rounds are paired: one row per match, one column per round.
    Cells show the two competitors by Berger number (individuals) or team
    letter (teams); a legend at the end maps each to its name."""

    @staticmethod
    def static_id() -> str:
        return 'round-robin-schedule'

    @staticmethod
    def static_name() -> str:
        return _('Round-robin schedule')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentPrintOption]

    @property
    def title(self) -> str:
        return self.name

    @property
    def template_name(self) -> str:
        return '/admin/print/round_robin_schedule.html'

    @staticmethod
    def _is_round_robin(tournament: Tournament) -> bool:
        return isinstance(
            tournament.pairing_system,
            (RoundRobinPairingSystem, TeamRoundRobinPairingSystem),
        )

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(cls._is_round_robin(t) for t in allowed_tournaments)

    def validate_options(self):
        super().validate_options()
        if not self._is_round_robin(self.tournament):
            raise OptionError(
                _('This document is only available for round-robin tournaments.'),
                self._get_option(TournamentPrintOption),
            )

    @property
    def template_context(self) -> dict[str, Any]:
        tournament = self.tournament
        rounds = tournament.rounds
        engine = tournament.pairing_variation.engine
        if isinstance(tournament.pairing_system, TeamRoundRobinPairingSystem):
            rounds_data = self._team_rounds_data(tournament, engine, rounds)
        else:
            rounds_data = self._individual_rounds_data(tournament, engine, rounds)
        return {'tournament': tournament, 'rounds_data': rounds_data}

    @staticmethod
    def _team_rounds_data(
        tournament: Tournament, engine: Any, rounds: int
    ) -> list[dict[str, Any]]:
        assert isinstance(engine, TeamRoundRobinPairingEngine)
        name_by_id = {team.id: team.name for team in tournament.teams}
        # The played match for each (round, team pair), to fill in the score.
        match_by_round_pair: dict[tuple[int, frozenset], Any] = {}
        for round_ in range(1, rounds + 1):
            for team_board in tournament.get_round_team_boards(round_):
                stb = team_board.stored_team_board
                if stb.team_b_id is None:
                    continue
                match_by_round_pair[
                    (round_, frozenset({stb.team_a_id, stb.team_b_id}))
                ] = team_board
        schedule = engine.full_schedule(tournament)
        rounds_data: list[dict[str, Any]] = []
        for round_ in range(1, rounds + 1):
            matches: list[dict[str, Any]] = []
            exempt: str | None = None
            for a_id, b_id in schedule.get(round_, []):
                if a_id is None or b_id is None:
                    real = a_id if a_id is not None else b_id
                    exempt = name_by_id.get(real) if real is not None else None
                    continue
                left_name = name_by_id.get(a_id, '')
                right_name = name_by_id.get(b_id, '')
                left_score = right_score = None
                played = match_by_round_pair.get((round_, frozenset({a_id, b_id})))
                if played is not None and played.match_score_pair is not None:
                    # Orient the displayed score to the stored team_a/team_b.
                    stb = played.stored_team_board
                    left_name = name_by_id.get(stb.team_a_id, '')
                    if stb.team_b_id is not None:
                        right_name = name_by_id.get(stb.team_b_id, '')
                    left_score, right_score = played.match_score_pair
                matches.append(
                    {
                        'left': left_name,
                        'right': right_name,
                        'left_score': left_score,
                        'right_score': right_score,
                    }
                )
            rounds_data.append({'number': round_, 'matches': matches, 'exempt': exempt})
        return rounds_data

    @staticmethod
    def _individual_rounds_data(
        tournament: Tournament, engine: Any, rounds: int
    ) -> list[dict[str, Any]]:
        assert isinstance(engine, BergerPairingEngine)
        player_count = tournament.player_count
        number_by_player = BergerNumbersSetting.get_value(tournament)
        player_by_number = {
            number: tournament.tournament_players_by_id[player_id]
            for player_id, number in number_by_player.items()
            if player_id in tournament.tournament_players_by_id
        }
        board_by_round_pair: dict[tuple[int, frozenset], Any] = {}
        for round_ in range(1, rounds + 1):
            for board in tournament.get_round_boards(round_):
                white = board.optional_white_tournament_player
                black = board.black_tournament_player
                if white is None or black is None:
                    continue
                board_by_round_pair[(round_, frozenset({white.id, black.id}))] = board
        rounds_data: list[dict[str, Any]] = []
        for round_ in range(1, rounds + 1):
            matches: list[dict[str, Any]] = []
            exempt: str | None = None
            for left_num, right_num in engine.get_round_pairings(player_count, round_):
                left_player = player_by_number.get(left_num)
                right_player = player_by_number.get(right_num)
                if left_player is None or right_player is None:
                    real = left_player or right_player
                    exempt = real.full_name if real is not None else None
                    continue
                left_score = right_score = None
                played_board = board_by_round_pair.get(
                    (round_, frozenset({left_player.id, right_player.id}))
                )
                if played_board is not None and played_board.result != Result.NO_RESULT:
                    raw = str(played_board.result)
                    if '-' in raw:
                        white_str, black_str = raw.split('-', 1)
                        white = played_board.optional_white_tournament_player
                        if white is not None and white.id == left_player.id:
                            left_score, right_score = white_str, black_str
                        else:
                            left_score, right_score = black_str, white_str
                matches.append(
                    {
                        'left': left_player.full_name,
                        'right': right_player.full_name,
                        'left_score': left_score,
                        'right_score': right_score,
                    }
                )
            rounds_data.append({'number': round_, 'matches': matches, 'exempt': exempt})
        return rounds_data


class PrizeListPrintDocument(PrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'prize-list'

    @staticmethod
    def static_name() -> str:
        return _('Prize list')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentsPrintOption]

    @property
    def title(self) -> str:
        return self.name

    @property
    def template_name(self) -> str:
        return '/admin/print/prize_list.html'

    @property
    def template_context(self) -> dict[str, Any]:
        prize_currency = self.get_event().prize_currency
        return {
            'tournaments': self.tournaments,
            'ordinal_integer': Utils.ordinal_integer,
            'prize_currency': prize_currency,
            'format_prize_value': partial(
                Utils.currency_value_str,
                currency=prize_currency,
            ),
        }


class PrizeAssignmentPrintDocument(PrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'prize-assignment'

    @staticmethod
    def static_name() -> str:
        return _('Prize assignment')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentsPrintOption, ShowWarningsPrintOption]

    @property
    def title(self) -> str:
        return _('Prize assignment')

    @property
    def template_name(self) -> str:
        return '/admin/print/prize_assignment.html'

    @property
    def template_context(self) -> dict[str, Any]:
        prize_currency = self.get_event().prize_currency
        return {
            'tournaments': self.tournaments,
            'show_warnings': self._get_option(ShowWarningsPrintOption).value,
            'ordinal_integer': Utils.ordinal_integer,
            'prize_currency': prize_currency,
            'format_prize_value': partial(
                Utils.currency_value_str,
                currency=prize_currency,
            ),
            'player_columns': self.player_columns,
        }

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        return PlayerColumnHandler(
            self.get_event(), ColumnUsage.PRINT
        ).get_prize_assignment_columns()


class PrizeReceiptsPrintDocument(PrintDocument):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'prize-receipts'

    @staticmethod
    def static_name() -> str:
        return _('Prize receipts')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentsPrintOption,
            NonMonetaryPrintOption,
        ]

    @property
    def title(self) -> str:
        return _('Prize receipts')

    @property
    def template_name(self) -> str:
        return '/admin/print/prize_receipts.html'

    @property
    def template_context(self) -> dict[str, Any]:
        prize_currency = self.get_event().prize_currency
        return {
            'tournaments': self.tournaments,
            'monetary_only': not self._get_option(NonMonetaryPrintOption).value,
            'ordinal_integer': Utils.ordinal_integer,
            'prize_currency': prize_currency,
            'format_prize_value': partial(
                Utils.currency_value_str,
                currency=prize_currency,
            ),
        }


@dataclass
class StatisticsSection:
    title: str
    rows: dict[str, int]
    subtitle: str | None = None


class StatisticsPrintDocument(PrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'statistics'

    @staticmethod
    def static_name() -> str:
        return _('Statistics')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [TournamentsPrintOption, ClubThresholdPrintOption]

    @property
    def title(self) -> str:
        return _('Participation Statistics')

    @property
    def template_name(self) -> str:
        return '/admin/print/statistics.html'

    def stat_section(
        self,
        attr_name: str,
        title: str,
        *,
        sort_key: Callable[[tuple[Any, int]], Any] | None = None,
        label_getter: Callable[[Any], Any] = lambda x: (
            x.name if hasattr(x, 'name') else x
        ),
        min_count: int | None = None,
        filter_func: Callable[[Any], bool] | None = None,
        subtitle_fn: Callable[[int], str] | None = None,
    ) -> StatisticsSection | None:
        values = [
            value
            for tournament in self.tournaments
            for p in tournament.tournament_players
            if (value := getattr(p, attr_name)) is not None
            and (filter_func(value) if filter_func else True)
        ]

        full_counter = Counter(values)

        if not full_counter:
            return None

        items: list[tuple[Any, int]] = list(full_counter.items())
        if min_count is not None:
            items = [(k, v) for k, v in items if v >= min_count]

        if sort_key:
            items = sorted(items, key=sort_key)

        subtitle = subtitle_fn(len(full_counter)) if subtitle_fn else None

        return StatisticsSection(
            title=title,
            rows={label_getter(k): v for k, v in items},
            subtitle=subtitle,
        )

    def rating_range_section(self) -> StatisticsSection | None:
        all_players = [p for t in self.tournaments for p in t.tournament_players]

        ratings = [p.rating for p in all_players if not p.estimated]
        estimated_count = sum(1 for p in all_players if p.estimated)

        if not ratings and not estimated_count:
            return None

        max_rating = max(ratings, default=0)
        buckets = [(0, 999)]
        r = 1000
        while r <= max_rating:
            buckets.append((r, r + 199))
            r += 200

        # Count players per bucket
        counter: Counter[tuple[int, int]] = Counter()
        for p in all_players:
            if p.estimated:
                continue
            for start, end in buckets:
                if start <= p.rating <= end:
                    counter[(start, end)] += 1
                    break

        rows: dict[str, int] = {
            _('{start} → {end}').format(start=start, end=end): counter[(start, end)]
            for (start, end) in reversed(buckets)
            if counter[(start, end)] > 0
        }

        if estimated_count:
            rows[_('Unrated *** PLURAL FOR UNRATED PLAYERS')] = estimated_count

        non_estimated_players = [
            player
            for tournament in self.tournaments
            for player in tournament.tournament_players
            if not player.estimated
        ]
        average_rating = (
            round(
                sum(player.rating for player in non_estimated_players)
                / len(non_estimated_players)
            )
            if non_estimated_players
            else None
        )

        return StatisticsSection(
            title=_('Rating ranges'),
            rows=rows,
            subtitle=_('Average rating: {rating}').format(rating=average_rating),
        )

    @property
    def template_context(self) -> dict[str, Any]:
        club_threshold = self._get_option(ClubThresholdPrintOption).value or 0

        statistics: list[StatisticsSection] = []

        per_plugin_sections = plugin_manager.hook_for_event(
            self.get_event(), 'get_extra_statistics_sections'
        )(document=self, tournaments=self.tournaments)

        for attr_name, title, sort_key, min_count, filter_func, subtitle_fn in [
            (
                'tournament',
                _('Tournaments'),
                lambda item: item[0].index,
                None,
                lambda x: x is not None,
                None,
            ),
            (
                'title',
                _('Titled players'),
                lambda item: -item[0].sort_index,
                None,
                lambda x: x != PlayerTitle.NONE,
                None,
            ),
            (
                'rating_type',
                _('Rating types'),
                lambda item: -item[0].value,
                None,
                None,
                None,
            ),
            (
                'category',
                _('Age categories'),
                lambda item: item[0],
                None,
                None,
                None,
            ),
            (
                'gender',
                _('Genders'),
                lambda item: item[0].value,
                None,
                None,
                None,
            ),
            (
                'federation',
                _('Federations'),
                lambda item: (-item[1], item[0].name),
                None,
                None,
                lambda count: ngettext(
                    '{count} federation represented',
                    '{count} federations represented',
                    count,
                ).format(count=count),
            ),
            (
                'club',
                _('Clubs'),
                lambda item: (
                    -item[1],
                    unicode_normalize(
                        item[0].name.lower().translate(str.maketrans('', '', '"\''))
                    ),
                ),
                club_threshold,
                lambda item: item.name != '',
                lambda count: ngettext(
                    '{count} club represented', '{count} clubs represented', count
                ).format(count=count),
            ),
        ]:
            if attr_name == 'tournament' and len(self.tournaments) <= 1:
                continue  # Skip if there's only one tournament

            for sections in per_plugin_sections:
                for section in sections:
                    if section.at == attr_name:
                        statistics.append(section)

            section = self.stat_section(
                attr_name,
                title,
                sort_key=sort_key,
                min_count=min_count,
                filter_func=filter_func,
                subtitle_fn=subtitle_fn,
            )

            if section:
                statistics.append(section)

            if attr_name == 'rating_type':
                section = self.rating_range_section()
                if section:
                    statistics.append(section)

        return {
            'tournaments': self.tournaments,
            'subtitle': self.subtitle,
            'statistics': statistics,
        }


class NormReportPrintDocument(PrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'norm-report'

    @staticmethod
    def static_name() -> str:
        return _('Norm Report')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            MandatoryPlayerPrintOption,
            Rule143ExemptionPrintOption,
        ]

    @property
    def title(self) -> str:
        return 'Certificate of Title Results'

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(
            tournament.rating == TournamentRating.STANDARD
            and tournament.has_norm_eligible_titled_players
            for tournament in allowed_tournaments
        )

    def validate_options(self):
        super().validate_options()
        tournament = self.tournament
        if tournament.rating != TournamentRating.STANDARD:
            raise OptionError(
                _(
                    'This document is only available for standard time control tournaments.'
                ),
                self._get_option(TournamentPrintOption),
            )
        if not tournament.has_norm_eligible_titled_players:
            raise OptionError(
                _('This tournament has no norm-eligible titled players.'),
                self._get_option(TournamentPrintOption),
            )

    @property
    def template_name(self) -> str:
        return '/admin/print/norm_report.html'

    @property
    def template_context(self) -> dict[str, Any]:
        from data.norms import apply_143abc_exemption
        from utils.types import Federation

        player_id = self._get_option(MandatoryPlayerPrintOption).value
        exemption_code = self._get_option(Rule143ExemptionPrintOption).value
        tournament_player = self.tournament.tournament_players_by_id[player_id]
        norms = {
            norm_title: norm
            for norm_title, norm in tournament_player.achieves_any_title_norm(
                rule_143_exemption=exemption_code
            ).items()
            if norm.meets_gender
            and tournament_player.title_on_norm_ladder(norm_title).sort_index
            < norm_title.player_title.sort_index
        }
        apply_143abc_exemption(
            norms,
            exemption_code,
            tournament_player.federation,
            Federation(self.get_event().federation),
        )
        return {
            'event': self.get_event(),
            'tournament': self.tournament,
            'is_swiss': self.tournament.pairing_system == SwissPairingSystem(),
            'start': self.tournament.start_date.strftime('%Y.%m.%d'),
            'end': self.tournament.stop_date.strftime('%Y.%m.%d'),
            'norms': norms,
            'tournament_player': tournament_player,
            'PlayerTitle': PlayerTitle,
            'rule_143_exemption_code': exemption_code,
        }


class NormCalculationDetailsPrintDocument(PrintDocument):
    """Per-norm calculation audit view — hidden from the document picker
    and only reachable via the "View calculation details" deep-link on
    the IT1 (NormReportPrintDocument).

    `is_available()` returns False so the picker never shows this doc.
    The route handler at `/document-view/{event}/{document}` doesn't
    consult `is_available`, so the deep-link continues to work. This
    keeps the picker clean for arbiters while exposing the full
    calculation audit at a stable URL."""

    @staticmethod
    def static_id() -> str:
        return 'norm-calculation-details'

    @staticmethod
    def static_name() -> str:
        return _('Norm Calculation Details')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            MandatoryPlayerPrintOption,
            NormChoicePrintOption,
            Rule143ExemptionPrintOption,
        ]

    @property
    def title(self) -> str:
        return 'Norm Calculation Details'

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        # Hidden from the picker. Reach this doc via the IT1's
        # "View calculation details" deep-link instead.
        return False

    @property
    def template_name(self) -> str:
        return '/admin/print/norm_calculation_details.html'

    @property
    def template_context(self) -> dict[str, Any]:
        from data.norms import (
            apply_143abc_exemption,
            compute_big_tournament_exemption_trail,
            compute_high_level_tournament_trail,
        )
        from utils.enum import TitleNorm as _TitleNorm
        from utils.types import Federation

        player_id = self._get_option(MandatoryPlayerPrintOption).value
        exemption_code = self._get_option(Rule143ExemptionPrintOption).value
        tournament_player = self.tournament.tournament_players_by_id[player_id]
        norms = {
            norm_title: norm
            for norm_title, norm in tournament_player.achieves_any_title_norm(
                rule_143_exemption=exemption_code
            ).items()
            if norm.meets_gender
            and tournament_player.title_on_norm_ladder(norm_title).sort_index
            < norm_title.player_title.sort_index
        }
        apply_143abc_exemption(
            norms,
            exemption_code,
            tournament_player.federation,
            Federation(self.get_event().federation),
        )
        norm_choice_value = self._get_option(NormChoicePrintOption).value
        # Resolve the chosen norm name to the TitleNorm enum, scoped to
        # the norms this player can claim. Falls back to the first
        # available if the picked one isn't in the player's list.
        chosen_norm = next(
            (tn for tn in norms.keys() if tn.name == norm_choice_value),
            next(iter(norms.keys()), None),
        )
        chosen_norm_result = norms.get(chosen_norm) if chosen_norm else None
        # Threshold the template displays for 1.4.1 — comes straight
        # from the TitleNorm enum (9 for Swiss, 10 for DRR).
        min_games_threshold = (
            _TitleNorm.minimum_rounds(self.tournament) if chosen_norm else 9
        )
        # Two score proofs sharing the same shape — used by section 3 to
        # show the rounding + 1.4.9 dp lookup explicitly.
        # `actual_score_proof`: the player's actual score (upper table).
        # `score_required_proof`: the tipping score that just clears Rp
        # (lower table, the "minimum score to clear the Rp threshold").
        actual_score_proof = self._build_score_proof_for(
            chosen_norm_result,
            chosen_norm_result.score if chosen_norm_result else None,
        )
        tipping_score = (
            chosen_norm_result.score - chosen_norm_result.performance_diff
            if chosen_norm_result and chosen_norm_result.performance_diff is not None
            else None
        )
        score_required_proof = self._build_score_proof_for(
            chosen_norm_result, tipping_score
        )
        return {
            'event': self.get_event(),
            'tournament': self.tournament,
            'is_swiss': self.tournament.pairing_system == SwissPairingSystem(),
            'start': self.tournament.start_date.strftime('%Y.%m.%d'),
            'end': self.tournament.stop_date.strftime('%Y.%m.%d'),
            'norms': norms,
            'chosen_norm': chosen_norm,
            'chosen_norm_result': chosen_norm_result,
            'tournament_player': tournament_player,
            'min_games_threshold': min_games_threshold,
            'rule_143_exemption_code': exemption_code,
            'actual_score_proof': actual_score_proof,
            'score_required_proof': score_required_proof,
            'exemption_trail': compute_big_tournament_exemption_trail(self.tournament),
            'high_level_trail': compute_high_level_tournament_trail(self.tournament),
        }

    @staticmethod
    def _build_score_proof_for(norm_result, score) -> dict[str, Any] | None:
        """Spell out the Rp computation for a given score on this norm.

        Returns None when there's nothing to show (no result, no score,
        or zero played games). Otherwise returns the rounding + lookup
        chain that produces Rp:
        - `score`: the score being explained (as-is).
        - `raw_percent`: 100 × score / played, unrounded.
        - `rounded_percent`: FIDE-rounded (half up) to integer.
        - `dp`: bonus looked up from the 1.4.9 table at the rounded
          fractional. Negative for sub-50% scores.
        - `rp`: Ra + dp.
        Used for both the actual-score row in section 3 and the
        tipping-score proof below it.
        """
        if norm_result is None or score is None or not norm_result.played_games:
            return None
        raw_percent = 100 * score / norm_result.played_games
        rounded_percent = Utils.round_ranking(raw_percent)
        dp = Utils.performance_bonus(rounded_percent / 100)
        return {
            'score': score,
            'raw_percent': raw_percent,
            'rounded_percent': rounded_percent,
            'dp': dp,
            'rp': norm_result.average_rating + dp,
        }


class TournamentNormsSummaryPrintDocument(PrintDocument):
    """Tournament-wide summary of all title norms achieved.

    Lists every player who picked up at least one norm above their current
    title, with the per-norm performance figures. Companion to the per-player
    IT1 form (NormReportPrintDocument).
    """

    @staticmethod
    def static_id() -> str:
        return 'tournament-norms-summary'

    @staticmethod
    def static_name() -> str:
        return _('Tournament Norms Summary')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            Rule143ExemptionPrintOption,
            NormsForecastSortPrintOption,
        ]

    @property
    def title(self) -> str:
        return _('Title Norms Achieved')

    @classmethod
    def is_available(cls, allowed_tournaments: list[Tournament]) -> bool:
        if not super().is_available(allowed_tournaments):
            return False
        return any(
            tournament.rating == TournamentRating.STANDARD
            and tournament.has_norm_eligible_titled_players
            for tournament in allowed_tournaments
        )

    def validate_options(self):
        super().validate_options()
        tournament = self.tournament
        if tournament.rating != TournamentRating.STANDARD:
            raise OptionError(
                _(
                    'This document is only available for standard time control tournaments.'
                ),
                self._get_option(TournamentPrintOption),
            )
        if not tournament.has_norm_eligible_titled_players:
            raise OptionError(
                _('This tournament has no norm-eligible titled players.'),
                self._get_option(TournamentPrintOption),
            )

    @property
    def template_name(self) -> str:
        return '/admin/print/tournament_norms_summary.html'

    @property
    def template_context(self) -> dict[str, Any]:
        tournament = self.tournament
        common = {
            'event': self.get_event(),
            'tournament': tournament,
            'start': tournament.start_date.strftime('%Y.%m.%d'),
            'end': tournament.stop_date.strftime('%Y.%m.%d'),
            'PlayerTitle': PlayerTitle,
            'TitleNorm': TitleNorm,
            'Result': Result,
            # Forwarded to the per-row deep-links so the clicked-through
            # IT1 / details doc keeps the arbiter's event-type selection
            # (1.4.3a/b/c).
            'rule_143_exemption_code': self._get_option(
                Rule143ExemptionPrintOption
            ).value,
        }
        if tournament.finished:
            return common | {'mode': 'achieved'} | self._achieved_context()
        forecast_round = self._find_forecastable_round()
        if forecast_round is not None:
            return (
                common | {'mode': 'forecast'} | self._forecast_context(forecast_round)
            )
        return common | {'mode': 'pending'}

    def _achieved_context(self) -> dict[str, Any]:
        from data.norms import apply_143abc_exemption
        from utils.types import Federation

        exemption_code = self._get_option(Rule143ExemptionPrintOption).value
        event_federation = Federation(self.get_event().federation)
        achievers: list[dict[str, Any]] = []
        for tournament_player in self.tournament.tournament_players_by_id.values():
            all_norms = tournament_player.achieves_any_title_norm(
                rule_143_exemption=exemption_code
            )
            # Apply 1.4.3a/b/c exemption before is_met filtering — the
            # exemption can flip a is_met=False norm to is_met=True for
            # players from the event's federation (or all players for c).
            apply_143abc_exemption(
                all_norms,
                exemption_code,
                tournament_player.federation,
                event_federation,
            )
            achieved = {
                tn: result
                for tn, result in all_norms.items()
                if result.is_met
                and tournament_player.title_on_norm_ladder(tn).sort_index
                < tn.player_title.sort_index
            }
            if achieved:
                achievers.append({'player': tournament_player, 'norms': achieved})

        # Stable ordering: highest norm first (GM > IM > WGM > WIM), then by
        # the player's tie-break-aware name key.
        def _sort_key(entry):
            top_norm = max(
                entry['norms'].keys(), key=lambda tn: tn.player_title.sort_index
            )
            return (-top_norm.player_title.sort_index, entry['player'].name_sort_key)

        achievers.sort(key=_sort_key)
        return {'achievers': achievers}

    def _find_forecastable_round(self) -> int | None:
        """The highest round that is paired AND has at least one unentered
        result across all players. None if no such round exists.

        Forecast meaning: this is the next round about to be played. In an
        11-round event with R10/R11 not yet paired, this is the most recent
        paired round; once R11 is paired, this jumps to R11.
        """
        best: int | None = None
        for p in self.tournament.tournament_players_by_id.values():
            for rnd, pairing in p.pairings_by_round.items():
                if (
                    pairing.opponent is not None
                    and pairing.result == Result.NO_RESULT
                    and (best is None or rnd > best)
                ):
                    best = rnd
        return best

    @staticmethod
    def _played_games_before(player, round_: int) -> int:
        """Count of the player's played games in rounds strictly < round_.
        Used to gate forecast eligibility on the 1.4.1 games threshold."""
        return sum(
            1
            for r, pairing in player.pairings_by_round.items()
            if r < round_ and pairing.played
        )

    def _forecast_context(self, forecast_round: int) -> dict[str, Any]:
        from data.norms import TitleNormForecaster

        exemption_code = self._get_option(Rule143ExemptionPrintOption).value
        sort_mode = self._get_option(NormsForecastSortPrintOption).value
        self.tournament.ensure_tournament_player_ranks_computed()
        candidates: list[dict[str, Any]] = []
        for tournament_player in self.tournament.tournament_players_by_id.values():
            forecaster = TitleNormForecaster(
                tournament_player,
                rule_143_exemption=exemption_code,
            )
            forecastable = forecaster.can_forecast_round(forecast_round)
            decided = forecaster.round_result_decided(forecast_round)
            if not forecastable and not decided:
                continue
            # 1.4.1 eligibility — player must be one played-game short of
            # the minimum so this round can plausibly bring them to it.
            # Use the lowest min_games across norms (DRR sits at 10, Swiss
            # at 9) so we don't filter someone who qualifies for a lower
            # norm but not yet for GM.
            min_needed = min(
                tn.minimum_rounds(tournament_player.tournament)
                for tn in TitleNorm.values()
            )
            if (
                self._played_games_before(tournament_player, forecast_round)
                < min_needed - 1
            ):
                continue
            requirements: dict[TitleNorm, ForecastRequirement | None]
            if forecastable:
                requirements = {
                    tn: r
                    for tn, r in forecaster.chaseable_norms(forecast_round).items()
                }
                achieved = False
            else:
                # Her game is in even though the round is still open for
                # others — show the norms she actually clinched rather
                # than dropping her from the forecast.
                requirements = {
                    tn: None for tn in forecaster.decided_norms(forecast_round)
                }
                achieved = True
            if not requirements:
                continue
            pairing = tournament_player.pairings_by_round[forecast_round]
            board = pairing.board
            candidates.append(
                {
                    'player': tournament_player,
                    'opponent': pairing.opponent,
                    'requirements': requirements,  # dict[TitleNorm, ForecastRequirement | None]
                    'achieved': achieved,
                    'rank': tournament_player.rank,
                    'board_number': board.number if board is not None else None,
                }
            )

        self._sort_candidates(candidates, sort_mode)
        return {
            'candidates': candidates,
            'forecast_round': forecast_round,
            'sort_mode': sort_mode,
        }

    @staticmethod
    def _sort_candidates(candidates: list[dict[str, Any]], sort_mode: str) -> None:
        """Order forecast rows per the arbiter's sort choice. Unpaired
        (board-less) players sink to the bottom of a table-number sort."""

        def _highest_norm_key(entry):
            highest_norm = max(
                entry['requirements'].keys(),
                key=lambda tn: tn.player_title.sort_index,
            )
            return -highest_norm.player_title.sort_index

        if sort_mode == 'name':
            candidates.sort(key=lambda e: e['player'].name_sort_key)
        elif sort_mode == 'table':
            candidates.sort(
                key=lambda e: (
                    e['board_number'] is None,
                    e['board_number'] or 0,
                )
            )
        else:  # 'rank'
            candidates.sort(key=lambda e: e['rank'])


class QRCodePrintDocument(PrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'qrcode'

    @staticmethod
    def static_name() -> str:
        return _('QR Code')

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [QRCodePrintOption, TournamentPrintOption, QRCodeNetworkPrintOption]

    @property
    def title(self) -> str:
        qrcode_type = self._get_option(QRCodePrintOption).qrcode_type
        return qrcode_type.title(self)

    @property
    def template_name(self) -> str:
        return '/admin/print/qrcode.html'

    @property
    def template_context(self) -> dict[str, Any]:
        qrcode_type = self._get_option(QRCodePrintOption).qrcode_type

        success, result = qrcode_type.url(self)
        qrcode_base64 = qrcode_type.get_qr_code(result) if success else None

        return {
            'qrcode_type': qrcode_type,
            'subtitle': qrcode_type.subtitle(self),
            'info': qrcode_type.info(self),
            'error_message': result if not success else None,
            'qrcode_url': result if success else None,
            'qrcode_base64': qrcode_base64,
        }


class PlaceCardPrintDocument(PrintDocument):
    @staticmethod
    def static_id() -> str:
        return 'place-card'

    @staticmethod
    def static_name() -> str:
        return _('Place Cards')

    @property
    def title(self) -> str:
        return ''

    @property
    def place_card_type(self) -> PlaceCardType:
        return self._get_option(PlaceCardPrintOption).place_card_type

    @property
    def place_card_template(self) -> PlaceCardTemplate:
        return self._get_option(PlaceCardTemplatePrintOption).place_card_template

    @property
    def player_ids(self) -> list[int]:
        return self._get_option(OptionalPlayersPrintOption).value

    @property
    def at_round(self) -> int:
        return self._get_option(RoundPrintOption).value or self.tournament.current_round

    @property
    def mirror(self) -> bool:
        return self._get_option(PlaceCardMirrorPrintOption).value

    @property
    def board_numbers(self) -> set[int]:
        return self._get_option(PlaceCardBoardNumbersPrintOption).board_numbers

    @property
    def crop_marks(self) -> PlaceCardCropMarks:
        return self._get_option(PlaceCardCropMarksPrintOption).place_card_crop_marks

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            PlaceCardPrintOption,
            PlaceCardTemplatePrintOption,
            TournamentPrintOption,
            OptionalPlayersPrintOption,
            RoundPrintOption,
            PlaceCardMirrorPrintOption,
            PlaceCardCropMarksPrintOption,
            PlaceCardBoardNumbersPrintOption,
        ]

    @property
    def template_context(self) -> dict[str, Any]:
        return self.place_card_template.template_context(
            event=self.get_event(),
            tournament=self.tournament,
            round_=self.at_round,
            mirror=self.mirror,
            place_card_crop_marks=self.crop_marks,
            board_numbers=self.board_numbers,
            player_ids=self.player_ids,
        )

    @property
    def template_name(self) -> str:
        return str(
            PlaceCardTemplate.load(
                self._get_option(PlaceCardTemplatePrintOption).value
            ).template_name
        )

    def validate_options(self):
        super().validate_options()
        template_option = self._get_option(PlaceCardTemplatePrintOption)
        try:
            PlaceCardTemplate.load(template_option.value)
        except KeyError:
            raise OptionError(
                f'Unknown template [{template_option.value}]', template_option
            )


class IndividuelTeamRankingPrintDocument(PrintDocument, ABC):
    hide_for_team_events = True

    @staticmethod
    def static_id() -> str:
        return 'individual-team-ranking'

    @staticmethod
    def static_name() -> str:
        return _('Individual team ranking')

    @property
    def template_name(self) -> str:
        return '/admin/print/individual_team_ranking.html'

    @staticmethod
    def available_options() -> list[type[PrintOption]]:
        return [
            TournamentPrintOption,
            RoundPrintOption,
            IndividualTeamTypePrintOption,
            IndividualTeamSizePrintOption,
            IndividualTeamMinGenderCountPrintOption,
            IndividualTeamMaxPerEntityPrintOption,
            IndividualTeamDisplayIncompletePrintOption,
        ]

    @property
    def team_type(self) -> IndividualTeamType:
        return self._get_option(IndividualTeamTypePrintOption).team_type

    @property
    def ranking_round(self) -> int:
        return (
            self._get_option(RoundPrintOption).value
            or self.tournament.max_ranking_round
        )

    @cached_property
    def display_incomplete_teams(self) -> bool:
        """Returns True if incomplete teams must be displayed."""
        return self._get_option(IndividualTeamDisplayIncompletePrintOption).value

    @property
    def team_size(self) -> int:
        """Returns the minimum number of players to form a team."""
        return self._get_option(IndividualTeamSizePrintOption).value

    @property
    def title(self) -> str:
        return self.team_type.document_title(self.ranking_round)

    @property
    def max_teams_per_entity(self) -> int | None:
        return self._get_option(IndividualTeamMaxPerEntityPrintOption).value

    @property
    def min_gender_count(self) -> int:
        return self._get_option(IndividualTeamMinGenderCountPrintOption).value or 0

    @property
    def youngest_team_last_tie_break(self) -> bool:
        """Returns True to use the age as the last tie-break (youngest wins)."""
        return False

    @property
    def team_type_table_header(self) -> str:
        return self.team_type.overall_table_header

    def _extract_team_from_pool(
        self,
        pool_in_order: list[TournamentPlayer],
    ) -> list[TournamentPlayer]:
        """
        Build one team (up to *team_size* contributors) from a club's pool.
        Returns (selected_players, meta)."""
        selected: list[TournamentPlayer] = []
        if self.min_gender_count:
            women = [p for p in pool_in_order if p.gender == PlayerGender.WOMAN]
            chosen_women = women[: self.min_gender_count]
            selected.extend(chosen_women)
            men = [p for p in pool_in_order if p.gender == PlayerGender.MAN]
            chosen_men = [p for p in men if p not in selected][: self.min_gender_count]
            selected.extend(chosen_men)
        # Fill ANY slots (do NOT compensate missing girl/boy with extra ANY)
        already = set(p.id for p in selected)
        remainder = [p for p in pool_in_order if p.id not in already]
        if self.team_size > 2 * self.min_gender_count:
            any_fillers = remainder[: self.team_size - 2 * self.min_gender_count]
            selected.extend(any_fillers)
        selected.sort(key=lambda p: p.rank)
        return selected

    def _get_team_sort_key(self, t: IndividualTeam) -> tuple:
        """Returns the key used to sort the teams."""
        base: list[float] = [
            0 if t.is_complete else 1,
            -t.total_points,
        ] + [-x for x in getattr(t, 'tie_break_sums', [])]
        if self.youngest_team_last_tie_break:
            base.append(-(t.avg_age_years or 0.0))
        return tuple(base)

    def _sort_teams(self, teams: list[IndividualTeam]):
        """Remove useless team labels and sort the teams."""
        teams_by_entity: dict[str, list[IndividualTeam]] = defaultdict(list)
        for team in teams:
            teams_by_entity[team.entity].append(team)

        # Remove labels when there's only one team for that entity
        for team_list in teams_by_entity.values():
            if len(team_list) == 1:
                team_list[0].label = ''

        teams.sort(key=self._get_team_sort_key)
        return teams

    @property
    def ordered_teams(self) -> list[IndividualTeam]:
        """
        Produce ranked teams (A, B, ...).
        Uses tournament-wide ordering and points/tiebreaks already computed by compute_player_ranks().
        """

        assert self.event is not None
        ordered_players: list[TournamentPlayer] = [
            tournament_player
            for tournament_player in self.tournament.compute_tournament_player_ranks(
                after_round=self.ranking_round
            ).values()
            if (not self.tournament.started or tournament_player.has_played_games)
            and not tournament_player.is_excluded_from_standings
        ]

        # Group by entity
        players_by_entity: dict[Any, list[TournamentPlayer]] = {}
        for player in ordered_players:
            if entity := self.team_type.get_player_entity(player):
                players_by_entity.setdefault(entity, []).append(player)

        teams: list[IndividualTeam] = []
        for entity, pool in players_by_entity.items():
            remaining = list(pool)
            team_idx = 0
            while remaining and (
                self.max_teams_per_entity is None
                or team_idx < self.max_teams_per_entity
            ):
                team_idx += 1
                label = chr(ord('A') + (team_idx - 1))  # "A", "B", ...
                selected_players = self._extract_team_from_pool(remaining)
                if not selected_players:
                    break
                team = IndividualTeam(
                    tournament=self.tournament,
                    team_size=self.team_size,
                    min_gender_count=self.min_gender_count,
                    entity=entity,
                    label=label,
                    players=selected_players,
                    type=self.team_type,
                )
                if self.display_incomplete_teams or team.is_complete:
                    teams.append(team)
                # Consume used players for the next team (B, C, …)
                used_ids = {p.id for p in selected_players}
                remaining = [p for p in remaining if p.id not in used_ids]
                if label == 'Z':
                    break
        self._sort_teams(teams)
        return teams

    @override
    def validate_options(self):
        super().validate_options()
        ranking_round = self._get_option(RoundPrintOption)
        if ranking_round.value is None:
            if self.tournament.max_ranking_round < 1:
                raise OptionError(
                    _('The tournament has not yet started.'),
                    ranking_round,
                )
            return
        if ranking_round.value > self.tournament.rounds:
            raise OptionError(
                _(
                    'This round is not valid (the tournament has {rounds} rounds).'
                ).format(rounds=self.tournament.rounds),
                ranking_round,
            )
        if ranking_round.value > self.tournament.max_ranking_round:
            raise OptionError(
                _('This round is not finished (last finished: #{round}).').format(
                    round=self.tournament.max_ranking_round
                ),
                ranking_round,
            )

    @property
    def player_columns(self) -> list[TournamentPlayerTableColumn]:
        tournament = self.tournament
        column_types: list[Callable[[ColumnUsage], TournamentPlayerTableColumn]] = [
            columns.RankColumn,
            columns.NameColumn,
            columns.CategoryColumn,
            columns.GenderColumn,
        ]
        for index in range(len(tournament.team_ranking_tie_breaks)):
            column_types.append(
                partial(
                    columns.TeamRankingTieBreakColumn,
                    tournament=tournament,
                    index=index,
                )
            )
        return PlayerColumnHandler(self.get_event(), ColumnUsage.PRINT).get_columns(
            column_types
        )

    @property
    def template_context(self) -> dict[str, Any]:
        return {
            'tournament': self.tournament,
            'subtitle': self.tournament.name,
            'ordered_teams': self.ordered_teams,
            'player_columns': self.player_columns,
            'ordinal_integer': Utils.ordinal_integer,
            'localized_number': Utils.localized_number,
            'points_str': Utils.points_str,
        }
