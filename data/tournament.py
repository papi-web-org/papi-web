import re
import time
from collections import Counter
from logging import Logger
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple, TYPE_CHECKING

from common import format_timestamp_date_time
from common.papi_web_config import PapiWebConfig

if TYPE_CHECKING:
    from data.event import NewEvent
    from data.screen import NewScreen
    from data.family import NewFamily

from common.config_reader import TMP_DIR, ConfigReader
from common.logger import get_logger
from data.board import Board
from data.chessevent import ChessEvent, NewChessEvent
from data.chessevent_tournament import ChessEventTournament
from data.player import Player
from data.util import Color, NeedsUpload, TournamentRating
from data.util import TournamentPairing, Result
from database.papi import PapiDatabase
from database.sqlite import EventDatabase
from database.store import StoredTournament

logger: Logger = get_logger()


class Tournament:
    def __init__(self, event_uniq_id: str, tournament_uniq_id: str, name: str, file: Path, ffe_id: int | None,
                 ffe_password: str | None, handicap_initial_time: int | None, handicap_increment: int | None,
                 handicap_penalty_step: int | None, handicap_penalty_value: int | None, handicap_min_time: int | None,
                 chessevent: ChessEvent | None, chessevent_tournament_name: str | None,
                 record_illegal_moves: int):
        self.event_uniq_id: str = event_uniq_id
        self.uniq_id: str = tournament_uniq_id
        self.name: str = name
        self.file: Path = file
        self.ffe_id: int | None = ffe_id
        self.ffe_password: str | None = ffe_password
        self.handicap_initial_time: int | None = handicap_initial_time
        self.handicap_increment: int | None = handicap_increment
        self.handicap_penalty_step: int | None = handicap_penalty_step
        self.handicap_penalty_value: int | None = handicap_penalty_value
        self.handicap_min_time: int | None = handicap_min_time
        self.chessevent: ChessEvent | None = chessevent
        self.chessevent_tournament_name: str | None = chessevent_tournament_name
        self.record_illegal_moves: int = record_illegal_moves
        self._rounds: int = 0
        self._pairing: TournamentPairing = TournamentPairing.STANDARD
        self._rating: TournamentRating | None = None
        self._players_by_id: dict[int, Player] = {}
        self._current_round: int = 0
        self._rating_limit1: int = 0
        self._rating_limit2: int = 0
        self._boards: list[Board] | None = None
        self._unpaired_players: list[Player] | None = None
        self._database_read = False
        self._players_by_name: list[Player] | None = None
        self.last_illegal_move_update: float = 0.0
        self.last_result_update: float = 0.0

    @property
    def download_allowed(self) -> bool:
        return self.file.exists()

    @property
    def ffe_upload_marker(self) -> Path:
        return TMP_DIR / 'ffe' / f'{self.ffe_id}.upload'

    @property
    def chessevent_download_marker(self) -> Path:
        return TMP_DIR / 'events' / f'{self.event_uniq_id}' / 'chessevent' / f'{self.uniq_id}.download'

    @property
    def handicap(self) -> bool:
        return self.handicap_initial_time is not None

    @property
    def rounds(self) -> int:
        self.read_database()
        return self._rounds

    @property
    def pairing(self) -> TournamentPairing:
        self.read_database()
        return self._pairing

    @property
    def rating(self) -> int:
        self.read_database()
        return self._rating

    @property
    def rating_limit1(self) -> int:
        self.read_database()
        return self._rating_limit1

    @property
    def rating_limit2(self) -> int:
        self.read_database()
        return self._rating_limit2

    @property
    def players_by_id(self) -> dict[int, Player]:
        self.read_database()
        return self._players_by_id

    @property
    def players_by_name_with_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            players: list[Player] = list(self.players_by_id.values())[1:]
            self._players_by_name = sorted(
                players, key=lambda player: (player.last_name, player.first_name))
        return self._players_by_name

    @property
    def players_by_name_without_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            players: list[Player] = []
            for player in list(self.players_by_id.values())[1:]:
                if not self.current_round or player.board_id:
                    players.append(player)
            self._players_by_name = sorted(
                players, key=lambda p: (p.last_name, p.first_name))
        return self._players_by_name

    @property
    def current_round(self) -> int | None:
        self.read_database()
        return self._current_round

    @property
    def boards(self) -> list[Board] | None:
        self.read_database()
        return self._boards

    @property
    def unpaired_players(self) -> list[Player] | None:
        self.read_database()
        return self._unpaired_players

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

    def read_database(self):
        if self._database_read:
            return
        if self.file and self.file.exists():
            with PapiDatabase(self.file) as papi_database:
                (
                    self._rounds,
                    self._pairing,
                    self._rating,
                    self._rating_limit1,
                    self._rating_limit2
                ) = papi_database.read_info()
                self._players_by_id = papi_database.read_players(self._rating, self._rounds)
        self._database_read = True
        self._calculate_current_round()
        self._set_players_illegal_moves()  # load illegal moves for the current round
        self._calculate_points()
        self._build_boards()

    def _calculate_current_round(self):
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
            if self._pairing == TournamentPairing.HALEY:
                if self._current_round <= 2:
                    if player.rating >= self._rating_limit1:
                        player.add_vpoints(1.0)
            elif self._pairing == TournamentPairing.HALEY_SOFT:
                # Round 1: All players above rating_limit1 get 1 vpoint
                # Round 2: All players above rating_limit1 get 1 vpoint
                # Round 2: All other players get .5 vpoints
                # bottom of page #138 on
                # https://dna.ffechecs.fr/wp-content/uploads/sites/2/2023/10/Livre-arbitre-octobre-2023.pdf,
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

    @property
    def _illegal_moves_marker_dir(self) -> Path:
        return TMP_DIR / 'events' / self.event_uniq_id / 'illegal_moves'

    @property
    def illegal_moves_marker(self) -> Path:
        return self._illegal_moves_marker_dir / f'{self.uniq_id}.marker'

    def _touch_illegal_moves_marker(self):
        self._illegal_moves_marker_dir.mkdir(exist_ok=True)
        self.illegal_moves_marker.touch(exist_ok=True)

    def store_illegal_move(self, player: Player):
        with EventDatabase(self.event_uniq_id, write=True) as event_database:
            event_database.add_stored_illegal_move_with_tournament_uniq_id(self.uniq_id, self.current_round, player.id)
            event_database.commit()
        self._touch_illegal_moves_marker()
        logger.info('le coup illégal a été enregistré')
    
    def delete_illegal_move(self, player: Player) -> bool:
        with EventDatabase(self.event_uniq_id, write=True) as event_database:
            deleted: bool = event_database.delete_stored_illegal_move_with_tournament_uniq_id(
                self.uniq_id, self.current_round, player.id)
            event_database.commit()
        self._touch_illegal_moves_marker()
        if deleted:
            logger.info('un coup illégal a été supprimé pour le·la joueur·euse [%s]', player.id)
        else:
            logger.info('aucun coup illégal n\'a été trouvé pour le·la joueur·euse [%s]', player.id)
        return deleted

    def get_illegal_moves(self) -> Counter[int]:
        with EventDatabase(self.event_uniq_id, write=True) as event_database:
            return event_database.get_stored_illegal_moves_with_tournament_uniq_id(self.uniq_id, self.current_round)

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

    def ffe_upload_needed(self, ffe_upload_delay) -> NeedsUpload:
        try:
            marker_time = self.ffe_upload_marker.lstat().st_mtime
            if marker_time > self.file.lstat().st_mtime:
                # last version already uploaded
                return NeedsUpload.NO_CHANGE
            if time.time() < marker_time + ffe_upload_delay:
                # last upload too recent
                return NeedsUpload.RECENT_CHANGE
            return NeedsUpload.YES
        except FileNotFoundError:
            return NeedsUpload.YES

    @property
    def _results_marker_dir(self) -> Path:
        return TMP_DIR / 'events' / self.event_uniq_id / 'results'

    @property
    def results_marker(self) -> Path:
        return self._results_marker_dir / f'{self.uniq_id}.marker'

    def _touch_results_marker(self):
        self._results_marker_dir.mkdir(exist_ok=True)
        self.results_marker.touch(exist_ok=True)

    def add_result(self, board: Board, white_result: Result):
        black_result = white_result.opposite_result
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.add_board_result(board.white_player.id, self._current_round, white_result)
            papi_database.add_board_result(board.black_player.id, self._current_round, black_result)
            papi_database.commit()
        with EventDatabase(self.event_uniq_id, write=True) as event_database:
            event_database.add_stored_result_with_tournament_uniq_id(
                self.uniq_id, self.current_round, board, white_result)
            event_database.commit()
        self._touch_results_marker()
        logger.info('Added result: %s %s %d.%d %s %s %d %s %s %s %d',
                    self.event_uniq_id, self.uniq_id, self._current_round, board.id, board.white_player.last_name,
                    board.white_player.first_name, board.white_player.rating, white_result,
                    board.black_player.last_name, board.black_player.first_name,
                    board.black_player.rating)
    
    def delete_result(self, board: Board):
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.remove_board_result(board.white_player.id, self._current_round)
            papi_database.remove_board_result(board.black_player.id, self._current_round)
            papi_database.commit()
        with EventDatabase(self.event_uniq_id, write=True) as event_database:
            event_database.delete_stored_result_with_tournament_uniq_id(self.uniq_id, self.current_round, board.id)
            event_database.commit()
        self._touch_results_marker()
        logger.info('Removed result: %s %s %d.%d',
                    self.event_uniq_id, self.uniq_id, self._current_round, board.id)

    def write_chessevent_info_to_database(self, chessevent_tournament: ChessEventTournament) -> int:
        with PapiDatabase(self.file, write=True) as papi_database:
            with EventDatabase(self.event_uniq_id, write=True) as event_database:
                stored_tournament: StoredTournament = event_database.get_stored_tournament_with_uniq_id(
                    self.event_uniq_id)
                event_database.delete_tournament_stored_skipped_rounds(stored_tournament.id)
                papi_database.write_chessevent_info(chessevent_tournament)
                player_id: int = 1
                for chessevent_player in chessevent_tournament.players:
                    player_id += 1
                    event_database.add_player_stored_skipped_rounds(
                        stored_tournament.id, player_id, chessevent_player.skipped_rounds)
                    papi_database.add_chessevent_player(
                        player_id, chessevent_player, chessevent_tournament.check_in_started)
                event_database.commit()
            papi_database.commit()
        return player_id - 1

    def check_in_player(self, player: Player, check_in: bool):
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.check_in_player(player.id, check_in, {})
            # no skipped round passed here since this code will be deleted soon
            papi_database.commit()


