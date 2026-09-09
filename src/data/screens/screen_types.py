from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple, override

from common.i18n import _
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from plugins.manager import plugin_manager
from utils.entity import IdentifiableEntity
from utils.enum import (
    BoardSelectionMode,
    EventType,
    PlayersScreenBoardFormat,
    PlayersScreenOpponentFormat,
    PlayersScreenPlayerFormat,
)

logger = get_logger()

if TYPE_CHECKING:
    from data.board import Board
    from data.columns.board_table import BoardColumn
    from data.columns.player_table import TournamentPlayerTableColumn
    from data.event import Event
    from data.screens.family import Family
    from data.player import TournamentPlayer
    from data.screens.screen import Screen
    from data.screens.screen_set import ScreenSet
    from data.tournament import Tournament
    from database.sqlite.event.event_store import StoredFamily, StoredScreen


def _build_board_columns(
    tournament: 'Tournament', show_illegal_moves: bool
) -> 'list[BoardColumn] | None':
    """Pairings-by-board columns for *tournament*, or ``None`` before the
    first round is paired."""
    from data.columns.board_table import ScreenResultColumn
    from data.columns.handlers import BoardColumnHandler
    from data.columns.player_table import ColumnUsage

    tournament.set_for_round()
    if tournament.current_round == 0:
        return None
    return BoardColumnHandler(ColumnUsage.SCREEN).get_pairings_columns(
        tournament,
        tournament.current_round,
        ScreenResultColumn,
        show_illegal_moves=show_illegal_moves,
    )


def _board_range_bounds(screen_set: 'ScreenSet') -> tuple[str, str]:
    """First/last display values for a boards/input set that has a paired
    round: match table numbers in team mode, board numbers otherwise."""
    dash = '-'
    tournament = screen_set.tournament
    if screen_set.shows_team_matches:
        first = screen_set.first_team_match
        last = screen_set.last_team_match
        return (
            str(first.display_number)
            if first is not None and first.display_number is not None
            else dash,
            str(last.display_number)
            if last is not None and last.display_number is not None
            else dash,
        )
    first_board = screen_set.first_board
    last_board = screen_set.last_board
    offset = tournament.first_board_number - 1
    return (
        str(first_board.id + offset)
        if first_board and first_board.id is not None
        else dash,
        str(last_board.id + offset)
        if last_board and last_board.id is not None
        else dash,
    )


def _board_numbers_str(screen_set: 'ScreenSet') -> str:
    """Human-readable range label for a boards/input set."""
    if screen_set.fixed_board_numbers:
        return _('boards {board_numbers}').format(
            board_numbers=', '.join(map(str, screen_set.fixed_board_numbers))
        )
    first, last = screen_set.first, screen_set.last
    if screen_set.shows_team_matches:
        match (first, last):
            case (0, 0):
                return _('all the matches')
            case (first, 0):
                return _('matches from #{first} to end').format(first=first)
            case (0, last):
                return _('matches from start to #{last}').format(last=last)
            case _:
                return _('matches from #{first} to #{last}').format(
                    first=first, last=last
                )
    if screen_set.board_selection_mode == BoardSelectionMode.PAIRING:
        # ``first``/``last`` are pairing positions, shown as-is.
        match (first, last):
            case (0, 0):
                return _('all the pairings')
            case (first, 0):
                return _('pairings from #{first} to end').format(first=first)
            case (0, last):
                return _('pairings from start to #{last}').format(last=last)
            case _:
                return _('pairings from #{first} to #{last}').format(
                    first=first, last=last
                )
    offset = screen_set.tournament.first_board_number - 1
    match (first, last):
        case (0, 0):
            return _('all the boards')
        case (first, 0):
            return _('boards from #{first} to end').format(first=first + offset)
        case (0, last):
            return _('boards from start to #{last}').format(last=last + offset)
        case _:
            return _('boards from #{first} to #{last}').format(
                first=first + offset, last=last + offset
            )


def _players_numbers_str(screen_set: 'ScreenSet') -> str:
    """Human-readable range label for a players/check-in set (players in an
    individual event, teams in a team event)."""
    first, last = screen_set.first, screen_set.last
    if screen_set.tournament.is_team_tournament:
        match (first, last):
            case (0, 0):
                return _('all the teams')
            case (first, 0):
                return _('teams from #{first} to end').format(first=first)
            case (0, last):
                return _('teams from start to #{last}').format(last=last)
            case _:
                return _('teams from #{first} to #{last}').format(
                    first=first, last=last
                )
    match (first, last):
        case (0, 0):
            return _('all the players')
        case (first, 0):
            return _('players from #{first} to end').format(first=first)
        case (0, last):
            return _('players from start to #{last}').format(last=last)
        case _:
            return _('players from #{first} to #{last}').format(first=first, last=last)


class FamilyItemRange(NamedTuple):
    """How a family of a given type splits into screens: the first/last item
    numbers it spans, the item count, and two flags driving the per-screen
    sizing (players are packed two columns deep; team-match ``number`` counts
    matches per column)."""

    first: int
    last: int
    item_count: int
    players_instead_of_boards: bool
    number_per_column: bool


def _family_range_from_total(family: 'Family', total: int) -> tuple[int, int, int]:
    """First/last/count for a family that honours its ``first``/``last`` window
    over *total* items."""
    if not total:
        return 0, 0, 0
    first = max(1, min(family.first, total)) if family.first else 1
    last = max(first, min(family.last, total)) if family.last else total
    return first, last, last - first + 1


def _board_family_item_range(family: 'Family') -> FamilyItemRange:
    """Family item range for a boards/input family: matches or boards once a
    round is paired, otherwise the registered players."""
    tournament = family.tournament
    if tournament.current_round:
        if family.shows_team_matches:
            total = len(
                [
                    team_board
                    for team_board in tournament.get_round_team_boards(
                        tournament.current_round
                    )
                    if team_board.display_number is not None
                ]
            )
            first, last, count = _family_range_from_total(family, total)
            return FamilyItemRange(first, last, count, False, True)
        total = len(tournament.boards or [])
        first, last, count = _family_range_from_total(family, total)
        return FamilyItemRange(first, last, count, False, False)
    count = len(tournament.sorted_tournament_players)
    return FamilyItemRange(1 if count else 0, count, count, True, False)


def _board_family_screen_label(screen_set: 'ScreenSet') -> str:
    """Per-screen range label shown on a boards/input family card."""
    tournament = screen_set.tournament
    if tournament.current_round and screen_set.shows_team_matches:
        first_match = screen_set.first_team_match
        last_match = screen_set.last_team_match
        if first_match is not None and last_match is not None:
            return _('Matches from #%(first)d to #%(last)d') % {
                'first': first_match.display_number,
                'last': last_match.display_number,
            }
        return _('Teams (none now)')
    if tournament.current_round:
        first_board = screen_set.first_board
        last_board = screen_set.last_board
        assert first_board is not None and last_board is not None
        assert first_board.id is not None and last_board.id is not None
        if screen_set.board_selection_mode == BoardSelectionMode.PAIRING:
            # Pairing positions, shown without the board-number offset.
            return _('Pairings from #%(first)d to #%(last)d') % {
                'first': first_board.id,
                'last': last_board.id,
            }
        offset = tournament.first_board_number - 1
        return _('Boards from #%(first)d to #%(last)d') % {
            'first': first_board.id + offset,
            'last': last_board.id + offset,
        }
    return _players_family_screen_label(screen_set)


