from logging import Logger
from operator import attrgetter
from pathlib import Path

from common.config_reader import TMP_DIR
from common.logger import get_logger
from data.board import Board
from data.player import Player
from data.util import Color
from data.util import TournamentPairing, Result
from database.papi import PapiDatabase

logger: Logger = get_logger()


class Tournament:
    def __init__(self, tournament_id: str, name: str, file: Path, ffe_id: int | None, ffe_password: str | None,
                 handicap_initial_time: int | None, handicap_increment: int | None,
                 handicap_penalty_step: int | None, handicap_penalty_value: int | None,
                 handicap_min_time: int | None):
        self.tournament_id: str = tournament_id
        self.name: str = name
        self.file: Path = file
        self.ffe_id: int | None = ffe_id
        self.ffe_password: str | None = ffe_password
        self.handicap_initial_time: int | None = handicap_initial_time
        self.handicap_increment: int | None = handicap_increment
        self.handicap_penalty_step: int | None = handicap_penalty_step
        self.handicap_penalty_value: int | None = handicap_penalty_value
        self.handicap_min_time: int | None = handicap_min_time
        self.papi_database: PapiDatabase = PapiDatabase(self.file)
        self._rounds: int = 0
        self._pairing: TournamentPairing = TournamentPairing.Standard
        self._rating: int = 0
        self._players_by_id: dict[int, Player] = {}
        self._current_round: int = 0
        self._rating_limit1: int = 0
        self._rating_limit2: int = 0
        self._boards: list[Board] | None = None
        self._papi_read = False
        self._players_by_name: list[Player] | None = None
        self._players_by_rating: list[Player] | None = None

    @property
    def id(self) -> str:
        return self.tournament_id

    @property
    def ffe_upload_marker(self) -> Path:
        return TMP_DIR / f'{self.ffe_id}.ffe_upload'

    @property
    def handicap(self) -> bool:
        return self.handicap_initial_time is not None

    @property
    def rounds(self) -> int:
        self.read_papi()
        return self._rounds

    @property
    def pairing(self) -> TournamentPairing:
        self.read_papi()
        return self._pairing

    @property
    def rating(self) -> int:
        self.read_papi()
        return self._rating

    @property
    def rating_limit1(self) -> int:
        self.read_papi()
        return self._rating_limit1

    @property
    def rating_limit2(self) -> int:
        self.read_papi()
        return self._rating_limit2

    @property
    def players_by_id(self) -> dict[int, Player]:
        self.read_papi()
        return self._players_by_id

    @property
    def players_by_name(self) -> list[Player]:
        if self._players_by_name is None:
            players: list[Player] = list(self.players_by_id.values())[1:]
            self._players_by_name = sorted(
                players, key=lambda player: (player.last_name, player.first_name))
        return self._players_by_name

    @property
    def players_by_rating(self) -> list[Player]:
        if self._players_by_rating is None:
            players: list[Player] = list(self._players_by_id.values())[1:]
            self._players_by_rating = sorted(
                players, key=lambda player: (-player.rating, player.last_name, player.first_name))
        return self._players_by_rating

    @property
    def current_round(self) -> int | None:
        self.read_papi()
        return self._current_round

    @property
    def boards(self) -> list[Board] | None:
        self.read_papi()
        return self._boards

    @property
    def print_real_points(self) -> bool:
        match self._pairing:
            case _ if self._current_round is None:
                return False
            case TournamentPairing.Haley | TournamentPairing.HaleySoft:
                return self._current_round <= 2
            case TournamentPairing.SAD if self._rounds is not None:
                return self._current_round <= self._rounds - 2
            case _:
                return False

    def read_papi(self):
        if self._papi_read:
            return
        if self.file:
            (
                self._rounds,
                self._pairing,
                self._rating,
                self._rating_limit1,
                self._rating_limit2
            ) = self.papi_database.read_info()
            self._players_by_id = self.papi_database.read_players(self._rating, self._rounds)
            self.papi_database.close()
        self._papi_read = True
        self._calculate_current_round()
        self._calculate_points()
        self._build_boards()

    def _calculate_current_round(self):
        round_infos: dict[int, dict[str, bool]] = {}
        paired_rounds: list[int] = []
        for round in range(1, self._rounds + 1):
            round_infos[round] = {
                'pairings_found': False,
                'results_missing': False,
            }
            for player in self._players_by_id.values():
                if player.id != 1:
                    color, opponent_id, result = player.pairings[round]
                    if color in ['W', 'B', ]:
                        round_infos[round]['pairings_found'] = True
                        paired_rounds.append(round)
                    # NOTE(Amaras) Why is it called RESULT_NOT_PAIRED if it also
                    # represents a missing result?
                    if result == Result.NotPaired and opponent_id is not None:
                        round_infos[round]['results_missing'] = True
                    if round_infos[round]['pairings_found'] and round_infos[round]['results_missing']:
                        break
        # the current round is the first one with pairings and no missing result
        if paired_rounds:
            for round in paired_rounds:
                if round_infos[round]['results_missing']:
                    self._current_round = round
                    break
            if self._current_round == 0:
                self._current_round = paired_rounds[-1]

    def _calculate_points(self):
        # TODO(Amaras) WTF IS THIS A LIST WHEN A RANGE OBJECT IS GOOD ENOUGH?
        # DONE(pascalaubry) Because player ids are not reused after player deletion, please remove if OK
        for player in self._players_by_id.values():
            if player.id == 1:
                continue
            # real points
            player.compute_points(self._current_round)
            # virtual points
            player.vpoints = 0.0
            if self._pairing == TournamentPairing.Haley:
                if self._current_round <= 2:
                    if player.rating >= self._rating_limit1:
                        player.add_vpoints(1.0)
            elif self._pairing == TournamentPairing.HaleySoft:
                # TODO(Amaras) Is this right?
                # The code implies this acceleration scheme:
                # Round 1: All players above rating_limit1 get 1 vpoint
                # Round 2: All players above rating_limit1 get 1 vpoint
                # Round 2: All other players get .5 vpoints
                # DONE(pascalaubry) Checked (bottom of page #138 on
                # https://dna.ffechecs.fr/wp-content/uploads/sites/2/2023/10/Livre-arbitre-octobre-2023.pdf),
                # please remove if OK
                if self._current_round <= 2:
                    if player.rating >= self.rating_limit1:
                        player.add_vpoints(1.0)
                    else:
                        if self._current_round == 2:
                            player.add_vpoints(0.5)
            elif self._pairing == TournamentPairing.SAD:
                # À l'appariement de l'avant-dernière ronde, les points
                # fictifs sont retirés et le système devient un système
                # Suisse intégral.
                if self._current_round <= self._rounds - 2:
                    # En début de tournoi, les joueurs du groupe A ont
                    # deux points fictifs (PF = 2), ceux du groupe B un
                    # point fictif (PF = 1), ceux du groupe C aucun point
                    # fictif (PF = 0)
                    if player.rating >= self._rating_limit1:
                        player.add_vpoints(2.0)
                    elif player.rating >= self._rating_limit2:
                        player.add_vpoints(1.0)
                    if player.rating < self._rating_limit1:
                        # Lorsqu'un joueur des groupes B ou C marque
                        # sur l'échiquier au moins 1,5 point, son capital
                        # fictif augmente de 0,5 point.
                        if player.points >= 1.5:
                            player.add_vpoints(0.5)
                        # Lorsque ce joueur marque sur l'échiquier son
                        # troisième point, son capital fictif augmente une
                        # nouvelle fois de 0,5 point.
                        if player.points >= 3:
                            player.add_vpoints(0.5)
                        if player.rating < self._rating_limit2:
                            # Lorsqu'un joueur du groupe C marque sur
                            # l'échiquier au moins 4,5 points, son capital
                            # fictif augmente pour la troisième fois de
                            # 0,5 point.
                            if player.points >= 4.5:
                                player.add_vpoints(0.5)

                            # Lorsqu'un joueur du groupe C marque sur
                            # l'échiquier au moins 6 points, son capital
                            # fictif augmente pour la dernière fois de
                            # 0,5 points (maximum de 2 points fictifs)
                            if player.points >= 6:
                                player.add_vpoints(0.5)

                        # Le capital fictif est automatiquement porté à 2
                        # points si le joueur a marqué la moitié des points
                        # possibles sur l'échiquier (il est sous-évalué par
                        # le classement ELO)
                        if player.points * 2 >= self._rounds:
                            player.vpoints = 2
            player.add_vpoints(player.points)

    def _build_boards(self):
        if not self._current_round:
            return
        self._boards = []
        for player in self._players_by_id.values():
            opponent_id = player.pairings[self._current_round].opponent_id
            if opponent_id in self._players_by_id:
                player_board: Board | None = None
                for board in self._boards:
                    if board.white_player is not None and board.white_player.id == opponent_id:
                        player_board = board
                        player_board.black_player = player
                        break
                    elif board.black_player is not None and board.black_player.id == opponent_id:
                        player_board = board
                        player_board.white_player = player
                        break
                if player_board is None:
                    if player.pairings[self._current_round].color == Color.White:
                        self._boards.append(Board(white_player=player))
                    else:
                        self._boards.append(Board(black_player=player))
        # sort the boards
        self._boards = sorted(self._boards, reverse=True)
        for index, board in enumerate(self._boards, start=1):
            board.id = index
            number: int = board.white_player.fixed or board.black_player.fixed or index
            board.number = number
            board.white_player.set_board(index, number, Color.White)
            board.black_player.set_board(index, number, Color.Black)
            board.result = board.white_player.pairings[self._current_round].result
            if self.handicap:
                strong_player: Player
                weak_player: Player
                strong_player, weak_player = sorted(
                    (board.white_player, board.black_player),
                    key=attrgetter('rating'),
                    reverse=True
                )
                weak_time = self.handicap_initial_time
                rating_diff = strong_player.rating - weak_player.rating
                penalties = rating_diff // self.handicap_penalty_step
                strong_time = max(
                    weak_time - penalties * self.handicap_penalty_value,
                    self.handicap_min_time
                )
                strong_player.set_handicap(
                    strong_time, self.handicap_increment, penalties > 0)
                weak_player.set_handicap(weak_time, self.handicap_increment, False)

    def add_result(self, board: Board, white_result: Result):
        black_result = Result.opposite_result(white_result)
        self.papi_database.add_result(board.white_player.id, self._current_round, white_result)
        self.papi_database.add_result(board.black_player.id, self._current_round, black_result)
        self.papi_database.close()
        logger.info(f'Added result: {self.id} {self._current_round}.{board.id} '
                    f'{board.white_player.last_name} '
                    f'{board.white_player.first_name} '
                    f'{board.white_player.rating} '
                    f'{white_result} '
                    f'{board.black_player.last_name} '
                    f'{board.black_player.first_name} '
                    f'{board.black_player.rating}')
