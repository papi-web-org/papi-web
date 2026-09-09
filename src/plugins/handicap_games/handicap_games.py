from operator import attrgetter
from typing import Any, TYPE_CHECKING

from packaging.version import Version

from common.i18n import _
from data.columns.board_table import BoardColumn, BlackRatingColumn, WhiteTitleColumn
from plugins.handicap_games import PLUGIN_NAME
from plugins.handicap_games.handicap_games_entity import (
    WhiteTimeControlColumn,
    BlackTimeControlColumn,
)
from plugins.handicap_games.utils import (
    HandicapGameUtils,
    HandicapGamesTournamentPluginData,
    HandicapGamesTransientPlayerPluginData,
)
from plugins.hookspec import hookimpl
from plugins.utils import (
    Plugin,
    PluginData,
    PluginUtils,
)
from utils.time_control import parse_time_control_trf25
from web.controllers.base_controller import WebContext
from data.columns.column import ColumnUsage
from utils.enum import EventType

if TYPE_CHECKING:
    from data.event import Event
    from data.tournament import Tournament
    from data.player import TournamentPlayer
    from database.sqlite.event.event_store import StoredEvent, StoredTournament


class HandicapGamesPlugin(Plugin):
    @staticmethod
    def static_id() -> str:
        return PLUGIN_NAME

    @property
    def supported_event_types(self) -> list[EventType]:
        return [EventType.INDIVIDUAL]

    @staticmethod
    def static_name() -> str:
        return _('Handicap games')

    @property
    def description(self) -> str:
        return _(
            'Adds features for handicap tournaments where weaker players are given a time advantage.'
        )

    @property
    def keywords(self) -> list[str]:
        return ['time control', 'odds']

    @property
    def doc_markdown(self) -> str:
        return '\n\n'.join(
            [
                _(
                    'In a handicap tournament the two players of a game do not get the '
                    'same thinking time: the stronger player plays with less time than '
                    "the weaker one, which which reduces the strongest player's chances of winning."
                ),
                _(
                    '- a rating step, a time penalty per step and a minimum time, '
                    'configured on the tournament;\n'
                    '- the time of each player computed for every game of the round '
                    'from the rating difference between the two players;\n'
                    '- the times of the two players displayed on the pairings screens '
                    'and on the printed documents.'
                ),
            ]
        )

    @property
    def version(self) -> Version:
        return Version('1.0.0')

    @property
    def default_is_enabled(self) -> bool:
        return False

    @property
    def default_event_is_enabled(self) -> bool:
        return False

    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        handicap_games_data = stored_tournament.plugin_data.get(PLUGIN_NAME, {})
        if any(
            handicap_games_data.get(k)
            for k in ('penalty_step', 'penalty_value', 'min_time')
        ):
            return True
        return False

    # ---------------------------------------------------------------------------------
    # Tournaments
    # ---------------------------------------------------------------------------------

    @hookimpl
    def get_tournament_plugin_data_class(self) -> tuple[str, type[PluginData]]:
        return self.id, HandicapGamesTournamentPluginData

    @hookimpl
    def get_tournament_form_fields_template_and_data(
        self, event: 'Event', tournament: 'Tournament | None'
    ) -> tuple[str, dict[str, Any]]:
        return (
            '/handicap_games_tournament_form_fields.html',
            {},
        )

    def _get_handicap_tim_control_options(
        self, time_control_trf25: str | None
    ) -> tuple[int, int]:
        initial_time = 0
        increment = 0

        # Parse time control
        # For handicap games, we only support one period, and it must be symmetric
        if time_control_trf25:
            time_control = parse_time_control_trf25(time_control_trf25)
            if time_control.black is None and len(time_control.white) == 1:
                initial_time = time_control.white[0].seconds
                increment = time_control.white[0].increment

        return initial_time, increment

    @hookimpl
    def validate_tournament_form_fields(
        self, data: dict[str, str], errors: dict[str, str]
    ):
        time_control_trf25 = WebContext.form_data_to_str(data, 'time_control_trf25')
        time_control_handicap_penalty_value = WebContext.form_data_to_int(
            data, 'handicap_games_penalty_value'
        )

        initial_time, inc = self._get_handicap_tim_control_options(time_control_trf25)
        if initial_time == 0 and time_control_handicap_penalty_value:
            errors['handicap_games_penalty_value'] = _(
                'Penalties require a time control with a single period.'
            )

    @hookimpl
    def get_tournament_page_template_context(self) -> dict[str, Any]:
        return {'handicap_game_utils': HandicapGameUtils}

    @hookimpl
    def get_tournament_card_time_control_template(self) -> str:
        return '/handicap_games_tournament_card_time_control.html'

    @hookimpl
    def set_for_round(self, tournament: 'Tournament', round_: int):
        plugin_data = HandicapGameUtils.get_tournament_plugin_data(tournament)
        if not plugin_data.penalty_value:
            return

        initial_time, increment = self._get_handicap_tim_control_options(
            tournament.time_control_trf25
        )

        for board in tournament.get_round_boards(round_):
            if not board.black_tournament_player:
                continue
            strong_tournament_player: TournamentPlayer
            weak_tournament_player: TournamentPlayer
            strong_tournament_player, weak_tournament_player = sorted(
                (board.white_tournament_player, board.black_tournament_player),
                key=attrgetter('rating'),
                reverse=True,
            )
            weak_time = initial_time
            rating_diff = (
                strong_tournament_player.rating - weak_tournament_player.rating
            )
            if not plugin_data.penalty_step:
                penalties = 0
            else:
                penalties = rating_diff // plugin_data.penalty_step
            strong_time = max(
                weak_time - penalties * (plugin_data.penalty_value or 0),
                plugin_data.min_time or 0,
            )
            strong_tournament_player.transient_plugin_data[PLUGIN_NAME] = (
                HandicapGamesTransientPlayerPluginData(
                    strong_time, increment, penalties > 0
                )
            )

            weak_tournament_player.transient_plugin_data[PLUGIN_NAME] = (
                HandicapGamesTransientPlayerPluginData(weak_time, increment, False)
            )

    # ---------------------------------------------------------------------------------
    # Print / Screens
    # ---------------------------------------------------------------------------------

    @hookimpl
    def alter_print_and_screen_board_columns(
        self,
        usage: ColumnUsage,
        board_columns: list[BoardColumn],
        tournament: 'Tournament',
    ):
        plugin_data = HandicapGameUtils.get_tournament_plugin_data(tournament)
        if not plugin_data.penalty_value:
            return
        PluginUtils.insert_on_isinstance(
            board_columns, WhiteTimeControlColumn(usage), WhiteTitleColumn, False
        )
        PluginUtils.insert_on_isinstance(
            board_columns, BlackTimeControlColumn(usage), BlackRatingColumn
        )
