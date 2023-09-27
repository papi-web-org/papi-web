from pathlib import Path
import math
from logging import Logger

from common.config_reader import TMP_DIR
from common.logger import get_logger
from database.papi import PapiDatabase, RESULT_STRINGS
from database.papi import TOURNAMENT_PAIRING_HALEY, TOURNAMENT_PAIRING_HALEY_SOFT, TOURNAMENT_PAIRING_SAD
from database.papi import RESULT_NOT_PAIRED, RESULT_LOSS, RESULT_DRAW_OR_BYE_05, \
    RESULT_GAIN, RESULT_FORFEIT_LOSS, RESULT_DOUBLE_FORFEIT, RESULT_EXE_FORFEIT_GAIN_BYE_1
from data.player import COLOR_BLACK, COLOR_WHITE
from common.exception import PapiException
from data.board import Board
from data.player import Player
from data.pairing import Pairing

logger: Logger = get_logger()


class Tournament:
    def __init__(self, tournament_id: str, name: str, file: Path, ffe_id: int | None, ffe_password: str | None,
                 handicap_initial_time: int | None, handicap_increment: int | None,
                 handicap_penalty_step: int | None, handicap_penalty_value: int | None,
                 handicap_min_time: int | None):
        self.__id: str = tournament_id
        self.__name: str = name
        self.__file: Path = file
        self.__ffe_id: int | None = ffe_id
        self.__ffe_password: str | None = ffe_password
        self.__handicap_initial_time: int | None = handicap_initial_time
        self.__handicap_increment: int | None = handicap_increment
        self.__handicap_penalty_step: int | None = handicap_penalty_step
        self.__handicap_penalty_value: int | None = handicap_penalty_value
        self.__handicap_min_time: int | None = handicap_min_time
        self.__papi_database: PapiDatabase = PapiDatabase(self.file)
        self.__rounds: int = 0
        self.__pairing: int = 0
        self.__rating: int = 0
        self.__players_by_id: dict[int, Player] = {}
        self.__current_round: int = 0
        self.__rating_limit1: int = 0
        self.__rating_limit2: int = 0
        self.__boards: list[Board] | None = None
        self.__papi_read = False
        self.__players_by_name: list[Player] | None = None
        self.__players_by_rating: list[Player] | None = None

    @property
    def id(self) -> str:
        return self.__id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def file(self) -> Path:
        return self.__file

    @property
    def ffe_id(self) -> int | None:
        return self.__ffe_id

    @property
    def ffe_password(self) -> str | None:
        return self.__ffe_password

    @property
    def ffe_upload_marker(self) -> Path:
        return Path(TMP_DIR, str(self.__ffe_id) + '.ffe_upload')

    @property
    def handicap(self) -> bool:
        return self.__handicap_initial_time is not None

    @property
    def handicap_initial_time(self) -> int | None:
        return self.__handicap_initial_time

    @property
    def handicap_increment(self) -> int | None:
        return self.__handicap_increment

    @property
    def handicap_penalty_step(self) -> int | None:
        return self.__handicap_penalty_step

    @property
    def handicap_penalty_value(self) -> int | None:
        return self.__handicap_penalty_value

    @property
    def handicap_min_time(self) -> int | None:
        return self.__handicap_min_time

    @property
    def rounds(self) -> int:
        self.read_papi()
        return self.__rounds

    @property
    def pairing(self) -> int:
        self.read_papi()
        return self.__pairing

    @property
    def rating(self) -> int:
        self.read_papi()
        return self.__rating

    @property
    def rating_limit1(self) -> int:
        self.read_papi()
        return self.__rating_limit1

    @property
    def rating_limit2(self) -> int:
        self.read_papi()
        return self.__rating_limit2

    @property
    def players_by_id(self) -> dict[int, Player]:
        self.read_papi()
        return self.__players_by_id

    @property
    def players_by_name(self) -> list[Player]:
        if self.__players_by_name is None:
            players: list[Player] = list(self.players_by_id.values())[1:]
            self.__players_by_name = sorted(
                players, key=lambda player: player.last_name + ' ' + player.first_name)
        return self.__players_by_name

    @property
    def players_by_rating(self) -> list[Player]:
        if self.__players_by_rating is None:
            players: list[Player] = list(self.players_by_id.values())[1:]
            self.__players_by_rating = sorted(
                players, key=lambda player: (str(9999 - player.rating) + player.last_name + ' ' + player.first_name))
        return self.__players_by_rating

    @property
    def current_round(self) -> int | None:
        self.read_papi()
        return self.__current_round

    @property
    def boards(self) -> list[Board] | None:
        self.read_papi()
        return self.__boards

    @property
    def print_real_points(self) -> bool:
        if self.current_round is None:
            return False
        elif self.pairing == TOURNAMENT_PAIRING_HALEY:
            return self.current_round <= 2
        elif self.pairing == TOURNAMENT_PAIRING_HALEY_SOFT:
            return self.current_round <= 2
        elif self.pairing == TOURNAMENT_PAIRING_SAD and self.rounds is not None:
            return self.current_round <= self.rounds - 2
        else:
            return False

    def read_papi(self):
        if self.__papi_read:
            return
        if self.file:
            (
                self.__rounds,
                self.__pairing,
                self.__rating,
                self.__rating_limit1,
                self.__rating_limit2
            ) = self.__papi_database.read_info()
            self.__players_by_id = self.__papi_database.read_players(self.__rating, self.__rounds)
            self.__papi_database.close()
        self.__papi_read = True
        self.__calculate_current_round()
        self.__calculate_points()
        self.__build_boards()

    def __calculate_current_round(self):
        round_infos: dict[int, dict[str, bool]] = {}
        for round in range(1, self.rounds + 1):
            round_infos[round] = {
                'pairings_found': False,
                'results_missing': False,
            }
            for player in self.players_by_id.values():
                if player.id != 1:
                    pairing: Pairing = player.pairings[round]
                    if pairing.color in ['W', 'B', ]:
                        round_infos[round]['pairings_found'] = True
                    if pairing.result == 0 and pairing.opponent_id is not None:
                        round_infos[round]['results_missing'] = True
                    if round_infos[round]['pairings_found'] and round_infos[round]['results_missing']:
                        break
        # looking for rounds with pairings
        paired_rounds: list[int] = []
        for round in range(1, self.__rounds + 1):
            if round_infos[round]['pairings_found']:
                paired_rounds.append(round)
        # the current round is the first one with pairings and no missing result
        if paired_rounds:
            for round in paired_rounds:
                if round_infos[round]['results_missing']:
                    self.__current_round = round
                    break
            if self.current_round == 0:
                self.__current_round = paired_rounds[-1]

    def __calculate_points(self):
        previous_rounds: list[int] = list(range(1, self.__current_round))
        for player in self.players_by_id.values():
            if player.id != 1:
                # real points
                player.set_points(0.0)
                for round in previous_rounds:
                    result = player.pairings[round].result
                    if result == RESULT_NOT_PAIRED:
                        pass
                    elif result == RESULT_LOSS:
                        pass
                    elif result == RESULT_DRAW_OR_BYE_05:
                        player.add_points(0.5)
                    elif result == RESULT_GAIN:
                        player.add_points(1.0)
                    elif result == RESULT_FORFEIT_LOSS:
                        pass
                    elif result == RESULT_DOUBLE_FORFEIT:
                        pass
                    elif result == RESULT_EXE_FORFEIT_GAIN_BYE_1:
                        player.add_points(1.0)
                    else:
                        raise PapiException('invalid result :-(')
                # virtual points
                player.set_vpoints(0.0)
                if self.pairing == TOURNAMENT_PAIRING_HALEY:
                    if self.current_round <= 2:
                        if player.rating >= self.__rating_limit1:
                            player.add_vpoints(1.0)
                elif self.pairing == TOURNAMENT_PAIRING_HALEY_SOFT:
                    if self.current_round <= 2:
                        if player.rating >= self.__rating_limit1:
                            player.add_vpoints(1.0)
                        else:
                            if self.current_round == 2:
                                player.add_vpoints(0.5)
                elif self.pairing == TOURNAMENT_PAIRING_SAD:
                    # A l'appariement de l'avant-dernière ronde, les points fictifs sont retirés et le système
                    # devient un système Suisse intégral.
                    if self.current_round <= self.rounds - 2:
                        # En début de tournoi, les joueurs du groupe A ont deux points fictifs (PF = 2), ceux
                        # du groupe B un point fictif (PF = 1), ceux du groupe C aucun point fictif (PF = 0)
                        if player.rating >= self.__rating_limit1:
                            player.add_vpoints(2.0)
                        elif player.rating >= self.__rating_limit2:
                            player.add_vpoints(1.0)
                        if player.rating < self.__rating_limit1:
                            # Lorsqu'un joueur des groupes B ou C marque sur l'échiquier au moins 1,5 point,
                            # son capital fictif augmente de 0,5 point.
                            if player.points >= 1.5:
                                player.add_vpoints(0.5)
                            # Lorsque ce joueur marque sur l'échiquier son troisième point, son capital fictif
                            # augmente une nouvelle fois de 0,5 point.
                            if player.points >= 3:
                                player.add_vpoints(0.5)
                            if player.rating < self.__rating_limit2:
                                # Lorsqu'un joueur du groupe C marque sur l'échiquier au moins 4,5 points, son
                                # capital fictif augmente pour la troisième fois de 0,5 point.
                                if player.points >= 4.5:
                                    player.add_vpoints(0.5)
                            if player.points >= 0.5 * self.rounds:
                                player.set_vpoints(2)
                player.add_vpoints(player.points)

    def __build_boards(self):
        if not self.current_round:
            return
        self.__boards = []
        for player in self.players_by_id.values():
            opponent_id = player.pairings[self.current_round].opponent_id
            if opponent_id in self.players_by_id:
                player_board: Board | None = None
                for board_number in range(len(self.boards)):
                    board = self.boards[board_number]
                    if board.white_player is not None and board.white_player.id == opponent_id:
                        player_board = board
                        player_board.set_black_player(player)
                        break
                    elif board.black_player is not None and board.black_player.id == opponent_id:
                        player_board = board
                        player_board.set_white_player(player)
                        break
                if player_board is None:
                    if player.pairings[self.current_round].color == 'W':
                        self.boards.append(Board(white_player=player))
                    else:
                        self.boards.append(Board(black_player=player))
        # sort the boards
        self.__boards = sorted(self.boards, reverse=True)
        id: int = 1
        for board in self.boards:
            board.set_id(id)
            number: int = id
            if board.white_player.fixed:
                number = board.white_player.fixed
            elif board.black_player.fixed:
                number = board.black_player.fixed
            board.set_number(number)
            board.white_player.set_board_id(id)
            board.white_player.set_board_number(number)
            board.white_player.set_color(COLOR_WHITE)
            board.black_player.set_board_id(id)
            board.black_player.set_board_number(number)
            board.black_player.set_color(COLOR_BLACK)
            board.set_result(board.white_player.pairings[self.current_round].result)
            if self.handicap:
                strong_player: Player
                weak_player: Player
                if board.white_player.rating > board.black_player.rating:
                    strong_player = board.white_player
                    weak_player = board.black_player
                else:
                    strong_player = board.black_player
                    weak_player = board.white_player
                weak_time = self.handicap_initial_time
                rating_diff = strong_player.rating - weak_player.rating
                penalties = math.floor(rating_diff / self.handicap_penalty_step)
                strong_time = max(weak_time - penalties * self.handicap_penalty_value, self.handicap_min_time)
                strong_player.set_handicap(
                    strong_time, self.handicap_increment, strong_time != self.handicap_initial_time)
                weak_player.set_handicap(weak_time, self.handicap_increment, False)
            id += 1

    def add_result(self, board: Board, white_result: int):
        black_result: int = {
            RESULT_LOSS: RESULT_GAIN,
            RESULT_DRAW_OR_BYE_05: RESULT_DRAW_OR_BYE_05,
            RESULT_GAIN: RESULT_LOSS,
        }[white_result]
        self.__papi_database.add_result(board.white_player.id, self.current_round, white_result)
        self.__papi_database.add_result(board.black_player.id, self.current_round, black_result)
        self.__papi_database.close()
        logger.info(f'Added result: {self.id} {self.current_round}.{board.id} '
                    f'{board.white_player.last_name} {board.white_player.first_name} {board.white_player.rating} '
                    f'{RESULT_STRINGS[white_result]} '
                    f'{board.black_player.last_name} {board.black_player.first_name} {board.black_player.rating}')
