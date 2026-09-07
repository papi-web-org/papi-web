from abc import ABC, abstractmethod
import random
from datetime import datetime
from typing import TYPE_CHECKING

from common.i18n import _
from common.sharly_chess_config import SharlyChessConfig
from data.board import Board
from data.player import Player
from data.print_documents.place_cards.data import (
    PlaceCardPlayer,
    PlaceCardBoard,
    PlaceCardPairing,
    PlaceCardTeam,
)
from data.tournament import Tournament
from utils.entity import IdentifiableEntity
from utils.enum import PlayerRatingType, PlayerGender, PlayerTitle

if TYPE_CHECKING:
    from data.print_documents import PrintOption


class PlaceCardType(IdentifiableEntity, ABC):
    @staticmethod
    @abstractmethod
    def static_singular_name() -> str:
        """Names one card of this type, where static_name() names the document
        ("Player" against "Player Cards")."""
        pass

    @classmethod
    def get_valid_option_ids(cls) -> list[str]:
        return [option.static_id() for option in cls.get_valid_option_types()]

    @staticmethod
    def get_valid_option_types() -> list[type['PrintOption']]:
        """Returns a list of valid options for the place card type."""
        from data.print_documents.options import (
            TournamentPrintOption,
            PlaceCardTemplatePrintOption,
            PlaceCardMirrorPrintOption,
            PlaceCardCropMarksPrintOption,
        )

        return [
            PlaceCardTemplatePrintOption,
            TournamentPrintOption,
            PlaceCardMirrorPrintOption,
            PlaceCardCropMarksPrintOption,
        ]

    @staticmethod
    def get_random_player(
        last_name: str,
        color: str = '',
    ) -> PlaceCardPlayer:
        place_card_player: PlaceCardPlayer = PlaceCardPlayer()
        place_card_player.rating = str(random.randint(1400, 3000))
        place_card_player.rating_type = random.choice(
            [
                PlayerRatingType.FIDE,
                PlayerRatingType.NATIONAL,
                PlayerRatingType.ESTIMATED,
            ]
        ).short_name
        place_card_player.last_name = last_name
        place_card_player.first_name = _('First name')
        place_card_player.full_name = Player.player_full_name(
            place_card_player.first_name,
            place_card_player.last_name,
        )
        year: int = datetime.now().year
        place_card_player.year_of_birth = str(random.randint(year - 100, year - 5))
        place_card_player.gender = PlayerGender(
            random.choice(list(PlayerGender))
        ).short_name
        place_card_player.title = PlayerTitle(
            random.choice(list(PlayerTitle))
        ).short_name
        config = SharlyChessConfig()
        place_card_player.federation = random.choice(list(config.federations.keys()))
        place_card_player.club = _("Player's club")
        place_card_player.category = random.choice(
            config.default_player_category_set.categories
        ).name
        place_card_player.color = color
        return place_card_player

    @classmethod
    def tournament_players(
        cls,
        tournament: Tournament,
        player_ids: list[int] | None = None,
    ) -> list[PlaceCardPlayer]:
        return []

    @classmethod
    def preview_players(
        cls,
    ) -> list[PlaceCardPlayer]:
        return []

    @classmethod
    def boards(
        cls,
        tournament: Tournament,
        board_numbers: set[int] | None = None,
    ) -> list[PlaceCardBoard]:
        return []

    @classmethod
    def preview_boards(
        cls,
    ) -> list[PlaceCardBoard]:
        return []

    @classmethod
    def pairings(
        cls,
        tournament: Tournament,
        round_: int,
        board_numbers: set[int] | None = None,
    ) -> list[PlaceCardPairing]:
        return []

    @classmethod
    def preview_pairings(
        cls,
    ) -> list[PlaceCardPairing]:
        return []

    @classmethod
    def teams(
        cls,
        tournament: Tournament,
    ) -> list[PlaceCardTeam]:
        return []

    @classmethod
    def preview_teams(
        cls,
    ) -> list[PlaceCardTeam]:
        return []

    @classmethod
    def supports_event_type(cls, is_team_event: bool) -> bool:
        return True

    @property
    def mirror_rotate(self) -> bool:
        return True


class PlayerCardType(PlaceCardType):
    @staticmethod
    def static_id() -> str:
        return 'player'

    @staticmethod
    def static_name() -> str:
        return _('Player Cards')

    @staticmethod
    def static_singular_name() -> str:
        return _('Player')

    @staticmethod
    def get_valid_option_types() -> list[type['PrintOption']]:
        from data.print_documents.options import OptionalPlayersPrintOption

        return PlaceCardType.get_valid_option_types() + [
            OptionalPlayersPrintOption,
        ]

    @classmethod
    def tournament_players(
        cls,
        tournament: Tournament,
        player_ids: list[int] | None = None,
    ) -> list[PlaceCardPlayer]:
        if tournament.event.is_team_event:
            # Cards come out grouped by team, in roster order.
            tournament_players = sorted(
                tournament.tournament_players_by_id.values(),
                key=lambda tp: (
                    tp.team.name.lower() if tp.team else '',
                    tp.team_index if tp.team_index is not None else 0,
                ),
            )
        else:
            tournament_players = list(
                tournament.tournament_players_by_starting_rank.values()
            )
        if player_ids:
            tournament_players = [
                tournament_player
                for tournament_player in tournament_players
                if tournament_player.id in player_ids
            ]
        return [PlaceCardPlayer(player) for player in tournament_players]

    @classmethod
    def preview_players(
        cls,
    ) -> list[PlaceCardPlayer]:
        return [
            cls.get_random_player(_("PLAYER'S NAME")),
        ]