def _players_family_screen_label(screen_set: 'ScreenSet') -> str:
    """Per-screen range label shown on a players/check-in family card (also
    the round-0 fallback for boards/input)."""
    if screen_set.tournament.is_team_tournament:
        first_team = screen_set.first_team_by_name
        last_team = screen_set.last_team_by_name
        if first_team is not None and last_team is not None:
            return _('Teams from %(first)s to %(last)s') % {
                'first': first_team.name[:12],
                'last': last_team.name[:12],
            }
        return _('Teams (none now)')
    first_player = screen_set.first_tournament_player_by_name
    last_player = screen_set.last_tournament_player_by_name
    if first_player is not None and last_player is not None:
        return _('Players from %(first)s to %(last)s') % {
            'first': first_player.last_name[:8],
            'last': last_player.last_name[:8],
        }
    return _('Players (none now)')


def _players_family_number_strings(
    family: 'Family',
) -> tuple[dict[str, str], int]:
    """Family selection-label strings for a players/check-in/ranking family
    (teams in a team event, players otherwise)."""
    if family.tournament.is_team_tournament:
        return (
            {
                'all': _('all the teams'),
                'from': _('teams from #{first} to end'),
                'to': _('teams from start to #{last}'),
                'range': _('teams from #{first} to #{last}'),
                'number': _('screens of {number} teams'),
                'number_from': _('screens of {number} teams from #{first} to end'),
                'number_to': _('screens of {number} teams from start to #{last}'),
                'number_range': _('screens of {number} teams from #{first} to #{last}'),
                'parts': _('teams on {parts} screens'),
                'parts_from': _('teams from #{first} to end, on {parts} screens'),
                'parts_to': _('teams from start to #{last}, on {parts} screens'),
                'parts_range': _('teams from #{first} to #{last}, on {parts} screens'),
            },
            0,
        )
    return (
        {
            'all': _('all the players'),
            'from': _('players from #{first} to end'),
            'to': _('players from start to #{last}'),
            'range': _('players from #{first} to #{last}'),
            'number': _('screens of {number} players'),
            'number_from': _('screens of {number} players from #{first} to end'),
            'number_to': _('screens of {number} players from start to #{last}'),
            'number_range': _('screens of {number} players from #{first} to #{last}'),
            'parts': _('players on {parts} screens'),
            'parts_from': _('players from #{first} to end, on {parts} screens'),
            'parts_to': _('players from start to #{last}, on {parts} screens'),
            'parts_range': _('players from #{first} to #{last}, on {parts} screens'),
        },
        0,
    )


def _board_family_number_strings(family: 'Family') -> tuple[dict[str, str], int]:
    """Family selection-label strings for a boards/input family (matches in
    team-vs-team mode, boards otherwise)."""
    if family.shows_team_matches:
        return (
            {
                'all': _('all the matches'),
                'from': _('matches from #{first} to end'),
                'to': _('matches from start to #{last}'),
                'range': _('matches from #{first} to #{last}'),
                'number': _('screens of {number} matches per column'),
                'number_from': _(
                    'screens of {number} matches per column from #{first} to end'
                ),
                'number_to': _(
                    'screens of {number} matches per column from start to #{last}'
                ),
                'number_range': _(
                    'screens of {number} matches per column from #{first} to #{last}'
                ),
                'parts': _('matches on {parts} screens'),
                'parts_from': _('matches from #{first} to end, on {parts} screens'),
                'parts_to': _('matches from start to #{last}, on {parts} screens'),
                'parts_range': _(
                    'matches from #{first} to #{last}, on {parts} screens'
                ),
            },
            0,
        )
    if family.fixed_board_order != BoardSelectionMode.BOARD_NUMBER:
        # PAIRING (default): first/last are pairing positions, no offset.
        return (
            {
                'all': _('all the pairings'),
                'from': _('pairings from #{first} to end'),
                'to': _('pairings from start to #{last}'),
                'range': _('pairings from #{first} to #{last}'),
                'number': _('screens of {number} pairings'),
                'number_from': _('screens of {number} pairings from #{first} to end'),
                'number_to': _('screens of {number} pairings from start to #{last}'),
                'number_range': _(
                    'screens of {number} pairings from #{first} to #{last}'
                ),
                'parts': _('pairings on {parts} screens'),
                'parts_from': _('pairings from #{first} to end, on {parts} screens'),
                'parts_to': _('pairings from start to #{last}, on {parts} screens'),
                'parts_range': _(
                    'pairings from #{first} to #{last}, on {parts} screens'
                ),
            },
            0,
        )
    return (
        {
            'all': _('all the boards'),
            'from': _('boards from #{first} to end'),
            'to': _('boards from start to #{last}'),
            'range': _('boards from #{first} to #{last}'),
            'number': _('screens of {number} boards'),
            'number_from': _('screens of {number} boards from #{first} to end'),
            'number_to': _('screens of {number} boards from start to #{last}'),
            'number_range': _('screens of {number} boards from #{first} to #{last}'),
            'parts': _('boards on {parts} screens'),
            'parts_from': _('boards from #{first} to end, on {parts} screens'),
            'parts_to': _('boards from start to #{last}, on {parts} screens'),
            'parts_range': _('boards from #{first} to #{last}, on {parts} screens'),
        },
        family.tournament.first_board_number - 1,
    )


def _board_selection_labels(is_team_matches: bool) -> dict:
    """Family create/edit selection wording for a boards/input family."""
    if is_team_matches:
        return {
            'header': _('Match selection (by table number)'),
            'first_label': _('First match:'),
            'last_label': _('Last match:'),
            'first_tooltip': _('The table number of the first match to select.'),
            'last_tooltip': _('The table number of the last match to select.'),
            'parts_placeholder': _('E.g.: 4 (split matches over 4 screens)'),
            'parts_tooltip': _(
                'The number of screens on which the matches will be distributed, optional (the number of screens is always the same and the number of matches per screen adapts to the number of matches).'
            ),
            'number_label': _('Matches per column:'),
            'number_placeholder': _('E.g.: 4 (matches per column)'),
            'number_tooltip': _(
                'The number of team matches per column, optional (the number of screens adapts to the number of matches; a match spans one row per board).'
            ),
        }
    return {
        'header': _('Board selection (by number)'),
        'first_label': _('First board:'),
        'last_label': _('Last board:'),
        'first_tooltip': _('The number of the first board to select.'),
        'last_tooltip': _('The number of the last board to select.'),
        'parts_placeholder': _('E.g.: 4 (split boards over 4 screens)'),
        'parts_tooltip': _(
            'The number of screens on which the boards will be distributed, optional (the number of screens is always the same and the number of boards per screen adapts to the number of boards).'
        ),
        'number_label': _('Rows per screen:'),
        'number_placeholder': _('E.g.: 20 (boards per screen)'),
        'number_tooltip': _(
            'The number of boards per screen, optional (the number of screens adapts to the number of boards).'
        ),
    }


