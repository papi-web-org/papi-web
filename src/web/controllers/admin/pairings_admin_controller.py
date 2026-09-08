from operator import attrgetter

from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ClientException

from common import experimental_features_enabled

from collections import defaultdict
from typing import Annotated, Any, Optional

from data.access_levels.actions import AuthAction
from data.input_output import DataSourceManager
from data.pairings.bbp_history import TeamTournamentHistory
from data.pairings.engines import BbpPairings, TeamSwissEngine
from data.pairings.bbp_history import TournamentHistoryPlayer
from litestar import delete, get, patch, put, post
from litestar.plugins.htmx import ClientRefresh, HTMXRequest
from litestar.enums import RequestEncodingType
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Template
from litestar.status_codes import HTTP_200_OK
from litestar_htmx import HTMXTemplate
from litestar.channels import ChannelsPlugin

from common.exception import SharlyChessException
from common.i18n import _, ngettext
from common.logger import get_logger
from data.board import Board
from data.player import TournamentPlayer
from data.event import Event
from data.teams.team import Team
from data.teams.team_board import TeamBoard
from data.print_documents.documents import (
    PairingPrintDocument,
    PlayerRankingPrintDocument,
)
from data.safety_mode import RoundStatus, SafetyMode, PairingAction
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from utils.enum import CheckInStatus, Result, ScoreType, TeamByeType
from plugins.manager import plugin_manager
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminWebContext,
    BaseEventAdminController,
)
from web.controllers.admin.player_admin_controller import PlayerAdminController
from web.controllers.base_controller import WebContext
from web.guards import (
    EventGuard,
    TournamentActionGuard,
    SetResultGuard,
)
from web.messages import Message
from web.session import (
    SessionPairingsShowWithoutResults,
    SessionPairingsSafetyMode,
    PairingsPageIdentifier,
    SessionPairingsPageIdentifier,
    SessionPairingsSelectedTournament,
    SessionPairingsSelectedRound,
    SessionPairingsBoardSort,
)

logger = get_logger()

# Bonus / penalty points are exported in the TRF26 299 record, whose
# point fields are ``[-]11.5``: four columns holding either a sign or a
# second integer digit, never both. Rounded inwards to a multiple of the
# form's 0.5 step, which is anchored on the minimum — an unaligned bound
# would make ordinary values like -1 unenterable.
MIN_POINT_ADJUSTMENT = -9.5
MAX_POINT_ADJUSTMENT = 99.5


class PairingsAdminWebContext(BaseEventAdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        tournament_id: int | None = None,
        round_: int | None = None,
        board_id: int | None = None,
        player_id: int | None = None,
        action: PairingAction | None = None,
        load_check_in_data: bool = False,
        reload_event: bool = False,
    ):
        super().__init__(request, reload_event)
        self.admin_tournament: Tournament | None = None
        self.allowed_tournaments = self.client.allowed_tournaments_for_action(
            AuthAction.VIEW_PAIRINGS_TAB
        )
        event = self.get_admin_event()
        if tournament_id:
            if tournament_id not in event.tournaments_by_id:
                raise NotFoundException(
                    f'Unknown tournament ID [{tournament_id}] '
                    f'for event [{event.uniq_id}]'
                )
            self.admin_tournament = event.tournaments_by_id[tournament_id]
        elif self.allowed_tournaments:
            session_tournament_id = SessionPairingsSelectedTournament(
                self.request, event
            ).get()
            if session_tournament_id in [
                tournament.id for tournament in self.allowed_tournaments
            ]:
                self.admin_tournament = event.tournaments_by_id[session_tournament_id]
            else:
                self.admin_tournament = self.allowed_tournaments[0]
        if load_check_in_data:
            plugin_manager.hook_for_event(event, 'load_tournament_check_in_data')(
                tournament=self.get_admin_tournament()
            )

        self.display_rankings = self.admin_tournament and (
            self.admin_tournament.finished
            and (round_ is None or round_ > self.admin_tournament.rounds)
        )

        if self.admin_tournament is None:
            self.admin_round = 0
        elif round_:
            self.admin_round = round_
        elif session_round := SessionPairingsSelectedRound(
            self.request, self.admin_tournament
        ).get():
            max_round = (
                self.admin_tournament.current_round or 1
            ) + self.admin_tournament.finished
            self.admin_round = min(session_round, max_round)
        else:
            self.admin_round = self.admin_tournament.current_round or 1

        if self.admin_tournament and (
            self.admin_round > self.admin_tournament.rounds or self.display_rankings
        ):
            self.admin_round = self.admin_tournament.rounds

        self.round_status = RoundStatus.from_round(
            self.admin_round,
            self.admin_tournament.current_round if self.admin_tournament else 0,
        )

        self.admin_boards: list[Board] = []
        self.admin_boards_sortable = False
        self.admin_board_sort = SessionPairingsBoardSort(request).get()
        # Set after a board-only points update and cleared by full-page rendering.
        self.scoped_recompute = False
        if self.admin_tournament is not None:
            if self.display_rankings:
                self.admin_tournament.compute_tournament_player_ranks()
            else:
                only_players = self._points_recompute_scope(event, board_id, action)
                self.scoped_recompute = only_players is not None
                self.admin_tournament.set_for_round(
                    self.admin_round, only_players=only_players
                )
                self.admin_boards = self.admin_tournament.get_round_boards(
                    self.admin_round
                )
                self.admin_boards_sortable = (
                    not event.is_team_event
                    and not self.admin_tournament.leave_fixed_board_holes
                    and any(
                        player.fixed
                        for player in self.admin_tournament.tournament_players
                    )
                )
                if self.admin_boards_sortable and self.admin_board_sort != 'natural':
                    self.admin_boards = sorted(
                        self.admin_boards, key=lambda board: board.number
                    )

        if SessionPairingsShowWithoutResults(request).get():
            self.admin_filtered_boards = [
                b for b in self.admin_boards if b.result == Result.NO_RESULT
            ]
        else:
            self.admin_filtered_boards = self.admin_boards

        self.admin_unpaired: list[TournamentPlayer] = []
        self.admin_unpaired_holes: list[dict[str, Any]] = []
        self.admin_bye_players: list[TournamentPlayer] = []
        self.admin_absent_players: list[TournamentPlayer] = []
        self.admin_team_bye: list[Team] = []
        self.admin_team_unpaired: list[Team] = []
        self.admin_team_absent: list[Team] = []
        if not self.display_rankings:
            self.reload_unpaired_player_lists()
            self.reload_unpaired_team_lists()

        self.admin_board: Board | None = None
        if board_id is not None:
            self.admin_board = next(
                (b for b in self.admin_boards if b.identifier == board_id), None
            )
            if self.admin_board is None and not event.is_team_event:
                self.admin_board = next(
                    (b for b in self.admin_boards if b.board_id == board_id), None
                )

        self.admin_player: TournamentPlayer | None = None
        if player_id is not None:
            assert self.admin_tournament is not None
            self.admin_player = next(
                (
                    p
                    for p in self.admin_tournament.tournament_players
                    if p.id == player_id
                ),
                None,
            )

        self.safety_mode = SafetyMode.SAFE
        if not tournament_id:
            # Reset the session safety mode if coming from another page
            SessionPairingsPageIdentifier(request).unset()
        else:
            page_identifier = PairingsPageIdentifier(
                event.uniq_id, tournament_id, self.admin_round
            )

            session_page_identifier = SessionPairingsPageIdentifier(request).get()
            if page_identifier != session_page_identifier:
                SessionPairingsPageIdentifier(request).set(page_identifier)
                SessionPairingsSafetyMode(request).set(SafetyMode.SAFE)
            else:
                self.safety_mode = SessionPairingsSafetyMode(request).get()
        self.requires_refresh = False
        if action:
            permission_handler = (
                self.get_admin_tournament().pairing_system.permission_handler
            )
            try:
                if not permission_handler.validate_action(
                    action, self.round_status, self.safety_mode
                ):
                    required_mode = permission_handler.required_mode(
                        self.round_status, action
                    )
                    SessionPairingsSafetyMode(request).set(required_mode)
                    self.safety_mode = required_mode
                    self.requires_refresh = True
            except SharlyChessException:
                raise ClientException(
                    f'Action [{action}] does not exist for '
                    f'round with status [{self.round_status}].'
                )

    def _points_recompute_scope(
        self,
        event: Event,
        board_id: int | None,
        action: 'PairingAction | None',
    ) -> 'list[TournamentPlayer] | None':
        """Return the affected board's players, or ``None`` for the full field."""
        if action != PairingAction.RESULT_UPDATE or board_id is None:
            return None
        if event.is_team_event or self.display_rankings:
            return None
        assert self.admin_tournament is not None
        board = next(
            (
                b
                for b in self.admin_tournament.get_round_boards(self.admin_round)
                if b.identifier == board_id or b.board_id == board_id
            ),
            None,
        )
        if board is None:
            return None
        players = [
            player
            for player in (
                board.optional_white_tournament_player,
                board.black_tournament_player,
            )
            if player is not None
        ]
        return players or None

    def reload_unpaired_player_lists(self):
        self.admin_absent_players = []
        self.admin_bye_players = []
        self.admin_unpaired = []
        if not self.admin_tournament:
            return
        # Team-vs-team systems pair teams, not individual players; the unpaired
        # / bye / absent player sidebar isn't meaningful in that mode.
        if (
            self.admin_tournament.event.is_team_event
            and self.admin_tournament.pairing_system.paired_by_team
        ):
            return
        unpaired = self.admin_tournament.get_unpaired_tournament_players(
            self.admin_boards
        )
        if self.admin_tournament.event.is_team_event:
            # Flat team systems (Molter) reach here — team-vs-team systems
            # already returned above. Only players seated in a team's line-up
            # for this round belong in the "to pair" list; benched players
            # aren't meant to play. Reads the line-up, never writes it.
            round_ = self.admin_round or 1
            seated_ids: set[int] = set()
            for team in self.admin_tournament.teams:
                for player in team.effective_round_slots(round_):
                    if player is not None:
                        seated_ids.add(player.id)
            unpaired = [player for player in unpaired if player.id in seated_ids]
            self.admin_unpaired_holes = self._unpaired_holes(round_)
        if self.admin_tournament.pairing_system.split_unpaired_and_bye_players:
            for player in sorted(unpaired, key=attrgetter('name_sort_key')):
                check_in_status = player.check_in_status_for_round(self.admin_round)
                if check_in_status == CheckInStatus.ABSENT:
                    self.admin_absent_players.append(player)
                elif check_in_status == CheckInStatus.PRESENT:
                    self.admin_unpaired.append(player)
                else:
                    self.admin_bye_players.append(player)
        else:
            self.admin_unpaired = sorted(unpaired, key=attrgetter('name_sort_key'))

    def _unpaired_holes(self, round_: int) -> list[dict[str, Any]]:
        """The round's unboarded table cells as ``{'index', 'label'}`` for the
        sidebar — a waiting player can be given a forfeit win on one. Thin
        wrapper over :meth:`Tournament.unboarded_holes`."""
        if self.admin_tournament is None:
            return []
        return [
            {'index': index, 'label': label}
            for index, label in self.admin_tournament.unboarded_holes(round_)
        ]

    def reload_unpaired_team_lists(self):
        """Populate the team-side equivalents of the player byes /
        unpaired lists.

        Manual byes (HPB / FPB / ZPB) sit in ``admin_team_bye`` and
        are rendered in the side column only — they're hidden from
        the main team-blocks table. Teams without any envelope for
        the round are *to-pair* and land in ``admin_team_unpaired``.
        PAB envelopes are engine-assigned and stay on the main table
        as bye blocks; they don't appear in either list."""
        self.admin_team_bye = []
        self.admin_team_unpaired = []
        self.admin_team_absent = []
        if not self.admin_tournament:
            return
        if not (
            self.admin_tournament.event.is_team_event
            and self.admin_tournament.pairing_system.paired_by_team
        ):
            return
        if not self.admin_tournament.pairing_system.show_unpaired_team_modal:
            # Fixed-schedule team systems (round-robin, two-game match) pair
            # every team from the schedule, present or not — there's no
            # absent / unpaired team to manage, so leave the lists empty and
            # let the Pair button generate directly (no absent-team prompt).
            return
        teams = [
            team
            for team in self.admin_tournament.event.sorted_teams
            if team.tournament_id == self.admin_tournament.id
        ]
        on_board_team_ids: set[int] = set()
        manual_bye_team_ids: set[int] = set()
        for team_board in self.admin_tournament.get_round_team_boards(self.admin_round):
            stb = team_board.stored_team_board
            if stb.team_b_id is None and stb.bye_type in TeamByeType.manual_bye_types():
                manual_bye_team_ids.add(stb.team_a_id)
                continue
            on_board_team_ids.add(stb.team_a_id)
            if stb.team_b_id is not None:
                on_board_team_ids.add(stb.team_b_id)
        teams_by_id = {team.id: team for team in teams}
        for team_id in manual_bye_team_ids:
            team = teams_by_id.get(team_id)
            if team is not None:
                self.admin_team_bye.append(team)
        for team in teams:
            if team.id in on_board_team_ids or team.id in manual_bye_team_ids:
                continue
            if team.check_in:
                self.admin_team_unpaired.append(team)
            else:
                self.admin_team_absent.append(team)

    @property
    def template_context(self) -> dict[str, Any]:
        allowed_actions = []
        existing_actions = []

        default_print_document = PairingPrintDocument.static_id()

        if self.admin_tournament:
            permission_handler = self.admin_tournament.pairing_system.permission_handler
            allowed_actions = permission_handler.allowed_actions(
                self.round_status, self.safety_mode
            )
            existing_actions = permission_handler.existing_actions(self.round_status)

            if (
                self.display_rankings
                or self.admin_round < self.admin_tournament.current_round
                or self.admin_tournament.is_round_finished(self.admin_round)
            ):
                default_print_document = PlayerRankingPrintDocument.static_id()

        tournament_ids = [tournament.id for tournament in self.allowed_tournaments]
        current_index = (
            tournament_ids.index(self.admin_tournament.id)
            if self.admin_tournament
            else 0
        )
        prev_tournament_id = (
            tournament_ids[current_index - 1] if current_index > 0 else None
        )
        next_tournament_id = (
            tournament_ids[current_index + 1]
            if current_index < len(tournament_ids) - 1
            else None
        )

        return super().template_context | {
            'admin_event_tab': 'admin-event-pairings-tab',
            'admin_tournament': self.admin_tournament,
            'admin_tournament_id': self.value_to_form_data(self.admin_tournament.id)
            if self.admin_tournament
            else None,
            'prev_tournament_id': prev_tournament_id,
            'next_tournament_id': next_tournament_id,
            'admin_round': self.admin_round,
            'admin_boards': self.admin_boards,
            'admin_boards_sortable': self.admin_boards_sortable,
            'admin_board_sort': self.admin_board_sort,
            'round_status': self.round_status,
            'display_rankings': self.display_rankings,
            'safety_mode': self.safety_mode,
            'allowed_actions': allowed_actions,
            'existing_actions': existing_actions,
            'tournament_options': self.get_tournament_options(self.allowed_tournaments),
            'admin_filtered_boards': self.admin_filtered_boards,
            'admin_team_boards': (
                [
                    tb
                    for tb in self.admin_tournament.get_round_team_boards(
                        self.admin_round
                    )
                    if not (
                        tb.stored_team_board.team_b_id is None
                        and tb.stored_team_board.bye_type
                        in TeamByeType.manual_bye_types()
                    )
                    # 'In play' hides the matches whose boards all have a
                    # result (the whole match, to keep board context).
                    and not (
                        SessionPairingsShowWithoutResults(self.request).get()
                        and tb.boards
                        and all(board.result != Result.NO_RESULT for board in tb.boards)
                    )
                ]
                if self.admin_tournament and not self.display_rankings
                else []
            ),
            'admin_unpaired': self.admin_unpaired,
            'admin_unpaired_holes': self.admin_unpaired_holes,
            'admin_bye_players': self.admin_bye_players,
            'admin_absent_players': self.admin_absent_players,
            'admin_team_bye': self.admin_team_bye,
            'admin_team_unpaired': self.admin_team_unpaired,
            'admin_team_absent': self.admin_team_absent,
            'pairings_generation_disabled_message': self.admin_tournament
            and not self.display_rankings
            and self.admin_tournament.pairings_generation_disabled_message(
                self.admin_round
            ),
            'show_without_results': SessionPairingsShowWithoutResults(
                self.request
            ).get(),
            'board': self.admin_board,
            'wtp': self.admin_board.optional_white_tournament_player
            if self.admin_board
            else None,
            'btp': self.admin_board.black_tournament_player
            if self.admin_board
            else None,
            'experimental_features_enabled': experimental_features_enabled(),
            'default_print_document': default_print_document,
        }

    def get_admin_tournament(self) -> Tournament:
        assert self.admin_tournament is not None
        return self.admin_tournament

    def get_admin_board(self) -> Board:
        assert self.admin_board is not None
        return self.admin_board

    def get_admin_player(self) -> TournamentPlayer:
        assert self.admin_player is not None
        return self.admin_player