class BoardCardType(PlaceCardType):
    @staticmethod
    def static_id() -> str:
        return 'board'

    @staticmethod
    def static_name() -> str:
        return _('Board Cards')

    @staticmethod
    def static_singular_name() -> str:
        return _('Board')

    @staticmethod
    def get_valid_option_types() -> list[type['PrintOption']]:
        from data.print_documents.options import (
            PlaceCardBoardNumbersPrintOption,
        )

        return PlaceCardType.get_valid_option_types() + [
            PlaceCardBoardNumbersPrintOption,
        ]

    @classmethod
    def get_random_board(
        cls,
    ) -> PlaceCardBoard:
        return PlaceCardBoard(random.randint(1, 99))

    @classmethod
    def boards(
        cls,
        tournament: Tournament,
        board_numbers: set[int] | None = None,
        preview: bool = False,
    ) -> list[PlaceCardBoard]:
        if preview:
            return [cls.get_random_board()]
        if tournament.event.is_team_event and tournament.pairing_system.paired_by_team:
            # Team-paired systems: the numbers field selects match
            # TABLES; each table emits one card per board of the match.
            # Flat team systems (fixed tables) keep plain board numbers.
            boards_per_match = tournament.team_player_count or 0
            table_count = len(tournament.teams) // 2
            tables = (
                sorted(board_numbers) if board_numbers else range(1, table_count + 1)
            )
            return [
                PlaceCardBoard(board_number, table=table)
                for table in tables
                for board_number in range(1, boards_per_match + 1)
            ]
        if board_numbers:
            return [PlaceCardBoard(board_number) for board_number in board_numbers]
        return [
            PlaceCardBoard(board_number)
            for board_number in sorted(
                [
                    tournament.first_board_number + number
                    for number in range(tournament.player_count // 2)
                ]
                + [
                    tournament_player.fixed
                    for tournament_player in tournament.tournament_players_by_id.values()
                    if tournament_player.fixed
                ]
            )
        ]

    @classmethod
    def preview_boards(
        cls,
    ) -> list[PlaceCardBoard]:
        return [
            cls.get_random_board(),
        ]


class PairingCardType(PlaceCardType):
    @staticmethod
    def static_id() -> str:
        return 'pairing'

    @staticmethod
    def static_name() -> str:
        return _('Pairing Cards')

    @staticmethod
    def static_singular_name() -> str:
        return _('Pairing')

    @property
    def mirror_rotate(self) -> bool:
        return False

    @staticmethod
    def get_valid_option_types() -> list[type['PrintOption']]:
        from data.print_documents.options import (
            RoundPrintOption,
            PlaceCardBoardNumbersPrintOption,
        )

        return PlaceCardType.get_valid_option_types() + [
            RoundPrintOption,
            PlaceCardBoardNumbersPrintOption,
        ]

    @classmethod
    def get_random_pairing(
        cls,
    ) -> PlaceCardPairing:
        place_card_pairing: PlaceCardPairing = PlaceCardPairing()
        place_card_pairing.number = random.randint(1, 99)
        place_card_pairing.white_player = cls.get_random_player(
            last_name=_('WHITE PLAYER'),
            color=_('W *** WHITE COLOR FOR PLACE CARDS'),
        )
        place_card_pairing.white_player.color_background = '#fff'
        place_card_pairing.white_player.color_text = '#000'
        place_card_pairing.black_player = cls.get_random_player(
            last_name=_('BLACK PLAYER'),
            color=_('B *** BLACK COLOR FOR PLACE CARDS'),
        )
        place_card_pairing.black_player.color_background = '#000'
        place_card_pairing.black_player.color_text = '#fff'
        return place_card_pairing

    @classmethod
    def pairings(
        cls,
        tournament: Tournament,
        round_: int,
        board_numbers: set[int] | None = None,
    ) -> list[PlaceCardPairing]:
        boards: list[Board] = tournament.get_round_boards(round_)
        if tournament.event.is_team_event and tournament.pairing_system.paired_by_team:
            # Team events: cards come out per match table, boards in
            # match order; the numbers field selects tables.
            def table_number(board: Board) -> int:
                team_board = board.team_board
                return team_board.display_number or 0 if team_board is not None else 0

            boards = sorted(boards, key=lambda b: (table_number(b), b.index))
            if board_numbers:
                boards = [
                    board for board in boards if table_number(board) in board_numbers
                ]
        elif board_numbers:
            boards = [board for board in boards if board.number in board_numbers]
        return [PlaceCardPairing(board) for board in boards]

    @classmethod
    def preview_pairings(
        cls,
    ) -> list[PlaceCardPairing]:
        return [
            cls.get_random_pairing(),
        ]


class TeamCardType(PlaceCardType):
    @staticmethod
    def static_id() -> str:
        return 'team'

    @staticmethod
    def static_name() -> str:
        return _('Team Cards')

    @staticmethod
    def static_singular_name() -> str:
        return _('Team')

    @classmethod
    def supports_event_type(cls, is_team_event: bool) -> bool:
        return is_team_event

    @classmethod
    def teams(
        cls,
        tournament: Tournament,
    ) -> list[PlaceCardTeam]:
        return [
            PlaceCardTeam(name=team.name, captain=team.captain_display_name or '')
            for team in sorted(tournament.teams, key=lambda t: t.name.lower())
        ]

    @classmethod
    def preview_teams(
        cls,
    ) -> list[PlaceCardTeam]:
        return [
            PlaceCardTeam(name=_("TEAM'S NAME"), captain=_("Captain's name")),
        ]