class HandicapTournament(NamedTuple):
    """A helper data structure to store the information needed to
    compute handicap times if needed."""
    initial_time: int | None = None
    increment: int | None = None
    penalty_step: int | None = None
    penalty_value: int | None = None
    min_time: int | None = None


class TournamentBuilder:
    def __init__(
            self, config_reader: ConfigReader, event_database: EventDatabase, event_uniq_id: str,
            default_tournament_path: Path, chessevents: dict[str, ChessEvent],
            default_record_illegal_moves: int):
        self._config_reader: ConfigReader = config_reader
        self.event_database: EventDatabase = event_database
        self._event_uniq_id: str = event_uniq_id
        self._default_tournament_path: Path = default_tournament_path
        self._chessevents: dict[str, ChessEvent] = chessevents
        self.default_record_illegal_moves: int = default_record_illegal_moves
        self.tournaments: dict[str, Tournament] = {}
        for tournament_uniq_id in self._read_tournament_uniq_ids():
            self._build_tournament(tournament_uniq_id)
        if not self.tournaments:
            self._config_reader.add_error('aucun tournoi initialisé')

    def _read_tournament_uniq_ids(self) -> list[str]:
        tournament_uniq_ids: list[str] = self._config_reader.get_subsection_keys_with_prefix('tournament')
        # NOTE(Amaras) Special case of tournament: handicap depends on
        # the [tournament] section being there.
        if 'handicap' in tournament_uniq_ids:
            tournament_uniq_ids.remove('handicap')
        if 'tournament' in self._config_reader:
            if tournament_uniq_ids:
                section_keys: str = ', '.join('[tournament.' + id + ']' for id in tournament_uniq_ids)
                self._config_reader.add_error(
                    f"la rubrique [tournament] ne doit être utilisée que lorsque l'évènement ne compte "
                    f"qu'un tournoi, d'autres rubriques sont présentes ({section_keys})",
                    'tournament.*'
                )
                return []
            default_tournament_uniq_id: str = 'default'
            old_tournament_section_key: str = 'tournament'
            new_tournament_section_key: str = 'tournament.' + default_tournament_uniq_id
            self._config_reader.rename_section(old_tournament_section_key, new_tournament_section_key)
            self._config_reader.add_debug(
                f'un seul tournoi, la rubrique [{old_tournament_section_key}] a '
                f'été renommée [{new_tournament_section_key}]',
                old_tournament_section_key
            )
            old_handicap_section_key: str = 'tournament.handicap'
            if old_handicap_section_key in self._config_reader:
                new_handicap_section_key = f'tournament.{default_tournament_uniq_id}.handicap'
                self._config_reader.rename_section(old_handicap_section_key, new_handicap_section_key)
                self._config_reader.add_debug(
                    f'un seul tournoi, la rubrique [{old_handicap_section_key}] a '
                    f'été renommée [{new_tournament_section_key}]'
                )
            tournament_uniq_ids.append(default_tournament_uniq_id)
        elif not tournament_uniq_ids:
            self._config_reader.add_error('aucun tournoi trouvé', 'tournament.*')
        return tournament_uniq_ids

    def _build_tournament(self, tournament_uniq_id: str):
        section_key: str = f'tournament.{tournament_uniq_id}'
        if tournament_uniq_id.find('/') != -1:
            self._config_reader.add_error(
                "le caractère « / » n\'est pas autorisé dans les identifiants des tournois, tournoi ignoré",
                section_key
            )
            return None
        try:
            section = self._config_reader[section_key]
        except KeyError:
            self._config_reader.add_error('Tournoi non trouvé', section_key)
            return
        key = 'path'
        tournament_path: Path = self._default_tournament_path
        try:
            tournament_path = Path(section[key])
        except KeyError:
            self._config_reader.add_debug(
                    f'option absente, par défault [{self._default_tournament_path}]',
                    section_key, key)
        except TypeError:
            self._config_reader.add_error(
                    f'La rubrique [{section_key}] est en fait une option, tournoi ignoré',
                    section_key)
            return
        # NOTE(Amaras) TOC/TOU bug
        if not tournament_path.exists():
            self._config_reader.add_warning(
                    f"le répertoire [{tournament_path}] n'existe pas",
                    section_key, key)
        elif not tournament_path.is_dir():
            self._config_reader.add_error(
                    f"[{tournament_path}] n'est pas un répertoire, tournoi ignoré",
                    section_key, key)
            return
        key = 'filename'
        filename: str | None = section.get(key)
        key = 'ffe_id'
        ffe_id: int | None = None
        try:
            ffe_id = int(section[key])
            assert ffe_id >= 1
        except KeyError:
            pass
        except ValueError:
            self._config_reader.add_warning('un entier est attendu', section_key, key)
            ffe_id = None
        except AssertionError:
            self._config_reader.add_warning(
                    'un entier positif non nul est attendu',
                    section_key,
                    key
            )
            ffe_id = None
        if filename is None and ffe_id is None:
            self._config_reader.add_error(
                    'ni [filename] ni [ffe_id] ne sont indiqués, tournoi ignoré',
                    section_key
            )
            return
        if filename is None:
            filename = str(ffe_id)
        file: Path = tournament_path / f'{filename}.papi'
        # NOTE(Amaras) TOC/TOU bug
        if tournament_path.is_dir():
            if not file.exists():
                self._config_reader.add_warning(f'le fichier [{file}] n\'existe pas', section_key)
            elif not file.is_file():
                self._config_reader.add_error(f'[{file}] n\'est pas un fichier, tournoi ignoré', section_key)
                return
        key = 'name'
        default_name: str = tournament_uniq_id
        try:
            name = section[key]
        except KeyError:
            self._config_reader.add_info(
                    f'option absente, par défaut [{default_name}]',
                    section_key, key)
            name = default_name
        key = 'ffe_password'
        ffe_password: str | None = None
        if ffe_id is not None:
            try:
                ffe_password = section[key]
                if not re.match('^[A-Z]{10}$', ffe_password):
                    self._config_reader.add_warning(
                        'un mot de 10 lettres majuscules est attendu, le mot de passe est ignoré (les '
                        'opérations sur le site web de la FFE ne seront pas disponibles)',
                        section_key, key)
                    ffe_password = None
            except KeyError:
                self._config_reader.add_info(
                    'option absente, les opérations sur le site web de la FFE ne seront pas disponibles',
                    section_key, key)
        elif key in section:
            self._config_reader.add_info(
                "option ignorée quand l'option [ffe_id] n'est pas indiquée",
                section_key, key)

        key = 'chessevent_tournament_name'
        chessevent_tournament_name: str | None = None
        try:
            chessevent_tournament_name: str = section[key]
        except KeyError:
            pass
        if not chessevent_tournament_name:
            self._config_reader.add_info('option absente', section_key, key)
            chessevent = None
        else:
            key = 'chessevent_connection_id'
            chessevent: ChessEvent | None = None
            chessevent_uniq_id: str | None = None
            try:
                chessevent_uniq_id = section[key]
            except KeyError:
                pass
            if chessevent_uniq_id:
                try:
                    chessevent = self._chessevents[chessevent_uniq_id]
                except KeyError:
                    self._config_reader.add_warning(
                        f'connexion à Chess Event [{chessevent_uniq_id}] introuvable',
                        section_key, 'chessevent_tournament_name')
                    chessevent_tournament_name = None
            else:
                try:
                    chessevent = self._chessevents[tournament_uniq_id]
                    self._config_reader.add_info(
                        f'l\'option chessevent_connection_id n\'est pas définie, utilisation par défaut de la '
                        f'connexion à Chess Event [{tournament_uniq_id}]',
                        section_key, 'chessevent_tournament_name')
                except KeyError:
                    if len(self._chessevents) == 0:
                        self._config_reader.add_warning(
                            'aucune connexion à Chess Event définie', section_key, 'chessevent_tournament_name')
                        chessevent_tournament_name = None
                    elif len(self._chessevents) > 1:
                        self._config_reader.add_warning(
                            'plusieurs connexions à Chess Event sont définies, la connexion doit être précisée à '
                            'l\'aide de l\'option chess_connection_id', section_key, 'chessevent_tournament_name')
                        chessevent_tournament_name = None
                    else:
                        self._config_reader.add_warning(
                            f'utilisation de l\'unique connexion à Chess Event '
                            f'[{list(self._chessevents.keys())[0]}]',
                            section_key, 'chessevent_tournament_name')
                        chessevent = list(self._chessevents.values())[0]
        if not chessevent_tournament_name:
            self._config_reader.add_info(
                'la création du fichier Papi depuis la plateforme Chess Event ne sera pas disponible', section_key)
        key = 'record_illegal_moves'
        record_illegal_moves: int = self.default_record_illegal_moves
        if key in section:
            record_illegal_moves_bool: bool | None = self._config_reader.getboolean_safe(section_key, key)
            if record_illegal_moves_bool is None:
                record_illegal_moves_int: int | None = self._config_reader.getint_safe(section_key, key, minimum=0)
                if record_illegal_moves_int is None:
                    self._config_reader.add_warning(
                        'un booléen ou un entier positif ou nul est attendu, écran ignoré', section_key, key)
                    return None
                else:
                    record_illegal_moves = record_illegal_moves_int
            else:
                if record_illegal_moves_bool:
                    record_illegal_moves = self.default_record_illegal_moves
                else:
                    record_illegal_moves = 0
        else:
            self._config_reader.add_debug(f'option absente, par défaut [{record_illegal_moves}]')

        tournament_section_keys: list[str] = [
            'path',
            'filename',
            'name',
            'ffe_id',
            'ffe_password',
            'chessevent_connection_id',
            'chessevent_tournament_name',
            'record_illegal_moves',
        ]
        for key, _ in section.items():
            if key not in tournament_section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)
        handicap_section_key = 'tournament.' + tournament_uniq_id + '.handicap'
        handicap_values = self._build_tournament_handicap(handicap_section_key)
        if handicap_values[0] is not None and ffe_id is not None:
            self._config_reader.add_warning(
                'les tournois à handicap ne devraient pas être homologués',
                handicap_section_key
            )

        tournament: Tournament = Tournament(
            self._event_uniq_id, tournament_uniq_id, name, file, ffe_id, ffe_password, *handicap_values,
            chessevent, chessevent_tournament_name, record_illegal_moves)
        stored_tournament: StoredTournament = self.event_database.get_stored_tournament_with_uniq_id(
            tournament_uniq_id=tournament_uniq_id)
        tournament.last_illegal_move_update = stored_tournament.last_illegal_move_update
        tournament.last_result_update = stored_tournament.last_result_update

        self.tournaments[tournament_uniq_id] = tournament

    def _build_tournament_handicap(self, section_key: str) -> HandicapTournament:
        try:
            handicap_section = self._config_reader[section_key]
        except KeyError:
            return HandicapTournament()
        section_keys: list[str] = [
            'initial_time',
            'increment',
            'penalty_step',
            'penalty_value',
            'min_time',
        ]
        for key in self._config_reader[section_key]:
            if key not in section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)
        ignore_message = 'configuration de handicap ignorée'
        positive_messages = (
            f'La rubrique est en fait une option, {ignore_message}',
            f'option absente, {ignore_message}',
            f'un entier est attendu, {ignore_message}',
            f'un entier strictement positif est attendu, {ignore_message}'
        )
        non_negative_messages = (
            f'La rubrique est en fait une option, {ignore_message}'
            f'option absente, {ignore_message}',
            f'un entier est attendu, {ignore_message}',
            f'un entier positif est attendu, {ignore_message}'
        )
        key = 'initial_time'
        initial_time: int | None = self._config_reader.get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if initial_time is None:
            return HandicapTournament()
        key = 'increment'
        increment: int | None = self._config_reader.get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 0,
            None,
            *non_negative_messages
        )
        if increment is None:
            return HandicapTournament()
        key = 'penalty_step'
        penalty_step: int | None = self._config_reader.get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_step is None:
            return HandicapTournament()
        key = 'penalty_value'
        penalty_value: int | None = self._config_reader.get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            None,
            *positive_messages
        )
        if penalty_value is None:
            return HandicapTournament()
        key = 'min_time'
        min_time: int | None = self._config_reader.get_value_with_warning(
            handicap_section,
            section_key,
            key,
            int,
            lambda x: x >= 1,
            *positive_messages
        )
        if min_time is None:
            return HandicapTournament()
        return HandicapTournament(
            initial_time,
            increment,
            penalty_step,
            penalty_value,
            min_time,
        )


