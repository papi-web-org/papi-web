import logging
from datetime import date

from common.i18n import _
from common.logger import get_logger

from plugins.manager import plugin_manager

from data.board import Board
from data.event import Event
from data.player import TournamentPlayer
from data.tournament import Tournament

logger: logging.Logger = get_logger()


class PlaceCardPlayer:
    """A utility class to pass unmodifiable players' data to print documents."""

    def __init__(
        self,
        tournament_player: TournamentPlayer | None = None,
        color: str = '',
    ):
        self.rating: str = ''
        self.rating_type: str = ''
        self.full_name: str = ''
        self.first_name: str = ''
        self.last_name: str = ''
        self.year_of_birth: str = ''
        self.gender: str = ''
        self.title: str = ''
        self.federation: str = ''
        self.club: str = ''
        self.category: str = ''
        self.color: str = ''
        # Swatch colours for the colour marker: the player's actual
        # piece colour (the marker text may be a seat letter on team
        # cards, where colours alternate from board to board).
        self.color_background: str = '#fff'
        self.color_text: str = '#000'
        self.team_name: str = ''
        if tournament_player:
            team = tournament_player.team
            if team is not None:
                self.team_name = team.name
            if tournament_player.rating:
                self.rating = str(tournament_player.rating)
            self.rating_type = tournament_player.rating_type.short_name
            self.full_name = tournament_player.full_name
            self.first_name = tournament_player.first_name
            self.last_name = tournament_player.last_name
            if tournament_player.year_of_birth:
                self.year_of_birth = str(tournament_player.year_of_birth)
            self.gender = tournament_player.gender.short_name
            self.title = tournament_player.display_title
            self.federation = tournament_player.federation.name
            self.club = tournament_player.club.name
            self.category = tournament_player.category.name
            self.color = color
            plugin_manager.hook_for_event(
                tournament_player.event, 'augment_place_card_player'
            )(tournament_player=tournament_player, place_card_player=self)

    @property
    def federation_flag(self) -> str:
        # The flag itself is a CSS background-image on this element; the img needs
        # a (transparent 1x1) src so the browser does not draw a broken-image
        # icon over the flag.
        if not self.federation:
            return ''
        blank = (
            'data:image/gif;base64,'
            'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
        )
        return f'<img class="federation-flag {self.federation}" src="{blank}" alt="" />'


class PlaceCardBoard:
    """A utility class to pass unmodifiable boards' data to print documents."""

    def __init__(
        self,
        number: int,
        table: int | None = None,
    ):
        self.number: int = number
        # Team events: the match table the board belongs to. Empty for
        # individual events.
        self.table: int | str = table if table is not None else ''


class PlaceCardTeam:
    """A utility class to pass unmodifiable teams' data to print documents."""

    def __init__(
        self,
        name: str = '',
        captain: str = '',
    ):
        self.name: str = name
        self.captain: str = captain


class PlaceCardPairing:
    """A utility class to pass unmodifiable pairings' data to print documents."""

    def __init__(
        self,
        board: Board | None = None,
    ):
        self.number: int
        self.white_player: PlaceCardPlayer
        self.black_player: PlaceCardPlayer
        if board:
            self.number = board.number
            team_board = board.team_board
            if team_board is not None:
                # Team events: the card shows the table seats — team A's
                # player on the left, team B's on the right, like the
                # pairings table. The colour marker shows each player's
                # actual colour (colours alternate from board to board).
                w_team_id, _b_team_id = team_board.board_team_ids(board)
                white_is_team_a = w_team_id == team_board.stored_team_board.team_a_id
                left_tp = (
                    board.optional_white_tournament_player
                    if white_is_team_a
                    else board.black_tournament_player
                )
                right_tp = (
                    board.black_tournament_player
                    if white_is_team_a
                    else board.optional_white_tournament_player
                )
                white_marker = _('W *** WHITE COLOR FOR PLACE CARDS')
                black_marker = _('B *** BLACK COLOR FOR PLACE CARDS')
                self.white_player = PlaceCardPlayer(
                    left_tp,
                    color=white_marker if white_is_team_a else black_marker,
                )
                self.black_player = PlaceCardPlayer(
                    right_tp,
                    color=black_marker if white_is_team_a else white_marker,
                )
                self.white_player.color_background = (
                    '#fff' if white_is_team_a else '#000'
                )
                self.white_player.color_text = '#000' if white_is_team_a else '#fff'
                self.black_player.color_background = (
                    '#000' if white_is_team_a else '#fff'
                )
                self.black_player.color_text = '#fff' if white_is_team_a else '#000'
            else:
                self.white_player = PlaceCardPlayer(
                    board.optional_white_tournament_player,
                    color=_('W *** WHITE COLOR FOR PLACE CARDS'),
                )
                self.black_player = PlaceCardPlayer(
                    board.black_tournament_player,
                    color=_('B *** BLACK COLOR FOR PLACE CARDS'),
                )
                self.black_player.color_background = '#000'
                self.black_player.color_text = '#fff'
        else:
            self.number = 0
            self.white_player = PlaceCardPlayer()
            self.black_player = PlaceCardPlayer()


class PlaceCardDate:
    """A utility class to pass unmodifiable dates to print documents."""

    def __init__(self, date_: date):
        self.year: int = date_.year
        self.month: int = date_.month
        self.day: int = date_.day


class PlaceCardTournament:
    """A utility class to pass unmodifiable tournaments' data to print documents."""

    def __init__(
        self,
        tournament: Tournament | None = None,
    ):
        self.name: str
        self.start: PlaceCardDate
        self.stop: PlaceCardDate
        if tournament:
            self.name = tournament.name
            self.start = PlaceCardDate(tournament.stop_date)
            self.stop = PlaceCardDate(tournament.stop_date)
        else:
            self.name = _('Tournament name')
            today = date.today()
            self.start = PlaceCardDate(today)
            self.stop = PlaceCardDate(today)


class PlaceCardEvent:
    """A utility class to pass unmodifiable tournaments' data to print documents."""

    def __init__(
        self,
        event: Event | None = None,
    ):
        self.name: str
        self.start: PlaceCardDate
        self.stop: PlaceCardDate
        if event:
            self.name = event.name
            self.start = PlaceCardDate(event.start_date)
            self.stop = PlaceCardDate(event.stop_date)
        else:
            self.name = _('Event name')
            today = date.today()
            self.start = PlaceCardDate(today)
            self.stop = PlaceCardDate(today)
