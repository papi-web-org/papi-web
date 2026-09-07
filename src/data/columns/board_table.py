from abc import ABC, abstractmethod
from typing import Any

from markupsafe import escape

from common.i18n import _
from data.board import Board
from .column import Column, ColumnUsage


def _color_chip(color: str) -> str:
    return f'<span class="board-color-chip {color}"></span>'


class BoardColumn(Column[Board], ABC):
    """Base class for board table columns."""

    def __init__(self, usage: ColumnUsage):
        self.usage = usage

    @property
    def grid_column_template(self) -> str:
        return 'auto'

    @property
    def edit_result_on_click(self) -> bool:
        """Defines if clicking on the cell opens the result modal (if the board is editable)."""
        return True


class NumberColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return _('Bd. *** BOARD NUMBER COLUMN HEADER')

    def get_cell_content(self, board: Board) -> Any:
        if board.fixed_number:
            return (
                f'<span class="border border-dark rounded p-1" '
                f'data-bs-toggle="tooltip" '
                f'data-bs-title="{escape(_("Fixed table"))}">'
                f'{escape(board.number_str)}</span>'
            )
        return board.number_str

    @property
    def is_cell_content_safe(self) -> bool:
        return True

    @property
    def shared_classes(self) -> str:
        return 'text-end'


class WhitePointsColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return _('Pts *** POINTS COLUMN HEADER')

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        return wtp.vpoints_str if wtp else ''

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class WhiteRealPointsColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        return f'[{wtp.points_str}]' if wtp else ''

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class IllegalMovesColumn(BoardColumn, ABC):
    @property
    def header_content(self) -> str:
        return ''

    @property
    def cell_template(self) -> str | None:
        return '/user/screen/sets/board_row_illegal_moves_cell.html'

    @property
    @abstractmethod
    def is_black(self) -> bool:
        """Defines if the column displays the white or black player."""

    @property
    def edit_result_on_click(self) -> bool:
        return False


class WhiteIllegalMovesColumn(IllegalMovesColumn):
    @property
    def is_black(self) -> bool:
        return False


class WhiteTitleColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        return wtp.display_title if wtp else ''


class WhiteNameColumn(BoardColumn):
    @property
    def grid_column_template(self) -> str:
        return '1fr'

    @property
    def header_content(self) -> str:
        return _('White')

    @property
    def is_cell_content_safe(self) -> bool:
        return True

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        name = escape(wtp.full_name) if wtp else ''
        # Inside a team match a colour chip marks each side (the team
        # screens group rows by match, where colours alternate by board).
        if board.team_board is not None:
            return f'{_color_chip("white")}{name}'
        return name

    @property
    def shared_classes(self) -> str:
        return 'text-start'

    def get_cell_classes(self, board: Board) -> str:
        return 'text-start text-nowrap overflow-hidden text-ellipsis'


class WhiteRatingColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        return wtp.rating_str if wtp else ''

    @property
    def shared_classes(self) -> str:
        return 'text-end'


class WhiteFederationColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        wtp = board.optional_white_tournament_player
        return wtp.federation.name if wtp else ''

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class ResultColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return _('Res. *** RESULT COLUMN HEADER')

    def get_cell_content(self, board: Board) -> Any:
        return board.result_str

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class NoResultColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return '\u00a0' * 6

    def get_cell_content(self, board: Board) -> Any:
        return board.result_str if board.exempt else ''


class ScreenResultColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return _('Res. *** RESULT COLUMN HEADER')

    def get_cell_content(self, board: Board) -> Any:
        return board.result_str or _('#{board_number}').format(
            board_number=board.number
        )

    @property
    def shared_classes(self) -> str:
        return 'score text-center'


class BlackIllegalMovesColumn(IllegalMovesColumn):
    @property
    def is_black(self) -> bool:
        return True


class BlackTitleColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        tournament_player = board.black_tournament_player
        if not tournament_player:
            return ''
        return tournament_player.display_title


class BlackNameColumn(BoardColumn):
    @property
    def grid_column_template(self) -> str:
        return '1fr'

    @property
    def header_content(self) -> str:
        return _('Black')

    @property
    def header_classes(self) -> str:
        return 'text-start'

    @property
    def is_cell_content_safe(self) -> bool:
        return True

    def get_cell_content(self, board: Board) -> Any:
        black = board.black_tournament_player
        if black is not None:
            name = escape(black.full_name)
            if board.team_board is not None:
                return f'{_color_chip("black")}{name}'
            return name
        white = board.optional_white_tournament_player
        return escape(white.exempt_str.upper()) if white else ''

    def get_cell_classes(self, board: Board) -> str:
        return 'text-start text-nowrap overflow-hidden text-ellipsis' + (
            ' fst-italic' if board.exempt else ''
        )


class BlackRatingColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        return getattr(board.black_tournament_player, 'rating_str', '')

    @property
    def shared_classes(self) -> str:
        return 'text-end'


class BlackFederationColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        black = board.black_tournament_player
        return black.federation.name if black else ''

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class BlackRealPointsColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return ''

    def get_cell_content(self, board: Board) -> Any:
        real_points = getattr(board.black_tournament_player, 'points_str', '')
        return f'[{real_points}]' if real_points else ''

    @property
    def shared_classes(self) -> str:
        return 'text-center'


class BlackPointsColumn(BoardColumn):
    @property
    def header_content(self) -> str:
        return _('Pts *** POINTS COLUMN HEADER')

    def get_cell_content(self, board: Board) -> Any:
        return getattr(board.black_tournament_player, 'vpoints_str', '')

    @property
    def shared_classes(self) -> str:
        return 'text-center'