class NewTournament:
    def __init__(self, event: 'NewEvent', stored_tournament: StoredTournament, ):
        self.event: 'NewEvent' = event
        self.stored_tournament: StoredTournament = stored_tournament
        if not stored_tournament.path:
            self.event.add_debug(
                f'pas de répertoire défini pour le fichier Papi, par défaut [{self.path}]',
                tournament_uniq_id=self.uniq_id)
        if not self.path.exists():
            self.event.add_warning(f'le répertoire [{self.path}] n\'existe pas', tournament_uniq_id=self.uniq_id)
        elif not self.path.is_dir():
            self.event.add_error(f'[{self.path}] n\'est pas un répertoire', tournament_uniq_id=self.uniq_id)
        if not self.stored_tournament.filename:
            self.event.add_info(
                f'le nom du fichier Papi n\'est pas défini, par défaut [{self.filename}]',
                tournament_uniq_id=self.uniq_id)
        if not self.stored_tournament.ffe_id or not self.stored_tournament.ffe_password:
            self.event.add_info(
                f'le numéro d\'homologation et le mot de passe de connexion au site fédéral sont nécessaires '
                f'pour les opérations sur le site fédéral, elles ne seront pas disponibles',
                tournament_uniq_id=self.uniq_id)
        if not self.chessevent:
            self.event.add_info(
                f'la connexion à la plateforme ChessEvent n\'est pas définie', tournament_uniq_id=self.uniq_id)
        if self.chessevent and not self.stored_tournament.chessevent_tournament_name:
            self.event.add_warning(f'le répertoire [{self.path}] n\'existe pas', tournament_uniq_id=self.uniq_id)
        self._rounds: int = 0
        self._pairing: TournamentPairing | None = None
        self._rating: TournamentRating | None = None
        self._players_by_id: dict[int, Player] = {}
        self._current_round: int = 0
        self._rating_limit1: int = 0
        self._rating_limit2: int = 0
        self._boards: list[Board] | None = None
        self._unpaired_players: list[Player] | None = None
        self._papi_read = False
        self._players_by_name: list[Player] | None = None
        self._dependent_families: list['NewFamily'] | None = None
        self._dependent_screens: list['NewScreen'] | None = None

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
        return self.path / f'{self.filename}.{PapiWebConfig().papi_ext}'

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
    def chessevent(self) -> NewChessEvent | None:
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
    def last_chessevent_download(self) -> float:
        return self.stored_tournament.last_chessevent_download

    @property
    def download_allowed(self) -> bool:
        return self.file_exists

    @property
    def handicap(self) -> bool:
        return self.time_control_handicap_penalty_value is not None

    @property
    def skipped_rounds_as_dict(self) -> dict[int, dict[int, float]]:
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

    @property
    def players_by_name_with_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            players: list[Player] = list(self.players_by_id.values())[1:]
            self._players_by_name = sorted(
                players, key=lambda player: (player.last_name, player.first_name))
        return self._players_by_name

    @property
    def players_by_name_without_unpaired(self) -> list[Player]:
        if self._players_by_name is None:
            players: list[Player] = []
            for player in list(self.players_by_id.values())[1:]:
                if not self.current_round or player.board_id:
                    players.append(player)
            self._players_by_name = sorted(
                players, key=lambda p: (p.last_name, p.first_name))
        return self._players_by_name

    @property
    def current_round(self) -> int | None:
        self.read_papi()
        return self._current_round

    @property
    def boards(self) -> list[Board] | None:
        self.read_papi()
        return self._boards

    @property
    def unpaired_players(self) -> list[Player] | None:
        self.read_papi()
        return self._unpaired_players

    @property
    def dependent_families(self) -> list['NewFamily']:
        if self._dependent_families is None:
            self._dependent_families = [
                family
                for family in self.event.families_by_id.values()
                if family.tournament.id == self.id
            ]
        return self._dependent_families

    @property
    def dependent_screens(self) -> list['NewScreen']:
        if self._dependent_screens is None:
            self._dependent_screens = []
            for screen in self.event.basic_screens_by_id.values():
                for screen_set in screen.screen_sets_sorted_by_order:
                    if screen_set.tournament.id == self.id:
                        self.dependent_screens.append(screen)
        return self._dependent_screens

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
            if self._pairing == TournamentPairing.HALEY:
                if self._current_round <= 2:
                    if player.rating >= self._rating_limit1:
                        player.add_vpoints(1.0)
            elif self._pairing == TournamentPairing.HALEY_SOFT:
                # Round 1: All players above rating_limit1 get 1 vpoint
                # Round 2: All players above rating_limit1 get 1 vpoint
                # Round 2: All other players get .5 vpoints
                # bottom of page #138 on
                # https://dna.ffechecs.fr/wp-content/uploads/sites/2/2023/10/Livre-arbitre-octobre-2023.pdf,
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

    def store_illegal_move(self, player: Player):
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.add_stored_illegal_move(self.id, self.current_round, player.id)
            event_database.commit()
        logger.info('le coup illégal a été enregistré')

    def delete_illegal_move(self, player: Player) -> bool:
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            deleted: bool = event_database.delete_stored_illegal_move(self.id, self.current_round, player.id)
            event_database.commit()
        if deleted:
            logger.info('un coup illégal a été supprimé pour le·la joueur·euse [%s]', player.id)
        else:
            logger.info('aucun coup illégal n\'a été trouvé pour le·la joueur·euse [%s]', player.id)
        return deleted

    def get_illegal_moves(self) -> Counter[int]:
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
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
                strong_player.set_handicap(
                    strong_time, self.time_control_increment, penalties > 0)
                weak_player.set_handicap(weak_time, self.time_control_increment, False)

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
        black_result = white_result.opposite_result
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.add_board_result(board.white_player.id, self._current_round, white_result)
            papi_database.add_board_result(board.black_player.id, self._current_round, black_result)
            papi_database.commit()
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.add_stored_result_with_tournament_uniq_id(
                self.uniq_id, self.current_round, board, white_result)
            event_database.commit()
        logger.info('Added result: %s %s %d.%d %s %s %d %s %s %s %d',
                    self.event.uniq_id, self.uniq_id, self._current_round, board.id, board.white_player.last_name,
                    board.white_player.first_name, board.white_player.rating, white_result,
                    board.black_player.last_name, board.black_player.first_name,
                    board.black_player.rating)

    def delete_result(self, board: Board):
        with PapiDatabase(self.file, write=True) as papi_database:
            papi_database.remove_board_result(board.white_player.id, self._current_round)
            papi_database.remove_board_result(board.black_player.id, self._current_round)
            papi_database.commit()
        with EventDatabase(self.event.uniq_id, write=True) as event_database:
            event_database.delete_stored_result_with_tournament_uniq_id(self.uniq_id, self.current_round, board.id)
            event_database.commit()
        logger.info('Removed result: %s %s %d.%d',
                    self.event.uniq_id, self.uniq_id, self._current_round, board.id)

    def write_chessevent_info_to_database(self, chessevent_tournament: ChessEventTournament) -> int:
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
                event_database.commit()
                papi_database.commit()
        return player_id - 1

    def check_in_player(self, player: Player, check_in: bool):
        with PapiDatabase(self.file, write=True) as papi_database:
            with EventDatabase(self.event.uniq_id, write=True) as event_database:
                papi_database.check_in_player(player.id, check_in, self.skipped_rounds_as_dict)
                event_database.set_tournament_last_check_in_update(self.stored_tournament.id)
                event_database.commit()
                papi_database.commit()
