import time
from collections import Counter
from functools import cached_property
from logging import Logger
from operator import attrgetter
from pathlib import Path
from typing import TYPE_CHECKING

from common import format_timestamp_date_time
from common.papi_web_config import PapiWebConfig

if TYPE_CHECKING:
    from data.event import Event
    from data.screen import Screen
    from data.family import Family

from common.logger import get_logger
from data.board import Board
from data.chessevent import ChessEvent
from data.chessevent_tournament import ChessEventTournament
from data.player import Player
from data.util import Color, NeedsUpload, TournamentRating
from data.util import TournamentPairing, Result
from database.papi import PapiDatabase
from database.sqlite import EventDatabase
from database.store import StoredTournament

logger: Logger = get_logger()


class Tournament:
    """A data wrapper around a stored tournament."""
    def __init__(self, event: 'Event', stored_tournament: StoredTournament, ):
        self.event: 'Event' = event
        self.stored_tournament: StoredTournament = stored_tournament
        if not stored_tournament.path:
            self.event.add_debug(
                f'pas de répertoire défini pour le fichier Papi, par défaut [{self.path}]', tournament=self)
        if not self.path.exists():
            self.event.add_warning(f'le répertoire [{self.path}] n\'existe pas', tournament=self)
        elif not self.path.is_dir():
            self.event.add_error(f'[{self.path}] n\'est pas un répertoire', tournament=self)
        if not self.stored_tournament.filename:
            self.event.add_info(
                f'le nom du fichier Papi n\'est pas défini, par défaut [{self.filename}]', tournament=self)
        if not self.stored_tournament.ffe_id or not self.stored_tournament.ffe_password:
            self.event.add_info(
                f'le numéro d\'homologation et le mot de passe de connexion au site fédéral sont nécessaires '
                f'pour les opérations sur le site fédéral, elles ne seront pas disponibles',
                tournament=self)
        if not self.chessevent:
            self.event.add_info(
                f'la connexion à la plateforme ChessEvent n\'est pas définie', tournament=self)
        if self.chessevent and not self.stored_tournament.chessevent_tournament_name:
            self.event.add_warning(
                f'le nom du tournoi [{self.uniq_id}] n\'est pas renseigné, la connexion à la plateforme '
                f'ChessEvent ne sera pas fonctionnelle', tournament=self)
        self._rounds: int = 0
        self._pairing: TournamentPairing | None = None
        self._rating: TournamentRating | None = None
        self._players_by_id: dict[int, Player] = {}
        self._current_round: int = 0
        self._playing: bool = False
        self._rating_limit1: int = 0
        self._rating_limit2: int = 0
        self._boards: list[Board] | None = None
        self._unpaired_players: list[Player] | None = None
        self._papi_read = False
        self._players_by_name: list[Player] | None = None

    @property
    def id(self) -> int:
        return self.stored_tournament.id

    @property
    def uniq_id(self) -> str:
        return self.stored_tournament.uniq_id

    @property
    def name(self) -> str:
        return self.stored_tournament.name if self.stored_tournament.name else self.uniq_id

    @property
    def path(self) -> Path:
        return Path(self.stored_tournament.path) if self.stored_tournament.path else self.event.path

    @property
    def filename(self) -> str:
        if self.stored_tournament.filename:
            return self.stored_tournament.filename
        if self.stored_tournament.ffe_id:
            return str(self.stored_tournament.ffe_id)
        return self.uniq_id

    @property
    def file(self) -> Path:
        return self.path / f'{self.filename}.{PapiWebConfig.papi_ext}'

    @property
    def file_exists(self) -> bool:
        return self.file.exists()

    @property
    def ffe_id(self) -> int | None:
        return self.stored_tournament.ffe_id

    @property
    def ffe_password(self) -> str | None:
        return self.stored_tournament.ffe_password if self.ffe_id else None

    @property
    def shadowed_ffe_password(self) -> str | None:
        return f'{self.ffe_password[:4] + "*" * (len(self.ffe_password) - 4)}' if self.ffe_password else None

    @property
    def time_control_initial_time(self) -> int | None:
        return self.stored_tournament.time_control_initial_time

    @property
    def time_control_increment(self) -> int | None:
        return self.stored_tournament.time_control_increment

    @property
    def time_control_handicap_penalty_value(self) -> int | None:
        return self.stored_tournament.time_control_handicap_penalty_value

    @property
    def time_control_handicap_penalty_step(self) -> int | None:
        return self.stored_tournament.time_control_handicap_penalty_step

    @property
    def time_control_handicap_min_time(self) -> int | None:
        return self.stored_tournament.time_control_handicap_min_time

    @property
    def chessevent(self) -> ChessEvent | None:
        if self.stored_tournament.chessevent_id is None:
            return None
        return self.event.chessevents_by_id[self.stored_tournament.chessevent_id]

    @property
    def chessevent_tournament_name(self) -> str | None:
        if self.chessevent is None:
            return None
        return self.stored_tournament.chessevent_tournament_name

    @property
    def record_illegal_moves(self) -> int:
        if self.stored_tournament.record_illegal_moves is not None:
            return self.stored_tournament.record_illegal_moves
        return self.event.record_illegal_moves

    @property
    def last_update(self) -> float:
        return self.stored_tournament.last_update

    @property
    def last_update_str(self) -> str:
        return format_timestamp_date_time(self.last_update)

    @property
    def last_illegal_move_update(self) -> float:
        return self.stored_tournament.last_illegal_move_update

    @property
    def last_result_update(self) -> float:
        return self.stored_tournament.last_result_update

    @property
    def last_check_in_update(self) -> float:
        return self.stored_tournament.last_check_in_update

    @property
    def last_ffe_upload(self) -> float:
        return self.stored_tournament.last_ffe_upload

    @property
    def last_chessevent_download_md5(self) -> str:
        return self.stored_tournament.last_chessevent_download_md5

    @property
    def download_allowed(self) -> bool:
        return self.file_exists

    @property
    def handicap(self) -> bool:
        return self.time_control_handicap_penalty_value is not None

    @property
    def skipped_rounds_as_dict(self) -> dict[int, dict[int, float]]:
        """A dictionary mapping player ids to a dictionary of rounds to results."""
        # dict[papi_player_id: int, dict[round: int, score: float]]
        skipped_rounds_dict: dict[int, dict[int, float]] = {}
        for skipped_round in self.stored_tournament.stored_skipped_rounds:
            if skipped_round.papi_player_id not in skipped_rounds_dict:
                skipped_rounds_dict[skipped_round.papi_player_id] = {}
            skipped_rounds_dict[skipped_round.papi_player_id][skipped_round.round] = skipped_round.score
        return skipped_rounds_dict

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

    @cached_property
    def players_by_name_with_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            self._players_by_name = sorted(
                list(self.players_by_id.values())[1:], key=lambda player: (player.last_name, player.first_name))
        return self._players_by_name

    @cached_property
    def players_by_name_without_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            self._players_by_name = sorted([
                player for player in list(self.players_by_id.values())[1:]
                if not self.current_round or player.board_id
            ], key=lambda p: (p.last_name, p.first_name))
        return self._players_by_name

    @property
    def current_round(self) -> int | None:
        self.read_papi()
        return self._current_round

    @property
    def playing(self) -> bool:
        self.read_papi()
        return self._playing

    @property
    def boards(self) -> list[Board] | None:
        self.read_papi()
        return self._boards

    @property
    def unpaired_players(self) -> list[Player] | None:
        self.read_papi()
        return self._unpaired_players

    @cached_property
    def dependent_families(self) -> list['Family']:
        return [family for family in self.event.families_by_id.values() if family.tournament.id == self.id]

    @cached_property
    def dependent_screens(self) -> list['Screen']:
        dependent_screens = []
        for screen in self.event.basic_screens_by_id.values():
            for screen_set in screen.screen_sets_sorted_by_order:
                if screen_set.tournament.id == self.id:
                    dependent_screens.append(screen)
        return dependent_screens

    @property
    def print_real_points(self) -> bool:
        match self._pairing:
            case _ if self._current_round is None:
                return False
            case TournamentPairing.HALEY | TournamentPairing.HALEY_SOFT:
                return self._current_round <= 2
            case TournamentPairing.SAD if self._rounds is not None:
                return self._current_round <= self._rounds - 2
            case _:
                return False

    def read_papi(self):
        """Fetch tournament information from the Papi database, as well
        as the player information."""
        assert not self.event.lazy_load
        if self._papi_read:
            return
        if self.file_exists:
            with PapiDatabase(self.file) as papi_database:
                (
                    self._rounds,
                    self._pairing,
                    self._rating,
                    self._rating_limit1,
                    self._rating_limit2
                ) = papi_database.read_info()
                self._players_by_id = papi_database.read_players(self._rating, self._rounds)
        else:
            self._rounds = 0
            self._players_by_id = {}
            self._current_round = 0
            self._rating_limit1 = None
            self._rating_limit2 = None
            self._boards = []
            self._unpaired_players = []
            self._players_by_name = []
        self._papi_read = True
        self._calculate_current_round()
        self._set_players_illegal_moves()  # load illegal moves for the current round
        self._calculate_points()
        self._build_boards()

    def _calculate_current_round(self):
        """Computes which round is the current round.
        Currently, the current round is the first paired round with missing
        results."""
        round_infos: dict[int, dict[str, bool]] = {}
        paired_rounds: list[int] = []
        for round_ in range(1, self._rounds + 1):
            round_infos[round_] = {
                'pairings_found': False,
                'results_missing': False,
            }
            for player in self._players_by_id.values():
                if player.id != 1:
                    color, opponent_id, result = player.pairings[round_]
                    if color in ['W', 'B', ]:
                        round_infos[round_]['pairings_found'] = True
                        paired_rounds.append(round_)
                    # NOTE(Amaras) Why is it called RESULT_NOT_PAIRED if it also
                    # represents a missing result?
                    if result == Result.NOT_PAIRED and opponent_id is not None:
                        round_infos[round_]['results_missing'] = True
                    if round_infos[round_]['pairings_found'] and round_infos[round_]['results_missing']:
                        break
        # the current round is the first one with pairings and no missing result
        if paired_rounds:
            for round_ in paired_rounds:
                if round_infos[round_]['results_missing']:
                    self._current_round = round_
                    self._playing = True
                    break
            if self._current_round == 0:
                self._current_round = paired_rounds[-1]

    def _calculate_points(self):
        for player in self._players_by_id.values():
            if player.id == 1:
                continue
            # real points
            player.compute_points(self._current_round)
            # virtual points
            player.vpoints = 0.0
            vpoints: float = 0.0
            if self._pairing == TournamentPairing.HALEY:
                if self._current_round <= 2 and player.rating >= self._rating_limit1:
                    vpoints = 1.0
            elif self._pairing == TournamentPairing.HALEY_SOFT:
                # Round 1: All players above rating_limit1 get 1 vpoint
                # Round 2: All players above rating_limit1 get 1 vpoint
                # Round 2: All other players get .5 vpoints
                # bottom of page #138 on
                # https://dna.ffechecs.fr/wp-content/uploads/sites/2/2023/10/Livre-arbitre-octobre-2023.pdf,
                # please remove if OK
                if self._current_round <= 2 and player.rating >= self.rating_limit1:
                    vpoints = 1.0
                elif self._current_round == 2 and player.rating < self.rating_limit1:
                    vpoints = 0.5
            elif self._pairing == TournamentPairing.SAD:
                # Before the second to last round, we we remove the virtual
                # points, and use a simple Swiss Dutch system.
                if self._current_round <= self._rounds - 2:
                    # Each 1.5 points earned, virtual points go up by 0.5
                    # No player can have more than 2 points.
                    # At the start, players are sorted in three groups
                    # based on their rating.
                    # Group A players start with 2 points
                    # Group B players start with 1 point
                    # Group C players start with 0 points.
                    # If a player reaches more than half of the possible score,
                    # their virtual points capital is raised to 2 points.

                    # NOTE(Amaras): // is implemented on float as well, so it's
                    # way simpler to implement than by applying the algorithm
                    # step by step.
                    potential_vpoints = 0.5 * player.points // 1.5
                    if player.rating >= self.rating_limit1:
                        # Group A players get 2 virtual points
                        vpoints = 2.0
                    elif player.rating >= self.rating_limit2:
                        # Group B players start with 1 point
                        # Players cannot have more than 2 points
                        vpoints = min(2.0, 1.0 + potential_vpoints)
                    else:
                        # Group C players start with 0 points
                        # Players cannor have more than 2 points
                        vpoints = min(2.0, potential_vpoints)
                    if 2 * player.points >= self._rounds:
                        # If a player gets at least half the possible score,
                        # their capital is set at 2 points.
                        # Assumes a 0-0.5-1 scoring system.
                        vpoints = 2.0
            player.vpoints = player.points + vpoints

    def store_illegal_move(self, player: Player):
        """Store an illegal move for the given `player`, for the current
        round."""
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.add_stored_illegal_move(self.id, self.current_round, player.id)
            event_database.commit()
        logger.info('un coup illégal a été enregistré pour le·la joueur·euse [%s]', player.id)

    def delete_illegal_move(self, player: Player) -> bool:
        """Deletes one illegal move for the given `player` for the current
        round. If no illegal move was stored, don't do anything in the database."""
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            deleted: bool = event_database.delete_stored_illegal_move(self.id, self.current_round, player.id)
            event_database.commit()
        if deleted:
            logger.info('un coup illégal a été supprimé pour le·la joueur·euse [%s]', player.id)
        else:
            logger.info('aucun coup illégal n\'a été trouvé pour le·la joueur·euse [%s]', player.id)
        return deleted

    def get_illegal_moves(self) -> Counter[int]:
        """Retrieves all the illegal moves for the current round.
        Returns a Counter, ordered by player id."""
        with EventDatabase(self.event.uniq_id) as event_database:
            return event_database.get_stored_illegal_moves(self.id, self.current_round)

    def _set_players_illegal_moves(self):
        illegal_moves: Counter[int] = self.get_illegal_moves()
        for player in self._players_by_id.values():
            if player.id == 1:
                continue
            player.illegal_moves = illegal_moves[player.id]

    def _build_boards(self):
        if not self._current_round:
            return
        self._boards: list[Board] = []
        self._unpaired_players: list[Player] = []
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
                    if player.pairings[self._current_round].color == Color.WHITE:
                        self._boards.append(Board(white_player=player))
                    else:
                        self._boards.append(Board(black_player=player))
            else:
                self._unpaired_players.append(player)
        self._boards = sorted(self._boards, reverse=True)
        for index, board in enumerate(self._boards, start=1):
            board.id = index
            number: int = board.white_player.fixed or board.black_player.fixed or index
            board.number = number
            board.white_player.set_board(index, number, Color.WHITE)
            board.black_player.set_board(index, number, Color.BLACK)
            board.result = board.white_player.pairings[self._current_round].result
            if self.handicap:
                strong_player: Player
                weak_player: Player
                strong_player, weak_player = sorted(
                    (board.white_player, board.black_player),
                    key=attrgetter('rating'),
                    reverse=True
                )
                weak_time = self.time_control_initial_time
                rating_diff = strong_player.rating - weak_player.rating
                penalties = rating_diff // self.time_control_handicap_penalty_step
                strong_time = max(
                    weak_time - penalties * self.time_control_handicap_penalty_value,
                    self.time_control_handicap_min_time
                )
                strong_player.set_time_control(
                    strong_time, self.time_control_increment, penalties > 0)
                weak_player.set_time_control(weak_time, self.time_control_increment, False)

    @property
    def ffe_upload_needed(self) -> NeedsUpload:
        try:
            if self.stored_tournament.last_ffe_upload > self.file.lstat().st_mtime:
                # last version already uploaded
                return NeedsUpload.NO_CHANGE
            if time.time() < self.stored_tournament.last_ffe_upload + PapiWebConfig().ffe_upload_delay:
                # last upload too recent
                return NeedsUpload.RECENT_CHANGE
            return NeedsUpload.YES
        except FileNotFoundError:
            return NeedsUpload.YES

    def add_result(self, board: Board, white_result: Result):
        """Stores the given result for the given `board` in the current round.
        Stores the `white_result` directly, and uses the opposite result
        as the black's result.
        Assumes that no asymetric result was entered."""
        black_result = white_result.opposite_result
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.add_board_result(board.white_player.id, self._current_round, white_result)
            papi_database.add_board_result(board.black_player.id, self._current_round, black_result)
            papi_database.commit()
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.add_stored_result(self.id, self.current_round, board, white_result)
            event_database.commit()
        logger.info('Added result: %s %s %d.%d %s %s %d %s %s %s %d',
                    self.event.uniq_id, self.uniq_id, self._current_round, board.id, board.white_player.last_name,
                    board.white_player.first_name, board.white_player.rating, white_result,
                    board.black_player.last_name, board.black_player.first_name,
                    board.black_player.rating)

    def delete_result(self, board: Board):
        """Deletes the result for the given `board` in the current round."""
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.remove_board_result(board.white_player.id, self._current_round)
            papi_database.remove_board_result(board.black_player.id, self._current_round)
            papi_database.commit()
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.delete_stored_result(self.id, self.current_round, board.id)
            event_database.commit()
        logger.info('Removed result: %s %s %d.%d',
                    self.event.uniq_id, self.uniq_id, self._current_round, board.id)

    def write_chessevent_info_to_database(
            self, chessevent_tournament: ChessEventTournament, chessevent_download_md5: str) -> int:
        """Stores the information from the given `chessevent_tournament` in
        the event database.
        For comparison, also store `chessevent_download_md5`, so that the 
        tournament is not downloaded unnecessarily."""
        with PapiDatabase(self.file, write=True) as papi_database:
            with EventDatabase(self.event.uniq_id, write=True) as event_database:
                event_database.delete_tournament_stored_skipped_rounds(self.id)
                papi_database.write_chessevent_info(chessevent_tournament)
                player_id: int = 1
                for chessevent_player in chessevent_tournament.players:
                    player_id += 1
                    event_database.add_player_stored_skipped_rounds(
                        self.id, player_id, chessevent_player.skipped_rounds)
                    papi_database.add_chessevent_player(
                        player_id, chessevent_player, chessevent_tournament.check_in_started)
                event_database.set_tournament_last_chessevent_download_md5(self.id, chessevent_download_md5)
                event_database.commit()
                papi_database.commit()
        return player_id - 1

    def check_in_player(self, player: Player, check_in: bool):
        """Stores the `check_in` status for the given `player`.
        If the player has configured skipped rounds, record them as well."""
        with PapiDatabase(self.file, write=True) as papi_database:
            with EventDatabase(self.event.uniq_id, write=True) as event_database:
                papi_database.check_in_player(player.id, check_in, self.skipped_rounds_as_dict)
                event_database.set_tournament_last_check_in_update(self.stored_tournament.id)
                event_database.commit()
                papi_database.commit()