def _name_or_rank_selection_labels(is_team: bool, header: str) -> dict:
    """Family selection wording for the player/team types (players, check-in,
    ranking): teams in a team event, players otherwise. *header* differs per
    ordering (alphabetical vs rank); the ``first``/``last`` tooltips are set by
    the caller."""
    unit_placeholder = _('E.g.: 20 (players per screen)')
    number_tooltip = _(
        'The number of players per screen, optional (the number of screens adapts to the number of players).'
    )
    if is_team:
        return {
            'header': header,
            'first_label': _('First team:'),
            'last_label': _('Last team:'),
            'parts_placeholder': _('E.g.: 4 (split teams over 4 screens)'),
            'parts_tooltip': _(
                'The number of screens on which the teams will be distributed, optional (the number of screens is always the same and the number of teams per screen adapts to the number of teams).'
            ),
            'number_label': _('Rows per screen:'),
            'number_placeholder': unit_placeholder,
            'number_tooltip': number_tooltip,
        }
    return {
        'header': header,
        'first_label': _('First player:'),
        'last_label': _('Last player:'),
        'parts_placeholder': _('E.g.: 4 (split players over 4 screens)'),
        'parts_tooltip': _(
            'The number of screens on which the players will be distributed, optional (the number of screens is always the same and the number of players per screen adapts to the number of players.'
        ),
        'number_label': _('Rows per screen:'),
        'number_placeholder': unit_placeholder,
        'number_tooltip': number_tooltip,
    }


def _config_record(screen: 'Screen') -> 'StoredScreen | StoredFamily':
    """The stored record carrying *screen*'s configuration: the screen's own
    record, or its family's for a family-generated screen."""
    if screen.stored_screen is not None:
        return screen.stored_screen
    if screen.family is None:
        raise RuntimeError('Family reference unexpectedly None')
    return screen.family.stored_family


class ScreenType(IdentifiableEntity, ABC):
    """A kind of screen (pairings, results, ranking, ...).

    Carries the type's UI metadata. ``static_id`` is the value persisted in
    ``StoredScreen.type``. Plugins can contribute new types through the
    ``insert_screen_types`` hook."""

    @property
    def value(self) -> str:
        """Alias of ``id`` mirroring the ``ScreenType`` enum member, so screen
        types read the same way as the enum in templates during the
        migration."""
        return self.id

    @property
    @abstractmethod
    def icon_str(self) -> str:
        """Bootstrap icon class representing the type."""

    @property
    @abstractmethod
    def tooltip_text(self) -> str:
        """Help text describing the type."""

    @property
    def families_allowed(self) -> bool:
        """Whether the type can back a family (a multi-screen)."""
        return True

    @property
    def multi_column_allowed(self) -> bool:
        """Whether multi-column layout is allowed."""
        return True

    def default_screen_name(self, screen: 'Screen') -> str:
        """The screen's automatic name when it has no stored name. A plugin
        type overrides this (or ``default_family_screen_name``) to name its
        screens."""
        if screen.stored_screen is not None:
            # Basic screen: the tournament name(s) of its sets, deduplicated.
            names: list[str] = []
            for screen_set in screen.sorted_screen_sets:
                name = screen_set.tournament.name
                if name and name not in names:
                    names.append(name)
            return ' / '.join(names) if names else _('Screen')
        return self.default_family_screen_name(screen)

    def default_family_screen_name(self, screen: 'Screen') -> str:
        """The automatic name for a family-generated screen of this type."""
        return self.name

    def shows_unpaired_players(self, screen: 'Screen') -> bool:
        """Whether unpaired players are shown for a screen of this type."""
        return False

    @property
    def supports_fixed_boards(self) -> bool:
        """Whether a set of this type can pin specific board (table) numbers."""
        return False

    def board_selection_options(self, include_specific: bool) -> dict[str, str]:
        """Labels for the board-selection mode select. ``include_specific`` is
        True for screen sets (which have a board-numbers field) and False for
        families."""
        return BoardSelectionMode.options(include_specific=include_specific)

    @property
    def allows_result_input(self) -> bool:
        """Whether the screen lets people enter results (and illegal moves)."""
        return False

    @property
    def allows_check_in(self) -> bool:
        """Whether the screen lets people check players/teams in or out."""
        return False

    @property
    def has_exit_button(self) -> bool:
        """Whether the screen offers an exit button (the interactive types)."""
        return self.allows_result_input or self.allows_check_in

    @property
    def allowed_in_rotators(self) -> bool:
        """Whether screens/families of this type can be picked for a rotator.
        Interactive types (result entry, check-in) opt out."""
        return True

    @property
    def has_config_fields(self) -> bool:
        """Whether the create/edit form shows the general configuration fields
        (menu label, timer, columns, font size, alert message). ``False`` for
        the standalone image type."""
        return True

    @property
    def board_based(self) -> bool:
        """Whether the screen is organised by board/match (rather than by
        player/team). Drives the board-vs-player wording in the admin UI."""
        return False

    @property
    def shows_copyright(self) -> bool:
        """Whether the live screen shows the copyright notice (hidden on the
        full-screen image type)."""
        return True

    def type_str(self, screen: 'Screen') -> str:
        """Human-readable label for the screen's type (may depend on the
        screen's own configuration)."""
        return self.name

    def range_bounds(
        self, screen_set: 'ScreenSet', abbreviated: bool = False
    ) -> tuple[str, str]:
        """First (``%f``) and last (``%l``) display values shown by *screen_set*.
        The default is the players-by-name range; set-based types override.
        When *abbreviated* (menu navigation) player names are cut to 3 upper-case
        characters, otherwise to 8."""
        dash = '-'
        first = screen_set.first_tournament_player_by_name
        last = screen_set.last_tournament_player_by_name

        def player_label(player: 'TournamentPlayer | None') -> str:
            if player is None:
                return dash
            return player.last_name[:3].upper() if abbreviated else player.last_name[:8]

        return player_label(first), player_label(last)

    def numbers_str(self, screen_set: 'ScreenSet') -> str:
        """Human-readable range label for *screen_set*. The default is the
        ranking wording; set-based types override."""
        match (screen_set.first, screen_set.last):
            case (0, 0):
                return _('the whole ranking')
            case (first, 0):
                return _('ranking from #{first} to end').format(first=first)
            case (0, last):
                return _('ranking from start to #{last}').format(last=last)
            case _:
                return _('ranking from #{first} to #{last}').format(
                    first=screen_set.first, last=screen_set.last
                )

    def build_columns(
        self, screen: 'Screen', tournament: 'Tournament', event: 'Event'
    ) -> 'list[TournamentPlayerTableColumn] | list[BoardColumn] | None':
        """Table columns rendered for *tournament* in this screen, or ``None``
        when the type has no per-tournament column table. Also performs any
        per-tournament setup the type's view needs."""
        tournament.set_for_round()
        return None

    def set_refresh_needed(self, screen_set: 'ScreenSet', since: datetime) -> bool:
        """Whether one of the screen's sets changed since *since* and needs a
        refresh."""
        tournament = screen_set.tournament
        return max(tournament.last_update, tournament.last_player_update) > since

    def refresh_needed(self, screen: 'Screen', since: datetime) -> bool:
        """Whether the screen changed since *since* (the caller already checks
        the event/screen/family timestamps)."""
        return any(
            self.set_refresh_needed(screen_set, since)
            for screen_set in screen.screen_sets
        )

    def supports_event_type(self, event_type: EventType) -> bool:
        """Whether screens of this type can be created in an event of
        *event_type*."""
        return True

    @property
    def set_template(self) -> str | None:
        """Template rendering one of the screen's sets (for set-based types
        that iterate ``screen.sorted_screen_sets``). ``None`` for standalone
        types (see ``content_template``)."""
        return None

    @property
    def has_screen_sets(self) -> bool:
        """Whether a screen of this type is built from per-tournament screen
        sets (rather than a single standalone view)."""
        return self.set_template is not None

    @property
    def content_template(self) -> str | None:
        """Template rendering the whole screen content for a standalone type
        (no per-set iteration). ``None`` for set-based types."""
        return None

    @property
    def form_template(self) -> str | None:
        """Extra fields rendered in the screen create/edit modal for this
        type. ``None`` for the built-in types (their fields are inline in the
        modal); a plugin type points this at its own form partial."""
        return None

    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        """Extract this type's ``StoredScreen`` fields from the submitted form
        *data*, adding any validation messages to *errors*."""
        return {}

    def default_form_data(self, screen: 'Screen') -> dict:
        """This type's stored fields as form values, to pre-fill the edit
        form."""
        return {}

    def default_family_form_data(self, family: 'Family') -> dict:
        """This type's stored fields as form values, to pre-fill the family
        edit form."""
        return {}

    def create_form_data(self, event: 'Event') -> dict:
        """This type's default field values for a new screen/family."""
        return {}

    def set_context(self, screen_set: 'ScreenSet') -> dict:
        """The data injected into ``set_template`` for one of the screen's
        sets. The type owns what its template needs, so the template reads
        ``data.*`` rather than reaching into the screen."""
        return {}

    def content_context(self, screen: 'Screen') -> dict:
        """The data injected into ``content_template`` for a standalone
        type."""
        return {}

    @property
    def card_config_template(self) -> str | None:
        """The general-configuration fragment of the admin card (type line,
        columns, menu label, timer, exit button). Shared by the configurable
        types; ``None`` for the standalone image type."""
        return '/admin/screens/cards/config_card.html'

    @property
    def card_template(self) -> str | None:
        """The always-shown summary fragment for the admin screen card (the
        screen's tournament sets for set-based types). ``None`` when the type
        has no compact summary of its own."""
        return '/admin/screens/cards/sets_card.html' if self.has_screen_sets else None

    @property
    def card_detail_template(self) -> str | None:
        """The expanded admin-card fragment (shown with the details) rendering
        this type's configuration. ``None`` when the type shows no
        type-specific detail."""
        return None

    @property
    def card_action_button_template(self) -> str | None:
        """A fragment rendering type-specific action buttons in the admin
        screen card's button row (alongside edit/clone/delete). ``None`` when
        the type contributes no extra buttons."""
        return None

    def card_context(self, screen: 'Screen') -> dict:
        """The data injected into ``card_detail_template`` for a screen card."""
        return {}

    def family_card_context(self, family: 'Family') -> dict:
        """The data injected into ``card_detail_template`` for a family card
        (same fragment as ``card_context``, read from the family's record)."""
        return {}

    def family_type_str(self, family: 'Family') -> str:
        """Human-readable label for a family's type (may depend on the
        family's configuration)."""
        return self.name

    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        """How a family of this type splits into screens. Only the
        family-capable types implement this."""
        raise NotImplementedError(f'{type(self).__name__} does not back a family')

    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        """The range label for one generated screen of a family, shown on the
        family card. Only the family-capable types implement this."""
        raise NotImplementedError(f'{type(self).__name__} does not back a family')

    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        """The create/edit-form selection wording (section header, first/last
        and screens/rows labels and tooltips) for a family of this type. Only
        the family-capable types implement this."""
        raise NotImplementedError(f'{type(self).__name__} does not back a family')

    def family_number_strings(self, family: 'Family') -> tuple[dict[str, str], int]:
        """The selection-label string table and board-number offset for a
        family of this type (see ``Family.numbers_str``)."""
        return _players_family_number_strings(family)

    def depends_on_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        """Whether the screen is a dedicated view of *tournament* (used to
        decide which screens a tournament change must refresh)."""
        return all(
            screen_set.tournament.id == tournament.id
            for screen_set in screen.screen_sets
        )

    def relates_to_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        """Whether the screen shows *tournament* among others."""
        return any(
            screen_set.tournament.id == tournament.id
            for screen_set in screen.sorted_screen_sets
        )


class CheckInScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'check-in'

    @staticmethod
    def static_name() -> str:
        return _('Check-in')

    @property
    def icon_str(self) -> str:
        return 'bi-check-square'

    @property
    def tooltip_text(self) -> str:
        return _('Check-in screens allow players to check-in or out.')

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        return {
            'input_exit_button': WebContext.form_data_to_bool(data, 'input_exit_button')
        }

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        assert screen.stored_screen is not None
        return {'input_exit_button': screen.stored_screen.input_exit_button}

    @override
    def default_family_form_data(self, family: 'Family') -> dict:
        return {'input_exit_button': family.stored_family.input_exit_button}

    @override
    def default_family_screen_name(self, screen: 'Screen') -> str:
        first_set = screen.sorted_screen_sets[0]
        if first_set.tournament.is_team_tournament:
            return first_set.name_for_teams
        return first_set.name_for_players

    @override
    def shows_unpaired_players(self, screen: 'Screen') -> bool:
        return True

    @property
    @override
    def set_template(self) -> str | None:
        return '/user/screen/sets/check_in_set.html'

    @property
    @override
    def allows_check_in(self) -> bool:
        return True

    @property
    @override
    def allowed_in_rotators(self) -> bool:
        return False

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/exit_button_form.html'

    @override
    def create_form_data(self, event: 'Event') -> dict:
        return {'input_exit_button': False}

    @override
    def range_bounds(
        self, screen_set: 'ScreenSet', abbreviated: bool = False
    ) -> tuple[str, str]:
        if screen_set.tournament.is_team_tournament:
            dash = '-'
            first = screen_set.first_team_by_name
            last = screen_set.last_team_by_name
            return (
                first.name[:12] if first is not None else dash,
                last.name[:12] if last is not None else dash,
            )
        return super().range_bounds(screen_set, abbreviated)

    @override
    def numbers_str(self, screen_set: 'ScreenSet') -> str:
        return _players_numbers_str(screen_set)

    @override
    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        tournament = family.tournament
        if tournament.is_team_tournament:
            count = len(
                [
                    team
                    for team in family.event.teams_by_id.values()
                    if team.tournament_id == tournament.id
                ]
            )
        else:
            count = len(tournament.sorted_tournament_players)
        return FamilyItemRange(1 if count else 0, count, count, True, False)

    @override
    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        return _players_family_screen_label(screen_set)

    @override
    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        header = (
            _('Team selection (by alphabetical order)')
            if is_team
            else _('Player selection (by alphabetical order)')
        )
        selection = _name_or_rank_selection_labels(is_team, header)
        selection['first_tooltip'] = (
            _('The number of the first team to select.')
            if is_team
            else _('The number of the first player to select.')
        )
        selection['last_tooltip'] = (
            _('The number of the last team to select.')
            if is_team
            else _('The number of the last player to select.')
        )
        return selection


class InputScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'input'

    @staticmethod
    def static_name() -> str:
        return _('Results entry')

    @property
    def icon_str(self) -> str:
        return 'bi-pencil'

    @property
    def tooltip_text(self) -> str:
        return _(
            'Input screens show pairings by board number and allow people to '
            'enter results.'
        )

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        return {
            'input_exit_button': WebContext.form_data_to_bool(data, 'input_exit_button')
        }

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        assert screen.stored_screen is not None
        return {'input_exit_button': screen.stored_screen.input_exit_button}

    @override
    def default_family_form_data(self, family: 'Family') -> dict:
        return {'input_exit_button': family.stored_family.input_exit_button}

    @override
    def default_family_screen_name(self, screen: 'Screen') -> str:
        return screen.sorted_screen_sets[0].name_for_boards

    @override
    def shows_unpaired_players(self, screen: 'Screen') -> bool:
        return True

    @property
    @override
    def set_template(self) -> str | None:
        return '/user/screen/sets/boards_set.html'

    @property
    @override
    def supports_fixed_boards(self) -> bool:
        return True

    @property
    @override
    def allows_result_input(self) -> bool:
        return True

    @property
    @override
    def allowed_in_rotators(self) -> bool:
        return False

    @property
    @override
    def board_based(self) -> bool:
        return True

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/exit_button_form.html'

    @override
    def create_form_data(self, event: 'Event') -> dict:
        return {'input_exit_button': False}

    @override
    def build_columns(
        self, screen: 'Screen', tournament: 'Tournament', event: 'Event'
    ) -> 'list[TournamentPlayerTableColumn] | list[BoardColumn] | None':
        show_illegal_moves = tournament.record_illegal_moves > 0
        return _build_board_columns(tournament, show_illegal_moves)

    @override
    def set_refresh_needed(self, screen_set: 'ScreenSet', since: datetime) -> bool:
        return (
            super().set_refresh_needed(screen_set, since)
            or screen_set.tournament.last_pairing_update > since
        )

    @override
    def range_bounds(
        self, screen_set: 'ScreenSet', abbreviated: bool = False
    ) -> tuple[str, str]:
        if not screen_set.tournament.current_round:
            return super().range_bounds(screen_set, abbreviated)
        return _board_range_bounds(screen_set)

    @override
    def numbers_str(self, screen_set: 'ScreenSet') -> str:
        return _board_numbers_str(screen_set)

    @override
    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        return _board_family_item_range(family)

    @override
    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        return _board_family_screen_label(screen_set)

    @override
    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        return _board_selection_labels(is_team_matches)

    @override
    def family_number_strings(self, family: 'Family') -> tuple[dict[str, str], int]:
        return _board_family_number_strings(family)


class BoardsScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'boards'

    @staticmethod
    def static_name() -> str:
        return _('Pairings by board')

    @property
    def icon_str(self) -> str:
        return 'bi-card-list'

    @property
    def tooltip_text(self) -> str:
        return _('Boards screens show pairings by board number.')

    @override
    def default_family_screen_name(self, screen: 'Screen') -> str:
        return screen.sorted_screen_sets[0].name_for_boards

    @override
    def shows_unpaired_players(self, screen: 'Screen') -> bool:
        # Shown so players appear before the first round is paired.
        return True

    @property
    @override
    def set_template(self) -> str | None:
        return '/user/screen/sets/boards_set.html'

    @property
    @override
    def supports_fixed_boards(self) -> bool:
        return True

    @property
    @override
    def board_based(self) -> bool:
        return True

    @override
    def build_columns(
        self, screen: 'Screen', tournament: 'Tournament', event: 'Event'
    ) -> 'list[TournamentPlayerTableColumn] | list[BoardColumn] | None':
        return _build_board_columns(tournament, show_illegal_moves=False)

    @override
    def set_refresh_needed(self, screen_set: 'ScreenSet', since: datetime) -> bool:
        return (
            super().set_refresh_needed(screen_set, since)
            or screen_set.tournament.last_pairing_update > since
        )

    @override
    def range_bounds(
        self, screen_set: 'ScreenSet', abbreviated: bool = False
    ) -> tuple[str, str]:
        if not screen_set.tournament.current_round:
            return super().range_bounds(screen_set, abbreviated)
        return _board_range_bounds(screen_set)

    @override
    def numbers_str(self, screen_set: 'ScreenSet') -> str:
        return _board_numbers_str(screen_set)

    @override
    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        return _board_family_item_range(family)

    @override
    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        return _board_family_screen_label(screen_set)

    @override
    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        return _board_selection_labels(is_team_matches)

    @override
    def family_number_strings(self, family: 'Family') -> tuple[dict[str, str], int]:
        return _board_family_number_strings(family)


class PlayersScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'players'

    @staticmethod
    def static_name() -> str:
        return _('Pairings by player')

    @property
    def icon_str(self) -> str:
        return 'bi-people'

    @property
    def tooltip_text(self) -> str:
        return _('Players screens show pairings by alphabetical order.')

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        return {
            'players_show_unpaired': WebContext.form_data_to_bool(
                data, 'players_show_unpaired'
            ),
            'players_player_format': WebContext.form_data_to_int(
                data, 'players_player_format'
            ),
            'players_board_format': WebContext.form_data_to_int(
                data, 'players_board_format'
            ),
            'players_opponent_format': WebContext.form_data_to_int(
                data, 'players_opponent_format'
            ),
        }

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        stored = screen.stored_screen
        assert stored is not None
        return self._players_form_data(
            stored.players_show_unpaired,
            stored.players_player_format,
            stored.players_board_format,
            stored.players_opponent_format,
        )

    @override
    def default_family_form_data(self, family: 'Family') -> dict:
        stored = family.stored_family
        return self._players_form_data(
            stored.players_show_unpaired,
            stored.players_player_format,
            stored.players_board_format,
            stored.players_opponent_format,
        )

    @staticmethod
    def _players_form_data(
        show_unpaired: bool | None,
        player_format: int | None,
        board_format: int | None,
        opponent_format: int | None,
    ) -> dict:
        return {
            'players_show_unpaired': show_unpaired or False,
            'players_player_format': player_format,
            'players_board_format': board_format,
            'players_opponent_format': opponent_format,
        }

    @staticmethod
    def default_player_format(event: 'Event') -> PlayersScreenPlayerFormat:
        return (
            plugin_manager.hook_for_event(
                event, 'get_default_players_screen_player_format'
            )()
            or PlayersScreenPlayerFormat.NAME_RATING_TYPE_POINTS
        )

    @staticmethod
    def default_board_format(event: 'Event') -> PlayersScreenBoardFormat:
        return (
            plugin_manager.hook_for_event(
                event, 'get_default_players_screen_board_format'
            )()
            or PlayersScreenBoardFormat.FULL
        )

    @staticmethod
    def default_opponent_format(event: 'Event') -> PlayersScreenOpponentFormat:
        return (
            plugin_manager.hook_for_event(
                event, 'get_default_players_screen_opponent_format'
            )()
            or PlayersScreenOpponentFormat.NAME_RATING_TYPE_POINTS
        )

    @staticmethod
    def default_columns(event: 'Event') -> int | None:
        return plugin_manager.hook_for_event(
            event, 'get_default_players_screen_columns'
        )()

    @override
    def create_form_data(self, event: 'Event') -> dict:
        return {
            'players_show_unpaired': True,
            'columns': self.default_columns(event),
            'players_player_format': self.default_player_format(event).value,
            'players_board_format': self.default_board_format(event).value,
            'players_opponent_format': self.default_opponent_format(event).value,
        }

    @override
    def default_family_screen_name(self, screen: 'Screen') -> str:
        return screen.sorted_screen_sets[0].name_for_players

    @override
    def shows_unpaired_players(self, screen: 'Screen') -> bool:
        value = _config_record(screen).players_show_unpaired
        assert value is not None
        return value

    @property
    @override
    def set_template(self) -> str | None:
        return '/user/screen/sets/players_set.html'

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/players_form.html'

    @override
    def supports_event_type(self, event_type: EventType) -> bool:
        # Pairings-by-player has no team counterpart (team events pair
        # matches, not individual players).
        return event_type == EventType.INDIVIDUAL

    @override
    def numbers_str(self, screen_set: 'ScreenSet') -> str:
        return _players_numbers_str(screen_set)

    def player_format(self, screen: 'Screen') -> PlayersScreenPlayerFormat:
        value = _config_record(screen).players_player_format
        assert value is not None
        return PlayersScreenPlayerFormat(value)

    def board_format(self, screen: 'Screen') -> PlayersScreenBoardFormat:
        value = _config_record(screen).players_board_format
        assert value is not None
        return PlayersScreenBoardFormat(value)

    def opponent_format(self, screen: 'Screen') -> PlayersScreenOpponentFormat:
        value = _config_record(screen).players_opponent_format
        assert value is not None
        return PlayersScreenOpponentFormat(value)

    @override
    def set_context(self, screen_set: 'ScreenSet') -> dict:
        screen = screen_set.screen
        return {
            'player_format': self.player_format(screen),
            'board_format': self.board_format(screen),
            'opponent_format': self.opponent_format(screen),
        }

    @property
    @override
    def card_detail_template(self) -> str | None:
        return '/admin/screens/cards/players_card.html'

    @override
    def card_context(self, screen: 'Screen') -> dict:
        return {
            'show_unpaired': self.shows_unpaired_players(screen),
            'player_format': self.player_format(screen),
            'board_format': self.board_format(screen),
            'opponent_format': self.opponent_format(screen),
            'tournament': screen.sorted_screen_sets[0].tournament,
        }

    @override
    def family_card_context(self, family: 'Family') -> dict:
        stored = family.stored_family
        player_format = stored.players_player_format
        board_format = stored.players_board_format
        opponent_format = stored.players_opponent_format
        assert (
            player_format is not None
            and board_format is not None
            and opponent_format is not None
        )
        return {
            'show_unpaired': stored.players_show_unpaired,
            'player_format': PlayersScreenPlayerFormat(player_format),
            'board_format': PlayersScreenBoardFormat(board_format),
            'opponent_format': PlayersScreenOpponentFormat(opponent_format),
            'tournament': family.tournament,
        }

    @override
    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        tournament = family.tournament
        if tournament.current_round:
            if family.stored_family.players_show_unpaired:
                total = len(tournament.sorted_tournament_players)
            else:
                total = len(tournament.sorted_tournament_players_without_unpaired)
        else:
            total = len(tournament.sorted_tournament_players)
        first, last, count = _family_range_from_total(family, total)
        return FamilyItemRange(first, last, count, False, False)

    @override
    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        return _players_family_screen_label(screen_set)

    @override
    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        header = (
            _('Team selection (by alphabetical order)')
            if is_team
            else _('Player selection (by alphabetical order)')
        )
        selection = _name_or_rank_selection_labels(is_team, header)
        selection['first_tooltip'] = (
            _('The number of the first team to select.')
            if is_team
            else _('The number of the first player to select.')
        )
        selection['last_tooltip'] = (
            _('The number of the last team to select.')
            if is_team
            else _('The number of the last player to select.')
        )
        return selection


class ResultsScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'results'

    @staticmethod
    def static_name() -> str:
        return _('Last results')

    @property
    def icon_str(self) -> str:
        return 'bi-1-square'

    @property
    def tooltip_text(self) -> str:
        return _('Results screens show the last results (most recent first).')

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        values: dict = {}
        try:
            values['results_limit'] = WebContext.form_data_to_int(data, 'results_limit')
        except ValueError:
            errors['results_limit'] = _('A positive integer is expected.')
        try:
            values['results_max_age'] = WebContext.form_data_to_int(
                data, 'results_max_age'
            )
        except ValueError:
            errors['results_max_age'] = _('A positive integer is expected.')
        values['results_tournament_ids'] = [
            tournament_id
            for tournament_id in WebContext.form_data_to_list_int(
                data, 'results_tournament_ids'
            )
            if tournament_id in event.tournaments_by_id
        ]
        return values

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        stored = screen.stored_screen
        assert stored is not None
        return {
            'results_limit': stored.results_limit,
            'results_max_age': stored.results_max_age,
            'results_tournament_ids': stored.results_tournament_ids,
        }

    @override
    def default_screen_name(self, screen: 'Screen') -> str:
        names: list[str] = []
        for tournament_id in self.tournament_ids(screen):
            name = screen.event.tournaments_by_id[tournament_id].name
            if name and name not in names:
                names.append(name)
        return ' / '.join(names) if names else _('Last results')

    @property
    @override
    def families_allowed(self) -> bool:
        return False

    @property
    @override
    def content_template(self) -> str | None:
        return '/user/screen/results_content.html'

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/results_form.html'

    def limit(self, screen: 'Screen') -> int:
        assert screen.stored_screen is not None
        columns = screen.columns
        stored_limit = screen.stored_screen.results_limit
        if not stored_limit:
            return SharlyChessConfig.default_results_screen_limit
        if stored_limit % columns > 0:
            results_limit = columns * (stored_limit // columns + 1)
            logger.info(
                f'Screen [{screen.uniq_id}]: Maximum number of results set to '
                f'[{results_limit}] to fit on [{columns}] columns.'
            )
            return results_limit
        return stored_limit

    def max_age(self, screen: 'Screen') -> int:
        assert screen.stored_screen is not None
        return (
            screen.stored_screen.results_max_age
            or SharlyChessConfig.default_results_screen_max_age
        )

    def tournament_ids(self, screen: 'Screen') -> list[int]:
        assert screen.stored_screen is not None
        return [
            tournament_id
            for tournament_id in screen.stored_screen.results_tournament_ids
            if tournament_id in screen.event.tournaments_by_id
        ]

    def tournament_names(self, screen: 'Screen') -> str:
        from common.i18n.utils import normalized_key

        return ', '.join(
            sorted(
                (
                    screen.event.tournaments_by_id[tournament_id].name
                    for tournament_id in self.tournament_ids(screen)
                ),
                key=normalized_key,
            )
        )

    def _results(self, screen: 'Screen') -> 'list[Board]':
        boards: list[Board] = []
        oldest = datetime.now() - timedelta(minutes=self.max_age(screen))
        tournament_ids = self.tournament_ids(screen)
        for tournament in screen.event.tournaments:
            if tournament_ids and tournament.id not in tournament_ids:
                continue
            for board in tournament.get_round_boards(tournament.current_round):
                if board.last_result_update and board.last_result_update >= oldest:
                    boards.append(board)
        boards.sort(key=lambda b: b.last_result_update or datetime.min, reverse=True)
        return boards

    def results_lists(self, screen: 'Screen') -> 'list[list[Board]]':
        results = self._results(screen)
        limit = self.limit(screen)
        column_size: int = (limit if limit else len(results)) // screen.columns
        return [
            results[i * column_size : (i + 1) * column_size]
            for i in range(screen.columns)
        ]

    @override
    def content_context(self, screen: 'Screen') -> dict:
        return {
            'title': screen.name,
            'results_lists': self.results_lists(screen),
            'print_tournament': len(
                self.tournament_ids(screen)
                or list(screen.event.tournaments_by_id.keys())
            )
            > 1,
        }

    @property
    @override
    def card_detail_template(self) -> str | None:
        return '/admin/screens/cards/results_card.html'

    @override
    def card_context(self, screen: 'Screen') -> dict:
        assert screen.stored_screen is not None
        return {
            'results_limit': self.limit(screen),
            'results_max_age': self.max_age(screen),
            'results_max_age_default': not screen.stored_screen.results_max_age,
            'tournament_ids': self.tournament_ids(screen),
            'tournament_names': self.tournament_names(screen),
        }

    @override
    def depends_on_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        return self.tournament_ids(screen) == [tournament.id]

    @override
    def relates_to_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        tournament_ids = self.tournament_ids(screen)
        return not tournament_ids or tournament.id in tournament_ids

    @override
    def refresh_needed(self, screen: 'Screen', since: datetime) -> bool:
        event = screen.event
        tournament_ids = self.tournament_ids(screen) or list(
            event.tournaments_by_id.keys()
        )
        for tournament_id in tournament_ids:
            with suppress(KeyError):
                tournament = event.tournaments_by_id[tournament_id]
                if max(tournament.last_update, tournament.last_pairing_update) > since:
                    return True
        return False


class RankingScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'ranking'

    @staticmethod
    def static_name() -> str:
        return _('Ranking')

    @property
    def icon_str(self) -> str:
        return 'bi-trophy'

    @property
    def tooltip_text(self) -> str:
        return _('Ranking screens show the players by rank.')

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        values: dict = {
            'ranking_crosstable': WebContext.form_data_to_bool(
                data, 'ranking_crosstable'
            )
        }
        try:
            values['ranking_round'] = WebContext.form_data_to_int(data, 'ranking_round')
        except ValueError:
            errors['ranking_round'] = _('A positive integer is expected.')
        try:
            values['ranking_min_points'] = WebContext.form_data_to_float(
                data, 'ranking_min_points'
            )
        except ValueError:
            errors['ranking_min_points'] = _('A positive integer is expected.')
        try:
            values['ranking_max_points'] = WebContext.form_data_to_float(
                data, 'ranking_max_points'
            )
        except ValueError:
            errors['ranking_max_points'] = _('A positive integer is expected.')
        return values

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        stored = screen.stored_screen
        assert stored is not None
        return self._ranking_form_data(
            stored.ranking_crosstable,
            stored.ranking_round,
            stored.ranking_min_points,
            stored.ranking_max_points,
        )

    @override
    def default_family_form_data(self, family: 'Family') -> dict:
        stored = family.stored_family
        return self._ranking_form_data(
            stored.ranking_crosstable,
            stored.ranking_round,
            stored.ranking_min_points,
            stored.ranking_max_points,
        )

    @staticmethod
    def _ranking_form_data(
        crosstable: bool,
        ranking_round: int | None,
        min_points: float | None,
        max_points: float | None,
    ) -> dict:
        return {
            'ranking_crosstable': crosstable,
            'ranking_round': ranking_round,
            'ranking_min_points': min_points,
            'ranking_max_points': max_points,
        }

    @override
    def create_form_data(self, event: 'Event') -> dict:
        return {'ranking_crosstable': False}

    @override
    def default_family_screen_name(self, screen: 'Screen') -> str:
        return screen.sorted_screen_sets[0].name_for_ranking

    @property
    @override
    def set_template(self) -> str | None:
        return '/user/screen/sets/ranking_set.html'

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/ranking_form.html'

    @override
    def type_str(self, screen: 'Screen') -> str:
        return _('Crosstable') if self.ranking_crosstable(screen) else _('Ranking')

    @override
    def family_type_str(self, family: 'Family') -> str:
        return (
            _('Crosstable') if family.stored_family.ranking_crosstable else _('Ranking')
        )

    def ranking_crosstable(self, screen: 'Screen') -> bool:
        return _config_record(screen).ranking_crosstable

    def ranking_round(self, screen: 'Screen') -> int | None:
        return _config_record(screen).ranking_round

    def ranking_min_points(self, screen: 'Screen') -> float | None:
        return _config_record(screen).ranking_min_points

    def ranking_max_points(self, screen: 'Screen') -> float | None:
        return _config_record(screen).ranking_max_points

    @override
    def build_columns(
        self, screen: 'Screen', tournament: 'Tournament', event: 'Event'
    ) -> 'list[TournamentPlayerTableColumn] | list[BoardColumn] | None':
        from data.columns.handlers import PlayerColumnHandler
        from data.columns.player_table import ColumnUsage

        ranking_round = tournament.correct_ranking_round(self.ranking_round(screen))
        tournament.compute_tournament_player_ranks(after_round=ranking_round)
        column_handler = PlayerColumnHandler(event, ColumnUsage.SCREEN)
        if self.ranking_crosstable(screen):
            return column_handler.get_player_crosstable_columns(
                tournament, ranking_round
            )
        return column_handler.get_player_ranking_columns(tournament)

    @override
    def set_refresh_needed(self, screen_set: 'ScreenSet', since: datetime) -> bool:
        return (
            super().set_refresh_needed(screen_set, since)
            or screen_set.tournament.last_pairing_update > since
        )

    @override
    def set_context(self, screen_set: 'ScreenSet') -> dict:
        return {'ranking_round': self.ranking_round(screen_set.screen)}

    @property
    @override
    def card_detail_template(self) -> str | None:
        return '/admin/screens/cards/ranking_card.html'

    @override
    def card_context(self, screen: 'Screen') -> dict:
        return self._card_context(
            self.ranking_round(screen),
            self.ranking_min_points(screen),
            self.ranking_max_points(screen),
        )

    @override
    def family_card_context(self, family: 'Family') -> dict:
        stored = family.stored_family
        return self._card_context(
            stored.ranking_round,
            stored.ranking_min_points,
            stored.ranking_max_points,
            # A family generates several ranking screens; the round is not
            # shown on the family card (only on each screen).
            hide_round=True,
        )

    @staticmethod
    def _card_context(
        ranking_round: int | None,
        min_points: float | None,
        max_points: float | None,
        hide_round: bool = False,
    ) -> dict:
        return {
            'ranking_round': ranking_round,
            'ranking_min_points': min_points,
            'ranking_max_points': max_points,
            'hide_round': hide_round,
        }

    @override
    def family_item_range(self, family: 'Family') -> FamilyItemRange:
        tournament = family.tournament
        stored = family.stored_family
        ranking_round = tournament.correct_ranking_round(stored.ranking_round)
        min_points = stored.ranking_min_points
        max_points = stored.ranking_max_points
        if tournament.is_team_tournament:
            from utils.enum import ScoreType

            primary_is_mp = (
                tournament.pairing_system.paired_by_team
                and tournament.primary_score == ScoreType.MATCH_POINTS
            )
            score_key = 'mp' if primary_is_mp else 'gp'
            total = len(
                [
                    row
                    for row in tournament.team_standings(after_round=ranking_round)
                    if not row['team'].is_excluded_from_standings
                    and (min_points is None or row[score_key] >= min_points)
                    and (max_points is None or row[score_key] <= max_points)
                ]
            )
        else:
            tournament.compute_tournament_player_ranks(after_round=ranking_round)
            total = len(
                [
                    player
                    for player in tournament.tournament_players_by_rank.values()
                    if not player.is_excluded_from_standings
                    and (min_points is None or (player.points or 0) >= min_points)
                    and (max_points is None or (player.points or 0) <= max_points)
                ]
            )
        first, last, count = _family_range_from_total(family, total)
        return FamilyItemRange(first, last, count, False, False)

    @override
    def family_screen_label(self, screen_set: 'ScreenSet') -> str:
        if screen_set.tournament.is_team_tournament:
            first_standing = screen_set.first_team_standing
            last_standing = screen_set.last_team_standing
            if first_standing is not None and last_standing is not None:
                return _('Teams from #%(first)d to #%(last)d') % {
                    'first': first_standing['rank'],
                    'last': last_standing['rank'],
                }
            return _('Teams (none now)')
        first_player = screen_set.first_tournament_player_by_rank
        last_player = screen_set.last_tournament_player_by_rank
        if first_player is not None and last_player is not None:
            return _('Players from #%(first)d to #%(last)d') % {
                'first': first_player.rank,
                'last': last_player.rank,
            }
        return _('Players (none now)')

    @override
    def selection_labels(self, is_team: bool, is_team_matches: bool) -> dict:
        header = (
            _('Team selection (by rank)')
            if is_team
            else _('Player selection (by rank)')
        )
        selection = _name_or_rank_selection_labels(is_team, header)
        selection['first_tooltip'] = (
            _('The rank of the first team to select.')
            if is_team
            else _('The rank of the first player to select.')
        )
        selection['last_tooltip'] = (
            _('The rank of the last team to select.')
            if is_team
            else _('The rank of the last player to select.')
        )
        return selection

    @override
    def range_bounds(
        self, screen_set: 'ScreenSet', abbreviated: bool = False
    ) -> tuple[str, str]:
        dash = '-'
        if screen_set.tournament.is_team_tournament:
            first_standing = screen_set.first_team_standing
            last_standing = screen_set.last_team_standing
            return (
                str(first_standing['rank']) if first_standing is not None else dash,
                str(last_standing['rank']) if last_standing is not None else dash,
            )
        first = screen_set.first_tournament_player_by_rank
        last = screen_set.last_tournament_player_by_rank
        return (
            str(first.rank) if first else dash,
            str(last.rank) if last else dash,
        )


class ImageScreenType(ScreenType):
    @staticmethod
    def static_id() -> str:
        return 'image'

    @staticmethod
    def static_name() -> str:
        return _('Image')

    @property
    def icon_str(self) -> str:
        return 'bi-image'

    @property
    def tooltip_text(self) -> str:
        return _('Image screens show an image (local or remote).')

    @override
    def read_form_data(
        self, data: dict[str, str], errors: dict[str, str], event: 'Event'
    ) -> dict:
        from web.controllers.base_controller import WebContext

        # An uploaded image (base64 data URI in ``background_image_upload``)
        # takes precedence over a typed URL. The value's format/size is
        # validated web-side (network I/O for URLs) once the controller sees it.
        uploaded = WebContext.form_data_to_str(data, 'background_image_upload', '')
        url = WebContext.form_data_to_str(data, 'background_image', '')
        values: dict = {'background_image': uploaded or url}
        if not WebContext.form_data_to_bool(data, 'background_color_checkbox'):
            field = 'background_color'
            try:
                values['background_color'] = WebContext.form_data_to_rgb(data, field)
            except ValueError:
                errors[field] = _(
                    'Invalid color [{color}] ([#RRGGBB] expected).'
                ).format(color={data[field]})
        return values

    @override
    def default_form_data(self, screen: 'Screen') -> dict:
        assert screen.stored_screen is not None
        stored_image = screen.stored_screen.background_image or ''
        is_upload = stored_image.startswith('data:')
        return {
            # Keep an uploaded image in the hidden upload field so the URL box
            # stays clean; a plain URL stays in the URL box.
            'background_image': '' if is_upload else stored_image,
            'background_image_upload': stored_image if is_upload else '',
            'background_color': screen.background_color,
        }

    @override
    def default_screen_name(self, screen: 'Screen') -> str:
        return _('Image')

    @property
    @override
    def families_allowed(self) -> bool:
        return False

    @property
    @override
    def content_template(self) -> str | None:
        return '/user/screen/image_content.html'

    @property
    @override
    def form_template(self) -> str | None:
        return '/admin/screens/forms/image_form.html'

    @property
    @override
    def has_config_fields(self) -> bool:
        return False

    @property
    @override
    def card_config_template(self) -> str | None:
        return None

    @property
    @override
    def shows_copyright(self) -> bool:
        return False

    @property
    @override
    def card_detail_template(self) -> str | None:
        return '/admin/screens/cards/image_card.html'

    @override
    def card_context(self, screen: 'Screen') -> dict:
        assert screen.stored_screen is not None
        return {
            'image': screen.stored_screen.background_image,
            'image_url': screen.background_url,
            'background_color': screen.background_color,
            'background_color_default': not screen.stored_screen.background_color,
        }

    @override
    def refresh_needed(self, screen: 'Screen', since: datetime) -> bool:
        return False

    @override
    def depends_on_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        return False

    @override
    def relates_to_tournament(self, screen: 'Screen', tournament: 'Tournament') -> bool:
        return False