class PairingsAdminController(BaseEventAdminController):
    guards = [
        EventGuard(),
        TournamentActionGuard(AuthAction.VIEW_PAIRINGS_TAB),
    ]

    @classmethod
    def _admin_event_pairings_render(
        cls,
        web_context: PairingsAdminWebContext,
        template_context: dict[str, Any] | None = None,
    ) -> Template:
        # Replace any board-only calculation before rendering the full table.
        if web_context.scoped_recompute and web_context.admin_tournament is not None:
            web_context.admin_tournament.set_for_round(web_context.admin_round)
            web_context.scoped_recompute = False
        return cls._admin_base_event_render(
            web_context.template_context | (template_context or {}),
        )

    @get(
        path=[
            '/event/{event_uniq_id:str}/pairings',
            '/event/{event_uniq_id:str}/pairings/{tournament_id:int}',
            '/event/{event_uniq_id:str}/pairings/{tournament_id:int}/{round:int}',
        ],
        name='admin-event-pairings-tab',
    )
    async def htmx_admin_pairings_tab(
        self,
        request: HTMXRequest,
        tournament_id: FromQuery[int | None],
        round: FromQuery[int | None],
        show_without_results: FromQuery[bool | None] = None,
        board_sort: FromQuery[str | None] = None,
        skip_ratings_warning: FromQuery[bool] = False,
    ) -> Template:
        if show_without_results is not None:
            SessionPairingsShowWithoutResults(request).set(show_without_results)
        if board_sort in ('board', 'natural'):
            SessionPairingsBoardSort(request).set(board_sort)
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        event = web_context.get_admin_event()
        if tournament := web_context.admin_tournament:
            SessionPairingsSelectedTournament(request, event).set(tournament.id)
            if admin_round := web_context.admin_round:
                SessionPairingsSelectedRound(request, tournament).set(admin_round)

        return self._admin_event_pairings_render(
            web_context, {'skip_ratings_warning': skip_ratings_warning}
        )

    @get(
        path='/event/{event_uniq_id:str}/pairing/{tournament_id:int}/{round:int}/{board_id:int}',
        name='admin-event-pairing-modal',
    )
    async def htmx_admin_pairings_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        board_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round, board_id)
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'pairing',
                'board': web_context.admin_board,
            },
        )

    @get(
        path='/event/{event_uniq_id:str}/team-pairing/{tournament_id:int}/{round:int}/{team_board_id:int}',
        name='admin-event-team-pairing-modal',
    )
    async def htmx_admin_team_pairings_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_board_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        team_board = tournament.team_boards_by_id.get(team_board_id)
        if team_board is None:
            raise NotFoundException(f'Team board {team_board_id} not found.')
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'team-pairing',
                'team_board': team_board,
            },
        )

    @staticmethod
    def _team_point_adjustment_context(
        tournament: 'Tournament', team: 'Team | None', round_: int
    ) -> dict[str, Any] | None:
        """Bonus/penalty data for one side of the match dialog: the
        team's current manual MP/GP/reason plus any rule-set-imposed
        adjustment and its explanation."""
        if team is None:
            return None
        manual_mp, manual_gp, reason = 0.0, 0.0, ''
        for adjustment in tournament.stored_tournament.stored_team_point_adjustments:
            if adjustment.team_id == team.id and adjustment.round_ == round_:
                manual_mp = adjustment.mp_delta
                manual_gp = adjustment.gp_delta
                reason = adjustment.reason or ''
                break
        rule_set_adjustment = tournament.rule_set_point_adjustment(team.id, round_)
        return {
            'team': team,
            'mp': manual_mp,
            'gp': manual_gp,
            'reason': reason,
            'rule_set_mp': rule_set_adjustment.mp if rule_set_adjustment else 0.0,
            'rule_set_gp': rule_set_adjustment.gp if rule_set_adjustment else 0.0,
            'rule_set_explanation': (
                rule_set_adjustment.explanation if rule_set_adjustment else ''
            ),
        }

    @staticmethod
    def _player_point_adjustment_context(
        tournament: 'Tournament', player: 'TournamentPlayer', round_: int
    ) -> dict[str, Any]:
        """The player's current manual delta and reason for the round.
        Individual tournaments have no match points and no rule-set
        contribution, so this is simpler than the team counterpart."""
        adjustment = tournament.stored_player_point_adjustment(player.id, round_)
        return {
            'player': player,
            'delta': adjustment.delta if adjustment else 0.0,
            'reason': (adjustment.reason if adjustment else '') or '',
        }

    @get(
        path='/player-point-adjustment/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{player_id:int}',
        name='admin-player-point-adjustment-modal',
    )
    async def htmx_admin_player_point_adjustment_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        player = tournament.tournament_players_by_id.get(player_id)
        if player is None:
            raise NotFoundException(f'Player {player_id} not found.')
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'player-point-adjustment',
                'pa_round': round,
                'pa_adjustment': self._player_point_adjustment_context(
                    tournament, player, round
                ),
            },
        )

    @patch(
        path='/player-point-adjustment/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{player_id:int}',
        name='admin-player-point-adjustment-set',
        guards=[TournamentActionGuard(AuthAction.UPDATE_RESULTS)],
        data=Body(media_type=RequestEncodingType.URL_ENCODED),
    )
    async def htmx_admin_player_point_adjustment_set(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        player = tournament.tournament_players_by_id.get(player_id)
        if player is None:
            raise NotFoundException(f'Player {player_id} not found.')
        event = web_context.get_admin_event()
        delta = WebContext.form_data_to_float(data, 'delta') or 0.0
        # Same TRF26 299 field limit as the team adjustments.
        if not MIN_POINT_ADJUSTMENT <= delta <= MAX_POINT_ADJUSTMENT:
            Message.error(
                request,
                _('Bonus / penalty points must be between {min} and {max}.').format(
                    min=f'{MIN_POINT_ADJUSTMENT:g}', max=f'{MAX_POINT_ADJUSTMENT:g}'
                ),
            )
            return self._admin_event_pairings_render(
                PairingsAdminWebContext(request, tournament_id, round)
            )
        reason = WebContext.form_data_to_str(data, 'reason') or None
        with EventDatabase(event.uniq_id, write=True) as database:
            tournament.set_manual_player_point_adjustment(
                player.id, round, delta, reason, database
            )
        Message.success(request, _('Bonus / penalty points updated.'))
        return self._admin_event_pairings_render(
            PairingsAdminWebContext(request, tournament_id, round, reload_event=True)
        )

    @get(
        path='/team-point-adjustment/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{team_id:int}',
        name='admin-team-point-adjustment-modal',
    )
    async def htmx_admin_team_point_adjustment_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        team = tournament.event.teams_by_id.get(team_id)
        if team is None or team.tournament_id != tournament.id:
            raise NotFoundException(f'Team {team_id} not found.')
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'team-point-adjustment',
                'pa_round': round,
                'pa_adjustment': self._team_point_adjustment_context(
                    tournament, team, round
                ),
            },
        )

    @patch(
        path='/team-point-adjustment/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{team_id:int}',
        name='admin-team-point-adjustment-set',
        guards=[TournamentActionGuard(AuthAction.UPDATE_RESULTS)],
        data=Body(media_type=RequestEncodingType.URL_ENCODED),
    )
    async def htmx_admin_team_point_adjustment_set(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        team = tournament.event.teams_by_id.get(team_id)
        if team is None or team.tournament_id != tournament.id:
            raise NotFoundException(f'Team {team_id} not found.')
        event = web_context.get_admin_event()
        mp_delta = WebContext.form_data_to_float(data, 'mp') or 0.0
        gp_delta = WebContext.form_data_to_float(data, 'gp') or 0.0
        # These travel in the TRF26 299 record, whose point fields are
        # ``[-]11.5`` — four columns, so a sign costs an integer digit.
        # A wider value would overflow the field and shift the rest of
        # the line, corrupting the file the pairing engine reads.
        if not all(
            MIN_POINT_ADJUSTMENT <= delta <= MAX_POINT_ADJUSTMENT
            for delta in (mp_delta, gp_delta)
        ):
            Message.error(
                request,
                _('Bonus / penalty points must be between {min} and {max}.').format(
                    min=f'{MIN_POINT_ADJUSTMENT:g}', max=f'{MAX_POINT_ADJUSTMENT:g}'
                ),
            )
            return self._admin_event_pairings_render(
                PairingsAdminWebContext(request, tournament_id, round)
            )
        reason = WebContext.form_data_to_str(data, 'reason') or None
        with EventDatabase(event.uniq_id, write=True) as database:
            tournament.set_manual_point_adjustment(
                team.id, round, mp_delta, gp_delta, reason, database
            )
        Message.success(request, _('Bonus / penalty points updated.'))
        web_context = PairingsAdminWebContext(
            request, tournament_id, round, reload_event=True
        )
        return self._admin_event_pairings_render(web_context)

    @delete(
        path='/team-pairing/unpair/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{team_board_id:int}',
        name='admin-pairings-unpair-team-board',
        guards=[TournamentActionGuard(AuthAction.UNPAIR_BOARD)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_unpair_team_board(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_board_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.MANUAL_UNPAIRING,
        )
        tournament = web_context.get_admin_tournament()
        team_board = tournament.team_boards_by_id.get(team_board_id)
        if team_board is None:
            raise NotFoundException(f'Team board {team_board_id} not found.')
        tournament.unpair_team_board(team_board)
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @get(
        path='/event/{event_uniq_id:str}/unpaired-modal/{tournament_id:int}/{round:int}/{player_id:int}',
        name='pairings-unpaired-player-modal',
    )
    async def htmx_pairings_unpaired_player_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request, tournament_id, round, player_id=player_id
        )
        tournament_player = web_context.get_admin_player()
        admin_tournament = web_context.get_admin_tournament()

        byes: int = 0
        for round_ in tournament_player.pairings:
            match tournament_player.pairings[round_].result:
                case Result.HALF_POINT_BYE:
                    byes += 1
                case Result.FULL_POINT_BYE:
                    byes += 2

        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'unpaired-player',
                'tournament_player': tournament_player,
                'exempt_tournament_player': next(
                    (
                        b.white_tournament_player
                        for b in web_context.admin_boards
                        if b.exempt
                    ),
                    None,
                ),
                'hpb_possible': byes < admin_tournament.max_byes,
            },
        )

    def _admin_update_result(
        self,
        request: HTMXRequest,
        tournament_id: int,
        round_: int,
        board_id: int,
        result: int,
        trigger_event: str | None = None,
        validate_result: bool = False,
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round_,
            board_id=board_id,
            action=None if validate_result else PairingAction.RESULT_UPDATE,
        )
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        board = web_context.get_admin_board()

        if board.exempt:
            return self._admin_event_pairings_render(web_context)

        target_board_id: int | None
        if result not in (Result.admin_imputable_results()):
            raise ClientException(f'Invalid result [{result}].')

        context = web_context.template_context

        if validate_result:
            if board.result != result:
                trigger_event = 'highlight_board_with_warning'
                context |= {'extra_row_class': 'highlight highlight-warning'}
                target_board_id = board_id
            else:
                target_board_id = self._next_board_id(
                    board_id, web_context.admin_filtered_boards
                )
        else:
            r = Result(result)
            if r.is_special_result:
                if message := plugin_manager.hook_for_event(
                    event, 'signal_special_result_set'
                )(tournament=tournament, result=r):
                    Message.warning(request, message)

            tournament.add_result(board, r)
            target_board_id = self._next_board_id(
                board_id, web_context.admin_filtered_boards
            )
            # Refetch the context to get the new default_print_document etc.
            context = web_context.template_context

        if not web_context.requires_refresh:
            return HTMXTemplate(
                template_name='/admin/pairings/pairing_row_and_controls.html',
                context=context
                | {
                    'messages': Message.messages(web_context.request),
                },
                re_target='#round-controls',
                re_swap='outerHTML',
                trigger_event=trigger_event,
                after='receive',
                params={'board_id': target_board_id},
            )

        return self._admin_event_pairings_render(web_context)

    @staticmethod
    def _next_board_id(board_id: int, boards: list[Board]) -> int | None:
        return next(
            (
                b.board_id
                for b in boards
                if b.board_id is not None and b.board_id > board_id
            ),
            None,
        )

    @put(
        path='/pairing/set-result/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{board_id:int}/{result:int}',
        name='admin-pairings-set-result',
        guards=[SetResultGuard()],
    )
    async def htmx_admin_set_result(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        board_id: FromPath[int],
        result: FromPath[int],
    ) -> Template:
        return self._admin_update_result(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
            result=result,
            trigger_event='close_modal',
        )

    @delete(
        path='/pairing/unpair/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{board_id:int}',
        name='admin-pairings-unpair-board',
        guards=[TournamentActionGuard(AuthAction.UNPAIR_BOARD)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_unpair(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        board_id: FromPath[int],
    ) -> Template:
        web_context: PairingsAdminWebContext = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
            action=PairingAction.MANUAL_UNPAIRING,
        )
        board = web_context.get_admin_board()
        tournament = web_context.get_admin_tournament()
        tournament.unpair_boards([board])

        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @patch(
        path='/pairing/permute/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{board_id:int}',
        name='admin-pairings-permute',
        guards=[TournamentActionGuard(AuthAction.PERMUTE_BOARD)],
    )
    async def htmx_admin_permute(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        board_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
            action=PairingAction.COLOR_PERMUTE,
        )
        board = web_context.get_admin_board()
        board.permute_colors()
        return self._admin_event_pairings_render(web_context)

    @put(
        path='/pairing/set-result-hotkey/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-pairings-set-result-hotkey',
        guards=[TournamentActionGuard(AuthAction.UPDATE_RESULTS)],
        data=Body(media_type=RequestEncodingType.URL_ENCODED),
    )
    async def htmx_admin_set_result_hotkey(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        board_id: int = int(data['board_id'])
        key: str = data['key']
        # Team rows use team_a/team_b order; stored results are white-relative.
        event = BaseEventAdminWebContext(request).get_admin_event()
        left_is_white = True
        if event.is_team_event:
            web_context = PairingsAdminWebContext(
                request, tournament_id=tournament_id, round_=round, board_id=board_id
            )
            tournament = web_context.get_admin_tournament()
            board = tournament.boards_by_id.get(board_id)
            team_board_id = (
                board.stored_board.team_board_id if board is not None else None
            )
            if board is not None and team_board_id is not None:
                team_board = tournament.team_boards_by_id.get(team_board_id)
                if team_board is not None:
                    team_a_id = team_board.stored_team_board.team_a_id
                    white_tp = board.optional_white_tournament_player
                    black_tp = board.black_tournament_player
                    if white_tp is not None:
                        left_is_white = white_tp.team_id == team_a_id
                    elif black_tp is not None:
                        left_is_white = black_tp.team_id != team_a_id
        result: Optional[Result] = None
        match key:
            case 'Digit0' | 'Numpad0':
                result = Result.NO_RESULT
            case 'Digit1' | 'Numpad1':
                result = Result.WIN if left_is_white else Result.LOSS
            case 'Digit2' | 'Numpad2':
                result = Result.LOSS if left_is_white else Result.WIN
            case 'Digit3' | 'Numpad3':
                result = Result.DRAW
            case _:
                return HTMXTemplate(
                    template_name='/common/empty.html',
                    re_swap='none',
                )
        assert result is not None
        return self._admin_update_result(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
            result=result,
            validate_result=data['validate_result'] == 'true',
        )

    @patch(
        path=(
            '/pairing/swap-board-player/{event_uniq_id:str}/{tournament_id:int}'
            '/{round:int}/{board_id:int}/{side:str}'
        ),
        name='admin-pairings-swap-board-player',
        guards=[TournamentActionGuard(AuthAction.UPDATE_RESULTS)],
        data=Body(media_type=RequestEncodingType.URL_ENCODED),
    )
    async def htmx_admin_swap_board_player(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        board_id: FromPath[int],
        side: FromPath[str],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        if side not in ('W', 'B'):
            raise ClientException(f'Invalid side [{side}].')
        this_side: str = 'white' if side == 'W' else 'black'
        try:
            new_player_id = int(data.get('new_player_id', '0') or '0')
        except ValueError:
            raise ClientException('Invalid new_player_id.')

        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            board_id=board_id,
        )
        event = web_context.get_admin_event()
        tournament = web_context.get_admin_tournament()
        this_board = web_context.get_admin_board()

        if not event.is_team_event:
            raise ClientException('Lineup swap only allowed in team events.')

        team_board_id = this_board.stored_board.team_board_id
        if team_board_id is None:
            raise ClientException('Board is not part of a team match.')
        team_board = tournament.team_boards_by_id[team_board_id]

        side_team = self._team_owning_side(
            tournament, team_board, this_board.index, side
        )
        if side_team is None:
            raise ClientException('Cannot determine team for this side at this slot.')

        old_player_id = (
            this_board.stored_board.white_player_id
            if this_side == 'white'
            else this_board.stored_board.black_player_id
        )

        # Punch a hole.
        if new_player_id == 0:
            if old_player_id is None:
                return self._admin_event_pairings_render(web_context)
            self._punch_lineup_hole_for_team(
                event, tournament, this_board, team_board, side_team, old_player_id
            )
            return self._admin_event_pairings_render(web_context)

        # Fill a hole.
        if old_player_id is None:
            new_tp = tournament.tournament_players_by_id.get(new_player_id)
            if new_tp is None or new_tp.team_id != side_team.id:
                raise ClientException('Picked player is not in this team.')
            self._fill_lineup_hole(
                event,
                tournament,
                this_board,
                team_board,
                side_team,
                this_side,
                new_tp,
            )
            return self._admin_event_pairings_render(web_context)

        new_player = event.players_by_id.get(new_player_id)
        if new_player is None or new_player.team_id != side_team.id:
            raise ClientException('New player is not in this team.')

        if old_player_id == new_player_id:
            return self._admin_event_pairings_render(web_context)

        # Locate the new player on another board of this team match
        # (they're already in the lineup; the dropdown's "Bench"
        # branch is what the hole-fill path handles).
        other_board: Board | None = None
        for board in team_board.boards:
            if board.identifier == this_board.identifier:
                continue
            if (
                board.stored_board.white_player_id == new_player_id
                or board.stored_board.black_player_id == new_player_id
            ):
                other_board = board
                break
        if other_board is None:
            raise ClientException('New player is not currently in this team match.')

        new_player_tp = tournament.tournament_players_by_id[new_player_id]
        # Vacate both slots, then drop the new player into the chosen
        # one. The displaced (old) player leaves the round lineup
        # entirely; the source slot becomes a hole.
        self._punch_lineup_hole_for_team(
            event, tournament, this_board, team_board, side_team, old_player_id
        )
        self._punch_lineup_hole_for_team(
            event, tournament, other_board, team_board, side_team, new_player_id
        )
        self._fill_lineup_hole(
            event,
            tournament,
            this_board,
            team_board,
            side_team,
            this_side,
            new_player_tp,
        )
        return self._admin_event_pairings_render(web_context)

    @staticmethod
    def _team_owning_side(
        tournament: Tournament,
        team_board: TeamBoard,
        board_index: int,
        side: str,
    ) -> Team | None:
        """Which team owns physical side ``side`` ('W' / 'B') on the
        board at ``board_index`` of ``team_board``, as the pairing
        system seats the match."""
        return tournament.pairing_variation.engine.team_seat_owner(
            tournament,
            team_board,
            board_index,
            'white' if side == 'W' else 'black',
        )

    @staticmethod
    def _team_lineup_slot(
        tournament: Tournament,
        team_board: TeamBoard,
        side_team: Team,
        board_index: int,
    ) -> int:
        """The line-up slot ``side_team`` fills by seating a player on
        the board at ``board_index``."""
        return tournament.pairing_variation.engine.team_board_slots(
            tournament, team_board, side_team.id
        ).get(board_index, board_index)

    @staticmethod
    def _punch_lineup_hole_for_team(
        event: Event,
        tournament: Tournament,
        this_board: Board,
        team_board: TeamBoard,
        side_team: Team,
        side_player_id: int,
    ) -> None:
        """Remove ``side_team``'s player from this board's slot.
        Leaves an index gap in the team's lineup. The physical side
        the player was on becomes ``NULL`` on the board (no flip).
        Both sides empty ⇒ delete the board."""
        round_ = this_board.round
        slot = PairingsAdminController._team_lineup_slot(
            tournament, team_board, side_team, this_board.index
        )
        w_id = this_board.stored_board.white_player_id
        physical_side: str = 'white' if side_player_id == w_id else 'black'
        side_tp = tournament.tournament_players_by_id[side_player_id]
        with EventDatabase(event.uniq_id, write=True) as database:
            lineup_slots: list[int | None] = [
                p.id if p is not None else None
                for p in side_team.effective_round_slots(round_)
            ]
            if 0 <= slot < len(lineup_slots):
                lineup_slots[slot] = None
            side_team.set_round_lineup(round_, lineup_slots, database)
            side_pairing = side_tp.pairings_by_round[round_]
            # Update (don't delete) the pairing: the
            # ``delete_board_on_pairing_delete`` trigger would
            # otherwise nuke this slot's board (cascading to the
            # opponent's pairing too). Clearing ``board_id`` first
            # lets the player look "unpaired" without losing the slot.
            side_pairing.stored_pairing.result = Result.NO_RESULT.value
            side_pairing.stored_pairing.board_id = None
            side_pairing.stored_pairing.effective_points = None
            side_pairing.stored_pairing.illegal_moves = 0
            side_pairing.update(database)
            if physical_side == 'white':
                this_board.white_player_id = None
            else:
                this_board.black_player_id = None
            # Keep the board even when both sides become empty so the
            # slot remains visible in the team block and can be
            # re-filled from either team.
            database.update_stored_board(this_board.stored_board)
            opp_id = (
                this_board.stored_board.black_player_id
                if physical_side == 'white'
                else this_board.stored_board.white_player_id
            )
            if opp_id is not None:
                opp_tp = tournament.tournament_players_by_id[opp_id]
                opp_pairing = opp_tp.pairings_by_round[round_]
                # Opposing player now has no opponent → forfeit win,
                # mirroring the lineup-hole branch in ``create_boards``.
                opp_pairing.stored_pairing.result = Result.FORFEIT_WIN.value
                opp_pairing.stored_pairing.effective_points = None
                opp_pairing.stored_pairing.illegal_moves = 0
                opp_pairing.update(database)
            this_board.set_last_result_update(Result.NO_RESULT, database)

    @staticmethod
    def _fill_lineup_hole(
        event: Event,
        tournament: Tournament,
        this_board: Board,
        team_board: TeamBoard,
        side_team: Team,
        physical_side: str,
        new_player_tp: 'TournamentPlayer',
    ) -> None:
        """Put ``new_player_tp`` on the ``physical_side`` of
        ``this_board`` (its current value must be ``NULL`` — a hole)
        and add the player to ``side_team``'s round lineup at this
        slot. No swap, no reshape: the chip-colour matches the
        physical side everywhere."""
        round_ = this_board.round
        slot = PairingsAdminController._team_lineup_slot(
            tournament, team_board, side_team, this_board.index
        )
        with EventDatabase(event.uniq_id, write=True) as database:
            lineup_slots: list[int | None] = [
                p.id if p is not None else None
                for p in side_team.effective_round_slots(round_)
            ]
            if 0 <= slot < len(lineup_slots):
                lineup_slots[slot] = new_player_tp.id
            side_team.set_round_lineup(round_, lineup_slots, database)
            this_board.replace_player(
                new_player_tp,
                physical_side,  # type: ignore[arg-type]
            )
            database.update_stored_board(this_board.stored_board)
            new_pairing = new_player_tp.pairings_by_round[round_]
            new_pairing.stored_pairing.result = Result.NO_RESULT.value
            new_pairing.stored_pairing.board_id = this_board.identifier
            new_pairing.stored_pairing.effective_points = None
            new_pairing.stored_pairing.illegal_moves = 0
            new_pairing.update(database)
            opp_id = (
                this_board.stored_board.black_player_id
                if physical_side == 'white'
                else this_board.stored_board.white_player_id
            )
            if opp_id is not None:
                opp_tp = tournament.tournament_players_by_id[opp_id]
                opp_pairing = opp_tp.pairings_by_round[round_]
                opp_pairing.stored_pairing.result = Result.NO_RESULT.value
                opp_pairing.stored_pairing.effective_points = None
                opp_pairing.stored_pairing.illegal_moves = 0
                opp_pairing.update(database)
            this_board.set_last_result_update(Result.NO_RESULT, database)

    @patch(
        path=(
            '/pairings-player-check-in-out/{event_uniq_id:str}/{tournament_id:int}'
            '/{round:int}/{player_id:int}'
        ),
        name='pairings-player-check-in-out',
        guards=[TournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_pairings_player_check_in_out(
        self,
        request: HTMXRequest,
        channels: NamedDependency[ChannelsPlugin],
        tournament_id: FromPath[int],
        player_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            player_id=player_id,
            round_=round,
        )
        player = web_context.get_admin_player()
        tournament = player.single_tournament
        tournament.check_in_player(player, not player.check_in)
        PlayerAdminController.publish_new_checkin(channels, tournament)
        message = _('Player [{player}] marked as "{status}".').format(
            player=player.full_name,
            status=_('Present') if player.check_in else _('Absent'),
        )
        Message.success(request, message)
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings-player-return-to-tournament/{event_uniq_id:str}/{tournament_id:int}'
            '/{round:int}/{player_id:int}'
        ),
        name='pairings-player-return-to-tournament',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_pairings_player_return_to_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        player_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            player_id=player_id,
            round_=round,
        )
        player = web_context.get_admin_player()
        tournament = player.single_tournament
        tournament.set_player_participation(player)
        message = _('Player [{player}] has returned to the tournament.').format(
            player=player.full_name
        )
        Message.success(request, message)
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/set-player-zpb/{event_uniq_id:str}/'
            '{tournament_id:int}/{player_id:int}/{round:int}'
        ),
        name='pairings-set-player-zpb',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_set_player_zpb(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            player_id=player_id,
            action=PairingAction.BYE_UPDATE,
        )
        tournament = web_context.get_admin_tournament()
        player = web_context.get_admin_player()
        tournament.set_player_byes(player, {round: Result.ZERO_POINT_BYE})
        message = _('Zero-Point Bye attributed to player [{player}].').format(
            player=player.full_name
        )
        Message.success(request, message)
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/set-player-hpb/{event_uniq_id:str}/'
            '{tournament_id:int}/{player_id:int}/{round:int}'
        ),
        name='pairings-set-player-hpb',
        guards=[TournamentActionGuard(AuthAction.SET_HPB)],
    )
    async def htmx_set_player_hpb(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            player_id=player_id,
            action=PairingAction.BYE_UPDATE,
        )
        tournament = web_context.get_admin_tournament()
        player = web_context.get_admin_player()
        byes: int = 0
        for pairing in player.pairings.values():
            match pairing.result:
                case Result.HALF_POINT_BYE:
                    byes += 1
                case Result.FULL_POINT_BYE:
                    byes += 2
        if byes >= tournament.max_byes:
            Message.error(
                request,
                _('Too many byes for player [{player_name}].').format(
                    player_name=player.full_name
                ),
            )
            return self._admin_event_pairings_render(web_context)
        message = _('Half-Point Bye attributed to player [{player}].').format(
            player=player.full_name
        )
        tournament.set_player_byes(player, {round: Result.HALF_POINT_BYE})
        Message.success(request, message)
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/cancel-player-bye/{event_uniq_id:str}/'
            '{tournament_id:int}/{player_id:int}/{round:int}'
        ),
        name='pairings-cancel-player-bye',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_cancel_bye(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            player_id=player_id,
            action=PairingAction.BYE_UPDATE,
        )
        tournament = web_context.get_admin_tournament()
        player = web_context.get_admin_player()
        tournament.set_player_byes(player, {round: Result.NO_RESULT})
        message = _('Player [{player}] has returned for this round.').format(
            player=player.full_name
        )
        Message.success(request, message)
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    @get(
        path='/event/{event_uniq_id:str}/unpaired-team-modal/{tournament_id:int}/{round:int}/{team_id:int}',
        name='pairings-unpaired-team-modal',
    )
    async def htmx_pairings_unpaired_team_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        admin_tournament = web_context.get_admin_tournament()
        if not admin_tournament.pairing_system.show_unpaired_team_modal:
            raise NotFoundException(
                'Team status is not editable for this pairing system.'
            )
        team = admin_tournament.event.teams_by_id.get(team_id)
        if team is None:
            raise NotFoundException(f'Team {team_id} not found.')
        exempt_team_board = next(
            (
                tb
                for tb in admin_tournament.get_round_team_boards(round)
                if tb.stored_team_board.team_b_id is None
                and tb.stored_team_board.bye_type not in TeamByeType.manual_bye_types()
            ),
            None,
        )
        exempt_team = (
            exempt_team_board.team_a
            if exempt_team_board is not None
            and exempt_team_board.stored_team_board.team_a_id != team_id
            else None
        )
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'unpaired-team',
                'admin_team': team,
                'admin_team_bye_type': team.round_bye_type(round),
                'exempt_team': exempt_team,
            },
        )

    def _set_team_bye(
        self,
        request: HTMXRequest,
        tournament_id: int,
        round: int,
        team_id: int,
        bye_type: str | None,
        success_message: str,
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.BYE_UPDATE,
        )
        admin_tournament = web_context.get_admin_tournament()
        if not admin_tournament.pairing_system.show_unpaired_team_modal:
            raise NotFoundException(
                'Team byes are not available for this pairing system.'
            )
        team = admin_tournament.event.teams_by_id.get(team_id)
        if team is None:
            raise NotFoundException(f'Team {team_id} not found.')
        with EventDatabase(admin_tournament.event.uniq_id, write=True) as db:
            team.set_round_bye(round, bye_type, db)
        Message.success(request, success_message.format(team=team.name))
        web_context.reload_unpaired_team_lists()
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/set-team-zpb/{event_uniq_id:str}/'
            '{tournament_id:int}/{team_id:int}/{round:int}'
        ),
        name='pairings-set-team-zpb',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_set_team_zpb(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        return self._set_team_bye(
            request,
            tournament_id,
            round,
            team_id,
            TeamByeType.ZPB,
            _('Zero-Point Bye attributed to team [{team}].'),
        )

    @patch(
        path=(
            '/pairings/set-team-hpb/{event_uniq_id:str}/'
            '{tournament_id:int}/{team_id:int}/{round:int}'
        ),
        name='pairings-set-team-hpb',
        guards=[TournamentActionGuard(AuthAction.SET_HPB)],
    )
    async def htmx_set_team_hpb(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        return self._set_team_bye(
            request,
            tournament_id,
            round,
            team_id,
            TeamByeType.HPB,
            _('Half-Point Bye attributed to team [{team}].'),
        )

    @patch(
        path=(
            '/pairings/set-team-fpb/{event_uniq_id:str}/'
            '{tournament_id:int}/{team_id:int}/{round:int}'
        ),
        name='pairings-set-team-fpb',
        guards=[TournamentActionGuard(AuthAction.SET_HPB)],
    )
    async def htmx_set_team_fpb(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        return self._set_team_bye(
            request,
            tournament_id,
            round,
            team_id,
            TeamByeType.FPB,
            _('Full-Point Bye attributed to team [{team}].'),
        )

    @patch(
        path=(
            '/pairings/cancel-team-bye/{event_uniq_id:str}/'
            '{tournament_id:int}/{team_id:int}/{round:int}'
        ),
        name='pairings-cancel-team-bye',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_cancel_team_bye(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        return self._set_team_bye(
            request,
            tournament_id,
            round,
            team_id,
            None,
            _('Team [{team}] has returned for this round.'),
        )

    @patch(
        path=(
            '/pairings/pair-team/{event_uniq_id:str}/'
            '{tournament_id:int}/{team_id:int}/{round:int}'
        ),
        name='admin-pairings-pair-team',
        guards=[TournamentActionGuard(AuthAction.MANUALLY_PAIR_PLAYERS)],
    )
    async def htmx_admin_pair_team(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.MANUAL_PAIRING,
        )
        pairing_round = web_context.admin_round or 1
        tournament = web_context.get_admin_tournament()
        team = tournament.event.teams_by_id.get(team_id)
        if team is None:
            raise NotFoundException(f'Team {team_id} not found.')
        exempt_team_board = next(
            (
                tb
                for tb in tournament.get_round_team_boards(pairing_round)
                if tb.stored_team_board.team_b_id is None
                and tb.stored_team_board.bye_type not in TeamByeType.manual_bye_types()
            ),
            None,
        )
        exempt_team = (
            exempt_team_board.team_a
            if exempt_team_board is not None
            and exempt_team_board.stored_team_board.team_a_id != team.id
            else None
        )
        tb = tournament.create_team_round_pairing(pairing_round, team.id)
        if exempt_team is not None:
            message = _(
                'Team [{team}] has been paired against [{opponent}] at board #{board}.'
            ).format(
                team=team.name,
                opponent=exempt_team.name,
                board=tb.display_number,
            )
        else:
            message = _('Pairing-Allocated Bye assigned to team [{team}].').format(
                team=team.name
            )
        Message.success(request, message)
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/pair-player/{event_uniq_id:str}/'
            '{tournament_id:int}/{player_id:int}/{round:int}'
        ),
        name='admin-pairings-pair-player',
        guards=[TournamentActionGuard(AuthAction.MANUALLY_PAIR_PLAYERS)],
    )
    async def htmx_admin_pair_player(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            player_id=player_id,
            action=PairingAction.MANUAL_PAIRING,
        )
        pairing_round = web_context.admin_round or 1
        tournament = web_context.get_admin_tournament()
        tournament_player = web_context.get_admin_player()
        # The waiting opponent is the player on the awaiting bye board, not a
        # settled forfeit hole (also black-less) — matching create_round_pairing.
        pab_board = tournament.get_round_pab_board(pairing_round)
        exempt_tournament_player = (
            pab_board.optional_white_tournament_player if pab_board else None
        )
        if exempt_tournament_player is not None:
            board = tournament.create_round_pairing(
                pairing_round,
                exempt_tournament_player.id,
                tournament_player.id,
            )
            message = _(
                'Player [{player}] has been paired against '
                '[{opponent}] at board #{board}.'
            ).format(
                player=tournament_player.full_name,
                opponent=exempt_tournament_player.full_name,
                board=board.number,
            )
        else:
            tournament.create_round_pairing(
                pairing_round,
                tournament_player.id,
                None,
            )
            message = _('Pairing-Allocated Bye assigned to player [{player}].').format(
                player=tournament_player.full_name
            )
        Message.success(request, message)
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            player_id=tournament_player.id,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @patch(
        path=(
            '/pairings/pair-flat/{event_uniq_id:str}/'
            '{tournament_id:int}/{first:str}/{second:str}/{round:int}'
        ),
        name='admin-pairings-pair-flat',
        guards=[TournamentActionGuard(AuthAction.MANUALLY_PAIR_PLAYERS)],
    )
    async def htmx_admin_pair_flat(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        first: FromPath[str],
        second: FromPath[str],
    ) -> Template:
        """Flat (Molter) manual pairing from the sidebar's select-then-pick
        flow. ``first``/``second`` are tokens: ``p<id>`` for a player,
        ``h<index>`` for an empty table cell (hole). The first selection is
        white, the second black; one player + a hole ⇒ forfeit win."""
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.MANUAL_PAIRING,
        )
        pairing_round = web_context.admin_round or 1
        tournament = web_context.get_admin_tournament()

        def _parse(token: str) -> tuple[str, int]:
            return token[0], int(token[1:])

        try:
            (kind1, value1), (kind2, value2) = _parse(first), _parse(second)
            if kind1 == 'h' and kind2 == 'h':
                raise SharlyChessException(
                    _('Pick at least one player — two empty tables cannot pair.')
                )
            white_id = value1 if kind1 == 'p' else None
            black_id = value2 if kind2 == 'p' else None
            if kind1 == 'h':
                index = value1
            elif kind2 == 'h':
                index = value2
            else:
                index = tournament.first_unused_board_index(pairing_round)
            tournament.create_flat_manual_board(
                pairing_round, white_id, black_id, index
            )
            Message.success(request, _('Pairing added.'))
        except (SharlyChessException, ValueError, KeyError, IndexError) as error:
            Message.error(request, str(error) or _('Could not add the pairing.'))
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/set-all-present/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-set-all-present',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_pairings_set_all_present(
        self,
        channels: NamedDependency[ChannelsPlugin],
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )
        tournament = web_context.get_admin_tournament()
        tournament.check_in_all_players(True)
        PlayerAdminController.publish_new_checkin(channels, tournament)
        Message.success(request, _('All players marked as "Present".'))
        web_context.reload_unpaired_player_lists()
        return self._admin_event_pairings_render(web_context)

    def _generate_round_pairings(
        self, web_context: PairingsAdminWebContext
    ) -> Template:
        tournament = web_context.get_admin_tournament()
        round_ = web_context.admin_round
        request = web_context.request
        if error := tournament.generate_round_pairings(round_):
            Message.error(request, error)
        else:
            Message.success(request, _('Pairings successfully generated.'))
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament.id,
            round_=round_,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/generate/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='generate-round-pairings',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_generate_round_pairings(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.FULL_PAIRING,
        )
        tournament = web_context.get_admin_tournament()
        tournament.set_valid_pairing_settings()
        return self._generate_round_pairings(web_context)

    @post(
        path='/pairings/generate-partial/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='generate-round-partial-pairings',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_generate_round_partial_pairings(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.PARTIAL_PAIRING,
        )
        tournament = web_context.get_admin_tournament()
        tournament.set_valid_pairing_settings()
        round_ = web_context.admin_round
        if error := tournament.pairing_variation.engine.generate_pairings(
            tournament, round_, True
        ):
            Message.error(request, error)
        else:
            unpaired_count = sum(
                player.pairings[round_].needs_pairing
                for player in tournament.tournament_players
            )
            if unpaired_count:
                if unpaired_count == 1:
                    reason = (
                        _('PAB is already assigned')
                        if tournament.round_has_pab(round_)
                        else _('player already received a PAB in a previous round')
                    )
                else:
                    reason = _('some already played each other')
                Message.warning(
                    request,
                    ' '.join(
                        [
                            _('Complementary pairings generated.'),
                            ngettext(
                                '{players} player remain unpaired',
                                '{players} players remain unpaired',
                                unpaired_count,
                            ).format(players=unpaired_count),
                            f'({reason}).',
                        ]
                    ),
                )
            else:
                Message.success(
                    request,
                    _('Complementary pairings successfully generated!'),
                )

        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/generate/{event_uniq_id:str}/{tournament_id:int}',
        name='generate-tournament-pairings',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_generate_tournament_pairings(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.get_admin_tournament()

        if errors := tournament.get_pairing_settings_data_errors(data):
            return self._render_pairings_settings_modal(web_context, data, errors)

        self._save_pairing_settings_data(tournament, data)
        error: str = ''
        for round_ in range(1, tournament.rounds + 1):
            if error := tournament.pairing_variation.engine.generate_pairings(
                tournament, round_
            ):
                break
        if error:
            Message.error(request, error)
        else:
            tournament.set_current_round(1)
            Message.success(
                request,
                _(
                    'Pairings generated for all rounds of tournament [{tournament}].'
                ).format(tournament=tournament.name),
            )

        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, reload_event=True
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/unpair/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-pairings-unpair-round',
        guards=[TournamentActionGuard(AuthAction.UNPAIR_ROUND)],
    )
    async def admin_pairings_unpair(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            action=PairingAction.FULL_UNPAIRING,
        )
        tournament = web_context.get_admin_tournament()
        tournament.unpair_boards(web_context.admin_boards)
        # A fully-unpaired round loses its prohibited-pairing snapshot;
        # re-pairing writes a fresh one.
        with EventDatabase(tournament.event.uniq_id, True) as database:
            tournament.delete_prohibited_pairing_snapshot(round, database)

        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            reload_event=True,
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/unpair-tournament/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-pairings-unpair-tournament',
        guards=[TournamentActionGuard(AuthAction.UNPAIR_ROUND)],
    )
    async def admin_pairings_unpair_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.get_admin_tournament()
        tournament.unpair_boards(list(tournament.boards_by_id.values()))
        tournament.set_current_round(0)

        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, reload_event=True
        )
        return self._admin_event_pairings_render(web_context)

    @get(
        path=(
            '/pairings/safety-mode-modal/{event_uniq_id:str}/{tournament_id:int}'
            '/{round:int}/{action:str}/{redirect_method:str}/{redirect_route:path}'
        ),
        name='admin-pairings-safety-mode-modal',
    )
    async def admin_pairings_safety_mode_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        action: FromPath[str],
        redirect_method: FromPath[str],
        redirect_route: FromPath[str],
    ) -> Template:
        try:
            protected_action = PairingAction(action)
        except ValueError:
            raise NotFoundException(f'Unknown pairing action [{action}]')
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        permission_handler = tournament.pairing_system.permission_handler
        if protected_action not in permission_handler.existing_actions(
            web_context.round_status
        ):
            # The action is impossible at this round status (e.g. a stale
            # page after the round changed) — report rather than crash.
            Message.error(
                request,
                _('This action is not possible for this round.'),
            )
            return self._admin_event_pairings_render(web_context)
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'safety-mode',
                'action': protected_action,
                'required_mode': permission_handler.required_mode(
                    web_context.round_status, protected_action
                ),
                'redirect_method': redirect_method,
                'redirect_route': redirect_route,
            },
        )

    @post(
        path=[
            '/pairings/update-safety-mode/'
            '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
            '/pairings/update-safety-mode/{event_uniq_id:str}'
            '/{tournament_id:int}/{round:int}/{mode:str}',
        ],
        name='admin-pairings-update-safety-mode',
    )
    async def admin_pairings_update_safety_mode(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        mode = WebContext.form_data_to_str(data, 'mode') or ''
        try:
            SessionPairingsSafetyMode(request).set(SafetyMode(mode))
        except ValueError:
            raise NotFoundException(f'Unknown safety mode [{mode}]')
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        return self._admin_event_pairings_render(web_context)

    @get(
        path='/pairings/unfinished-round-modal/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-pairings-unfinished-round-modal',
    )
    async def admin_pairings_unfinished_round_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )

        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'unfinished-round',
                'unpaired_count': len(web_context.admin_unpaired),
                'hole_count': len(web_context.admin_unpaired_holes),
                'absent_count': len(web_context.admin_absent_players),
                'no_result_board_count': len(
                    [
                        board
                        for board in web_context.admin_boards
                        if board.result == Result.NO_RESULT
                        # A board with a hole on either side is a forfeit,
                        # not a pending result.
                        and board.stored_board.white_player_id is not None
                        and board.stored_board.black_player_id is not None
                    ]
                ),
            },
        )

    @get(
        path='/pairings/set-current-round-modal/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-pairings-set-current-round-modal',
    )
    async def admin_pairings_set_current_round_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )

        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'set-current-round',
                'no_result_board_count': len(
                    [
                        board
                        for board in web_context.admin_boards
                        if board.result == Result.NO_RESULT
                        # A board with a hole on either side is a forfeit,
                        # not a pending result.
                        and board.stored_board.white_player_id is not None
                        and board.stored_board.black_player_id is not None
                    ]
                ),
            },
        )

    @get(
        path='/pairings/ratings-warning-modal/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-ratings-warning-modal',
    )
    async def htmx_pairings_ratings_warning_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)

        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'pairing-ratings-warning',
                'data_sources': DataSourceManager().objects(),
            },
        )

    @get(
        path='/pairings/absents-modal/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-absents-modal',
    )
    async def htmx_pairings_absents_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request, tournament_id, round, load_check_in_data=True
        )
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'pairing-absents',
            },
        )

    @get(
        path='/pairings/team-absents-modal/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-team-absents-modal',
    )
    async def htmx_pairings_team_absents_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'pairing-team-absents',
            },
        )

    @patch(
        path='/pairings/team-toggle-check-in/{event_uniq_id:str}/{tournament_id:int}/{round:int}/{team_id:int}',
        name='pairings-team-toggle-check-in',
        guards=[TournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_pairings_team_toggle_check_in(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        team_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        team = tournament.event.teams_by_id.get(team_id)
        if team is None:
            raise NotFoundException(f'Team {team_id} not found.')
        tournament.check_in_team(team, not team.check_in)
        web_context = PairingsAdminWebContext(
            request, tournament_id, round, reload_event=True
        )
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/set-all-teams-present/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-set-all-teams-present',
        guards=[TournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_pairings_set_all_teams_present(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        tournament.check_in_all_teams(True)
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/pairings/validate-team-absents/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-validate-team-absents',
        guards=[TournamentActionGuard(AuthAction.CHECK_IN_PLAYERS)],
    )
    async def htmx_pairings_validate_team_absents(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, round_=round
        )
        tournament = web_context.get_admin_tournament()
        for team in list(web_context.admin_team_absent):
            if data.get(f'team_{team.id}') == 'present':
                tournament.check_in_team(team, True)
        if round == 1 and tournament.pairing_variation.settings:
            return self._render_pairings_settings_modal(web_context)
        return self._generate_round_pairings(web_context)

    @classmethod
    def _render_pairings_settings_modal(
        cls,
        web_context: PairingsAdminWebContext,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
        for_pairing: bool = True,
    ) -> Template:
        """The pairing settings, either as the last step before pairing
        (*for_pairing*, the modal that opens on the first pairing) or on
        their own, so they can be prepared ahead of time.

        Prepared on their own they are read-only once anything has been
        paired: the settings are baked into the pairings already made,
        so changing them then would describe a tournament that was never
        played.
        """
        tournament = web_context.get_admin_tournament()
        if data is None:
            data = {}
            for setting in tournament.pairing_variation.settings:
                data |= setting.get_form_data(tournament)
            errors = tournament.get_pairing_settings_data_errors(data)

        template_context = {
            'modal': 'pairing-settings',
            'pairing_settings': tournament.pairing_variation.settings,
            'r1_present_pairing_numbers': [
                player.pairing_number
                for player in tournament.players
                if player.pairings_by_round[1].needs_pairing
            ],
            'data': data,
            'errors': errors or {},
            'settings_for_pairing': for_pairing,
            'settings_read_only': (
                not for_pairing
                and tournament.has_pairings
                and tournament.pairing_system.lock_settings_after_first_pairing
            ),
        }
        return cls._admin_event_pairings_render(web_context, template_context)

    @get(
        path='/pairings/settings-modal/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-settings-modal',
    )
    async def htmx_pairings_settings_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        configure: FromQuery[bool] = False,
    ) -> Template:
        """*configure* opens the settings on their own, to be prepared
        before the first pairing; without it this is the step the pairing
        flow goes through."""
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        return self._render_pairings_settings_modal(
            web_context, for_pairing=not configure
        )

    @post(
        path='/pairings/settings-save/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-settings-save',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_pairings_settings_save(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template | ClientRefresh:
        """Store the settings without pairing, so they can be prepared
        ahead of the first round."""
        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, round_=round
        )
        tournament = web_context.get_admin_tournament()
        if errors := tournament.get_pairing_settings_data_errors(data):
            return self._render_pairings_settings_modal(
                web_context, data, errors, for_pairing=False
            )
        self._save_pairing_settings_data(tournament, data)
        if tournament.has_pairings:
            # Once rounds are paired the settings feed the standings (a
            # Keizer re-derives every score from them), so a full refresh
            # is needed for the new figures to reach every view, not just
            # the pairings tab.
            return ClientRefresh()
        return self._admin_event_pairings_render(web_context, {})

    @post(
        path='/pairings/generate-with-settings/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='generate-round-pairings-with-settings',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_generate_round_pairings_with_settings(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )
        tournament = web_context.get_admin_tournament()
        if errors := tournament.get_pairing_settings_data_errors(data):
            return self._render_pairings_settings_modal(web_context, data, errors)

        self._save_pairing_settings_data(tournament, data)
        return self._generate_round_pairings(web_context)

    @post(
        path='/pairings/settings-action/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-settings-action',
    )
    async def htmx_pairings_settings_action(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        """Re-render the pairing settings after one of their own buttons
        has been pressed. The settings decide what the action does; the
        values are only rendered back, never saved."""
        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, round_=round
        )
        tournament = web_context.get_admin_tournament()
        for setting in tournament.pairing_variation.settings:
            data = setting.apply_action(tournament, data)
        return self._render_pairings_settings_modal(
            web_context, data, tournament.get_pairing_settings_data_errors(data)
        )

    @staticmethod
    def _save_pairing_settings_data(tournament: Tournament, data: dict[str, str]):
        stored_settings: dict[str, Any] = {}
        for setting in tournament.pairing_variation.settings:
            stored_settings[setting.id] = setting.to_stored_value(
                setting.from_form_data(data)
            )
        tournament.update_pairing_settings(stored_settings)

    @post(
        path='/pairings/validate-absents/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='pairings-validate-absents',
        guards=[TournamentActionGuard(AuthAction.SET_ZPB)],
    )
    async def htmx_pairings_validate_absents(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
            load_check_in_data=True,
        )
        tournament = web_context.get_admin_tournament()
        absent_players = web_context.admin_absent_players
        if len(absent_players) > tournament.player_count / 2:
            set_present = 'over_50_present' in data
            for player in absent_players:
                if set_present:
                    tournament.check_in_player(player, check_in=True)
                else:
                    tournament.set_player_byes(player, {round: Result.ZERO_POINT_BYE})
        else:
            for player in absent_players:
                match data.get(f'player_{player.id}'):
                    case 'zpb':
                        tournament.set_player_byes(
                            player, {round: Result.ZERO_POINT_BYE}
                        )
                    case 'withdraw':
                        tournament.set_player_participation(player, withdraw=True)
                    case 'present':
                        tournament.check_in_player(player, check_in=True)
        if round == 1 and tournament.pairing_variation.settings:
            return self._render_pairings_settings_modal(web_context)
        return self._generate_round_pairings(web_context)

    @put(
        path='/tournament/set-current-round/{event_uniq_id:str}/{tournament_id:int}/{current_round:int}',
        name='admin-tournament-set-current-round',
        guards=[TournamentActionGuard(AuthAction.SET_CURRENT_ROUND)],
    )
    async def htmx_admin_tournament_set_current_round(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        current_round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=current_round,
        )
        tournament = web_context.get_admin_tournament()
        tournament.set_current_round(round_=current_round)
        SessionPairingsSelectedRound(request, tournament).set(current_round)
        return self._admin_event_pairings_render(web_context)

    # -------------------------------------------------------------------------
    # Prohibited pairings
    # -------------------------------------------------------------------------

    @classmethod
    def _render_prohibited_pairings_modal(
        cls,
        web_context: PairingsAdminWebContext,
        show_manual_form: bool = False,
        manual_form_index: int | None = None,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> Template:
        tournament = web_context.get_admin_tournament()
        round_ = web_context.admin_round
        is_team = tournament.is_team_tournament
        locked = tournament.round_has_pairings(round_)

        members: list[Any]
        if is_team:
            members = sorted(tournament.teams, key=lambda m: m.name.lower())
            member_options = {str(m.id): m.name for m in members}

            def member_name(member_id: int) -> str:
                member = tournament.teams_by_id.get(member_id)
                return member.name if member else f'#{member_id}'
        else:
            members = sorted(
                tournament.tournament_players, key=lambda m: m.last_name.lower()
            )
            member_options = {str(m.id): m.full_name for m in members}

            def member_name(member_id: int) -> str:
                member = tournament.tournament_players_by_id.get(member_id)
                return member.full_name if member else f'#{member_id}'

        def display(groups: list[tuple[bool, list[int]]]) -> list[dict]:
            return [
                {
                    'is_hard': is_hard,
                    'members': [member_name(mid) for mid in member_ids],
                    'count': len(member_ids),
                }
                for is_hard, member_ids in groups
            ]

        dimension_options = {'': '-'}
        for dimension in tournament.prohibited_pairing_dimensions():
            dimension_options[dimension.id] = dimension.label

        manual_groups = [
            {
                'index': index,
                'is_hard': group.is_hard,
                'members': [member_name(mid) for mid in group.member_ids],
            }
            for index, group in enumerate(tournament.manual_prohibited_pairing_groups())
        ]

        # The snapshot stores the configured hard + soft groups that were
        # the basis for this round's pairing, so they display directly as
        # groups. ``protect_rank`` (set when soft groups were relaxed) lets
        # us also regenerate the effective groups actually enforced.
        snapshot = tournament.prohibited_pairing_snapshot(round_)
        snapshot_groups = display(
            [(group.is_hard, list(group.member_ids)) for group in snapshot]
        )
        # Only surface the relaxation detail when a soft separation was
        # actually released. A round that could protect everyone still
        # stores protect_rank at the bottom rank (full protection) — that
        # is not a relaxation and must not be announced as one.
        pp_protect_rank = (
            next(
                (
                    group.protect_rank
                    for group in snapshot
                    if group.protect_rank is not None
                ),
                None,
            )
            if tournament.prohibited_pairing_was_relaxed(round_)
            else None
        )
        pp_released = [
            member_name(mid)
            for mid in tournament.released_prohibited_pairing_members(round_)
        ]

        template_context = {
            'modal': 'prohibited-pairings',
            'pp_round': round_,
            'pp_locked': locked,
            'pp_is_team': is_team,
            'pp_dimension_options': dimension_options,
            'pp_dimension': tournament.prohibited_pairing_dimension_id or '',
            'pp_dimension_is_hard': tournament.prohibited_pairing_dimension_is_hard,
            'pp_forced_by_rule_set': (
                tournament.prohibited_pairing_forced_by_rule_set is not None
            ),
            'pp_rule_set_name': tournament.rule_set.name if tournament.rule_set else '',
            'pp_auto_groups': [
                {
                    'label': key,
                    'members': [member_name(mid) for mid in member_ids],
                    'count': len(member_ids),
                }
                for key, member_ids in (
                    tournament.dimension_prohibited_pairing_buckets()
                )
            ],
            'pp_manual_groups': manual_groups,
            # Rule-set / results-based groups for this round (read-only).
            # Once the round is paired they are part of the frozen snapshot,
            # so only surface them while still configurable.
            'pp_rule_groups': []
            if locked
            else [
                {
                    'label': group.name,
                    'is_hard': group.is_hard,
                    'members': [member_name(mid) for mid in group.member_ids],
                    'count': len(group.member_ids),
                }
                for group in tournament.round_rule_prohibited_pairing_groups(round_)
            ],
            'pp_member_options': member_options,
            'pp_snapshot_groups': snapshot_groups,
            'pp_protect_rank': pp_protect_rank,
            'pp_released': pp_released,
            'pp_show_manual_form': show_manual_form,
            'pp_manual_form_index': manual_form_index,
            'data': data or {},
            'errors': errors or {},
        }
        return cls._admin_event_pairings_render(web_context, template_context)

    @staticmethod
    def _manual_groups_as_tuples(
        tournament: Tournament,
    ) -> list[tuple[bool, list[int]]]:
        return [
            (group.is_hard, list(group.member_ids))
            for group in tournament.manual_prohibited_pairing_groups()
        ]

    @get(
        path='/pairings/prohibited/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-prohibited-pairings-modal',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_admin_prohibited_pairings_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        return self._render_prohibited_pairings_modal(web_context)

    @patch(
        path='/pairings/prohibited/config/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-prohibited-pairings-config',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_admin_prohibited_pairings_config(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        if (
            not tournament.round_has_pairings(round)
            and tournament.prohibited_pairing_forced_by_rule_set is None
        ):
            dimension = WebContext.form_data_to_str(data, 'dimension') or None
            is_hard = WebContext.form_data_to_bool(data, 'dimension_is_hard') or False
            with EventDatabase(tournament.event.uniq_id, True) as database:
                tournament.set_prohibited_pairing_config(dimension, is_hard, database)
        return self._render_prohibited_pairings_modal(web_context)

    @get(
        path='/pairings/prohibited/manual-form/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-prohibited-pairings-manual-form',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_admin_prohibited_pairings_manual_form(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        index: FromQuery[int] = -1,
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        data: dict[str, str] = {}
        manual_index: int | None = None
        if index >= 0:
            groups = tournament.manual_prohibited_pairing_groups()
            if index < len(groups):
                manual_index = index
                group = groups[index]
                data = {
                    'member_ids': ','.join(str(mid) for mid in group.member_ids),
                    'is_hard': 'on' if group.is_hard else '',
                }
        return self._render_prohibited_pairings_modal(
            web_context,
            show_manual_form=True,
            manual_form_index=manual_index,
            data=data,
        )

    @post(
        path='/pairings/prohibited/manual-save/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-prohibited-pairings-manual-save',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
    )
    async def htmx_admin_prohibited_pairings_manual_save(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        data: Annotated[
            dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED)
        ],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        if tournament.round_has_pairings(round):
            return self._render_prohibited_pairings_modal(web_context)
        raw_ids = WebContext.form_data_to_str(data, 'member_ids') or ''
        member_ids = [int(part) for part in raw_ids.split(',') if part.strip()]
        is_hard = WebContext.form_data_to_bool(data, 'is_hard') or False
        raw_index = WebContext.form_data_to_str(data, 'index') or ''
        errors: dict[str, str] = {}
        if len(member_ids) < 2:
            errors['member_ids'] = _('Select at least two members.')
        if errors:
            return self._render_prohibited_pairings_modal(
                web_context,
                show_manual_form=True,
                manual_form_index=int(raw_index) if raw_index else None,
                data=data,
                errors=errors,
            )
        groups = self._manual_groups_as_tuples(tournament)
        if raw_index:
            index = int(raw_index)
            if 0 <= index < len(groups):
                groups[index] = (is_hard, member_ids)
        else:
            groups.append((is_hard, member_ids))
        with EventDatabase(tournament.event.uniq_id, True) as database:
            tournament.set_manual_prohibited_pairing_groups(groups, database)
        return self._render_prohibited_pairings_modal(web_context)

    @delete(
        path='/pairings/prohibited/manual/'
        '{event_uniq_id:str}/{tournament_id:int}/{round:int}/{index:int}',
        name='admin-prohibited-pairings-manual-delete',
        guards=[TournamentActionGuard(AuthAction.USE_PAIRING_ENGINE)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_prohibited_pairings_manual_delete(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        index: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id, round)
        tournament = web_context.get_admin_tournament()
        if not tournament.round_has_pairings(round):
            groups = self._manual_groups_as_tuples(tournament)
            if 0 <= index < len(groups):
                del groups[index]
                with EventDatabase(tournament.event.uniq_id, True) as database:
                    tournament.set_manual_prohibited_pairing_groups(groups, database)
        return self._render_prohibited_pairings_modal(web_context)

    @put(
        path='/tournament/add-illegal-move/{event_uniq_id:str}/{tournament_id:int}/{round:int}/{player_id:int}',
        name='admin-tournament-add-illegal-move',
        guards=[TournamentActionGuard(AuthAction.SET_ILLEGAL_MOVES)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_tournament_add_illegal_move(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context: PairingsAdminWebContext = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            player_id=player_id,
            round_=round,
        )
        tournament = web_context.get_admin_tournament()
        tournament_player = web_context.get_admin_player()
        tournament.store_illegal_move(tournament_player)
        return self._admin_event_pairings_render(
            web_context=web_context,
        )

    @delete(
        path='/tournament/delete-illegal-move/{event_uniq_id:str}/{tournament_id:int}/{round:int}/{player_id:int}',
        name='admin-tournament-delete-illegal-move',
        guards=[TournamentActionGuard(AuthAction.SET_ILLEGAL_MOVES)],
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_tournament_delete_illegal_move(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
        player_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            player_id=player_id,
            round_=round,
        )
        tournament = web_context.get_admin_tournament()
        tournament_player = web_context.get_admin_player()
        tournament.delete_illegal_move(tournament_player)
        return self._admin_event_pairings_render(
            web_context=web_context,
        )

    @get(
        path='/pairings/needs-refresh-message/{event_uniq_id:str}/{tournament_id:int}/{round:int}/{reason:str}',
        name='pairings-needs-refresh-message',
    )
    async def htmx_pairings_refresh_message(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        tournament_id: FromPath[int],
        round: FromPath[int],
        reason: FromPath[str],
        ignore: FromQuery[bool] = False,
    ) -> Template:
        if ignore:
            return HTMXTemplate(template_name='/common/empty.html')
        return HTMXTemplate(
            template_name='/admin/common/needs_refresh.html',
            context={
                'url': request.app.route_reverse(
                    'admin-event-pairings-tab',
                    event_uniq_id=event_uniq_id,
                    tournament_id=tournament_id,
                    round=round,
                ),
                'reason': reason,
            },
        )

    @get(
        path=(
            '/pairings/absents-modal/new-check-ins-message/'
            '{event_uniq_id:str}/{tournament_id:int}/{round:int}'
        ),
        name='absents-modal-new-check-ins-message',
    )
    async def htmx_absents_modal_new_check_ins_message(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )
        return HTMXTemplate(
            template_name='/admin/pairings/absents_new_check_ins_alert.html',
            context=web_context.template_context,
        )

    @classmethod
    def publish_new_user_results(
        cls,
        channels: ChannelsPlugin,
        event_uniq_id: str,
        tournament_id: int,
        round_: int,
    ):
        channels.publish(
            {
                'event': f'new-user-results|{event_uniq_id}|{tournament_id}|{round_}',
                'data': '',
            },
            ['ws'],
        )
        channels.publish(
            {
                'event': f'new-user-results|{event_uniq_id}',
                'data': '',
            },
            ['ws'],
        )

    @get(
        path='/pairings/info-modal/{event_uniq_id:str}/{tournament_id:int}/{round:int}',
        name='admin-pairings-info-modal',
    )
    async def admin_pairings_info_modal(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        round: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(
            request,
            tournament_id=tournament_id,
            round_=round,
        )
        tournament = web_context.get_admin_tournament()

        if tournament.event.is_team_event:
            return self._team_pairings_info_modal(web_context, tournament, round)

        engine = tournament.pairing_variation.engine
        assert isinstance(engine, BbpPairings)

        warning: str | None = None
        (history, boards) = engine.get_history(tournament=tournament, round_=round)
        if tournament.round_has_pairings(round) and engine.pairings_diff(
            tournament, round, ignore_order=False, expected_stored_boards=boards
        ):
            warning = _(
                'Current pairings differ from the expected Swiss pairings, '
                'possibly due to manual changes, complementary pairings, '
                'or renumbering after rating/late-entry adjustments.'
            )

        buckets: dict[float, list[TournamentHistoryPlayer]] = defaultdict(list)

        # Put each player in the right bucket
        for player in history.players:
            buckets[player.points].append(player)

        # Sort players within each bucket by player id
        for pts, players in buckets.items():
            players.sort(key=lambda p: p.id)

        # Create grouped list
        grouped = [(pts, players) for pts, players in buckets.items()]

        # Sort groups by points (highest first)
        grouped.sort(key=lambda it: it[0], reverse=True)

        return self._admin_event_pairings_render(
            web_context,
            {
                'modal': 'pairing_info',
                'pairing_history': grouped,
                'players_by_pairing_number': tournament.tournament_players_by_pairing_number,
                'warning': warning,
            },
        )

    @classmethod
    def _team_pairing_checklist(
        cls, tournament: 'Tournament', round_: int
    ) -> 'TeamTournamentHistory | None':
        """The engine's checklist for *round_*, or ``None`` when it can't
        supply one — the round-robin team engines pair from a fixed table
        and never run bbpPairings, and a round that cannot be paired has
        no checklist to show."""
        engine = tournament.pairing_variation.engine
        if not isinstance(engine, TeamSwissEngine):
            return None
        try:
            return engine.get_team_history(tournament, round_)
        except SharlyChessException as exception:
            logger.warning(
                'Could not read the team pairing checklist for round %s: %s',
                round_,
                exception,
            )
            return None

    @classmethod
    def _team_pairings_info_modal(
        cls,
        web_context: PairingsAdminWebContext,
        tournament: Tournament,
        round: int,
    ) -> Template:
        """Team-mode counterpart to the individual info modal: per-team
        rows with TPN, name, accumulated MP/GP at the start of *round*,
        and the chronological list of opponents up to *round - 1* (each
        rendered as the opposing team's TPN, with a tooltip carrying
        the team name)."""
        opponents_by_team: dict[int, list[int | None]] = {
            team.id: [] for team in tournament.teams
        }
        # Per-team colour history on board 0 (the team's overall colour
        # in each match). Same length as ``opponents_by_team[id]``.
        colors_by_team: dict[int, list[str | None]] = {
            team.id: [] for team in tournament.teams
        }
        pattern = tournament.color_pattern or ''
        team_a_board0_color = pattern[0].upper() if pattern else 'W'
        team_b_board0_color = 'B' if team_a_board0_color == 'W' else 'W'
        for r in range(1, round):
            paired_team_ids: set[int] = set()
            for tb in tournament.get_round_team_boards(r):
                stb = tb.stored_team_board
                if stb.team_b_id is None:
                    opponents_by_team.setdefault(stb.team_a_id, []).append(None)
                    colors_by_team.setdefault(stb.team_a_id, []).append(None)
                    paired_team_ids.add(stb.team_a_id)
                    continue
                opponents_by_team.setdefault(stb.team_a_id, []).append(stb.team_b_id)
                opponents_by_team.setdefault(stb.team_b_id, []).append(stb.team_a_id)
                colors_by_team.setdefault(stb.team_a_id, []).append(team_a_board0_color)
                colors_by_team.setdefault(stb.team_b_id, []).append(team_b_board0_color)
                paired_team_ids.add(stb.team_a_id)
                paired_team_ids.add(stb.team_b_id)
            for tid, hist in opponents_by_team.items():
                if tid not in paired_team_ids:
                    hist.append(None)
                    colors_by_team.setdefault(tid, []).append(None)
        teams_by_id = tournament.event.teams_by_id
        rows: list[dict[str, Any]] = []
        # Prefer the engine's own checklist: it is what the pairing was
        # actually decided on, so nothing shown here can drift from it.
        # Only the team-Swiss engine goes through bbpPairings; the
        # round-robin ones pair from a fixed table and are reconstructed
        # below.
        history = cls._team_pairing_checklist(tournament, round)
        # Round-robin team engines don't run bbpPairings and never use a
        # secondary score for colours, so the reconstruction below leaves
        # the column hidden too.
        show_secondary = False
        if history is not None:
            team_by_tpn = {
                team.pairing_number: team
                for team in tournament.teams
                if team.pairing_number is not None
            }
            # The engine only reports a secondary score when the
            # tournament uses one for colour allocation (C.04.6 §4.2.2).
            # This modal explains the pairing, so rather than substituting
            # a figure the engine ignored, the column is dropped.
            show_secondary = any(
                entry.secondary_points is not None for entry in history.teams
            )
            for entry in history.teams:
                team = team_by_tpn.get(entry.id)
                if team is None:
                    continue
                opponent = team_by_tpn.get(entry.current_opponent or 0)
                rows.append(
                    {
                        'team': team,
                        'tpn': entry.id,
                        'mp': entry.points,
                        'gp': entry.secondary_points,
                        'rank': None,
                        'opponents': [
                            getattr(team_by_tpn.get(tpn or 0), 'id', None)
                            for tpn in entry.previous_opponents
                        ],
                        'colors': [
                            color.value if color else None
                            for color in entry.color_history
                        ],
                        'preference': entry.color_preference,
                        'eligible_for_bye': entry.eligible_for_bye,
                        'current_opponent': opponent,
                        'current_color': entry.current_color,
                        'has_bye': entry.has_bye,
                    }
                )
        else:
            # Standings as they stand entering this round (the modal shows
            # the accumulated MP/GP "at the start of round").
            for row in tournament.team_standings(after_round=round - 1):
                team = row['team']
                rows.append(
                    {
                        'team': team,
                        'tpn': team.pairing_number,
                        'mp': tournament.team_primary_score_before_round(
                            team.id, round
                        ),
                        'gp': row['gp'],
                        'rank': row['rank'],
                        'opponents': opponents_by_team.get(team.id, []),
                        'colors': colors_by_team.get(team.id, []),
                        'preference': None,
                        'eligible_for_bye': None,
                        'current_opponent': None,
                        'current_color': None,
                        'has_bye': False,
                    }
                )
        buckets: dict[float, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[row['mp']].append(row)
        for entries in buckets.values():
            entries.sort(key=lambda r: (r['tpn'] or 0, r['team'].name.lower()))
        grouped = sorted(buckets.items(), key=lambda it: it[0], reverse=True)
        return cls._admin_event_pairings_render(
            web_context,
            {
                'modal': 'team_pairing_info',
                'team_info_groups': grouped,
                'show_secondary': show_secondary,
                'primary_is_game_points': (
                    tournament.primary_score == ScoreType.GAME_POINTS
                ),
                'teams_by_id': teams_by_id,
                'history_columns': max((len(r['opponents']) for r in rows), default=0),
            },
        )

    @patch(
        path='/manual-tiebreak/update/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-manual-tiebreak-update',
    )
    async def htmx_admin_manual_tiebreak_update(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, str | list[int]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id=tournament_id)

        tournament = web_context.get_admin_tournament()

        player_data = data['player']
        ordered_player_ids: list[int] = (
            player_data if isinstance(player_data, list) else []
        )

        # Group players by manual_rank_key, preserving current order
        by_rank: dict[object, list[TournamentPlayer]] = defaultdict(list)
        for tournament_player in sorted(
            tournament.tournament_players, key=attrgetter('rank'), reverse=True
        ):
            by_rank[tournament_player.before_manual_rank_key].append(tournament_player)

        players_to_update: dict[int, int | None] = {}

        #  Update manual_tiebreaks: assign only to point groups whose index varies from the natural sort order, clear for others
        for group in by_rank.values():
            # Singletons never need manual tiebreak
            if len(group) <= 1:
                for tournament_player in group:
                    if tournament_player.manual_tiebreak is not None:
                        players_to_update[tournament_player.id] = None
                continue

            # Current order (by manual_rank_key) and submitted order (restricted to this group)
            current_group_ids = [tournament_player.id for tournament_player in group][
                ::-1
            ]

            new_group_ids = [
                pid for pid in ordered_player_ids if pid in current_group_ids
            ]
            # Ignore groups that have not been modified
            if current_group_ids == new_group_ids:
                continue

            # Maps of index within the group
            for index, player_id in enumerate(new_group_ids):
                players_to_update[player_id] = len(group) - index

        if players_to_update:
            with EventDatabase(tournament.event.uniq_id, True) as database:
                database.set_tournament_players_manual_tiebreak(
                    tournament_id, players_to_update
                )

        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, reload_event=True
        )

        # Re-render the admin pairings view
        return self._admin_event_pairings_render(web_context)

    @post(
        path='/manual-tiebreak/reset/{event_uniq_id:str}/{tournament_id:int}',
        name='admin-manual-tiebreak-reset',
    )
    async def htmx_admin_manual_tiebreak_reset(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = PairingsAdminWebContext(request, tournament_id=tournament_id)
        tournament = web_context.get_admin_tournament()
        with EventDatabase(event_uniq_id, True) as database:
            tournament.delete_manual_tie_break_values(database)
        web_context = PairingsAdminWebContext(
            request, tournament_id=tournament_id, reload_event=True
        )
        return self._admin_event_pairings_render(web_context)
