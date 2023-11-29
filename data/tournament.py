import re
from logging import Logger
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple

from common.config_reader import TMP_DIR, ConfigReader
from common.logger import get_logger
from data.board import Board
from data.chessevent_connection import ChessEventConnection
from data.chessevent_tournament import ChessEventTournament
from data.player import Player
from data.util import Color, TournamentRating
from data.util import TournamentPairing, Result
from database.papi import PapiDatabase

logger: Logger = get_logger()


class Tournament:
    def __init__(self, tournament_id: str, name: str, file: Path, ffe_id: int | None, ffe_password: str | None,
                 handicap_initial_time: int | None, handicap_increment: int | None, handicap_penalty_step: int | None,
                 handicap_penalty_value: int | None, handicap_min_time: int | None,
                 chessevent_connection: ChessEventConnection | None, chessevent_tournament_name: str | None):
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
        self.chessevent_connection: ChessEventConnection | None = chessevent_connection
        self.chessevent_tournament_name: str | None = chessevent_tournament_name
        self.papi_database: PapiDatabase = PapiDatabase(self.file)
        self._rounds: int = 0
        self._pairing: TournamentPairing = TournamentPairing.STANDARD
        self._rating: TournamentRating | None = None
        self._players_by_id: dict[int, Player] = {}
        self._current_round: int = 0
        self._rating_limit1: int = 0
        self._rating_limit2: int = 0
        self._boards: list[Board] | None = None
        self._database_read = False
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
        self.read_database()
        return self._current_round

    @property
    def boards(self) -> list[Board] | None:
        self.read_database()
        return self._boards

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
            with self.papi_database:
                (
                    self._rounds,
                    self._pairing,
                    self._rating,
                    self._rating_limit1,
                    self._rating_limit2
                ) = self.papi_database.read_info()
                self._players_by_id = self.papi_database.read_players(self._rating, self._rounds)
        self._database_read = True
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
                    if result == Result.NOT_PAIRED and opponent_id is not None:
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
            if self._pairing == TournamentPairing.HALEY:
                if self._current_round <= 2:
                    if player.rating >= self._rating_limit1:
                        player.add_vpoints(1.0)
            elif self._pairing == TournamentPairing.HALEY_SOFT:
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
                    if player.pairings[self._current_round].color == Color.WHITE:
                        self._boards.append(Board(white_player=player))
                    else:
                        self._boards.append(Board(black_player=player))
        # sort the boards
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

    def add_result(self, board: Board, white_result: Result):
        black_result = white_result.opposite_result
        with self.papi_database:
            self.papi_database.add_board_result(board.white_player.id, self._current_round, white_result)
            self.papi_database.add_board_result(board.black_player.id, self._current_round, black_result)
            self.papi_database.commit()
        logger.info(f'Added result: {self.id} {self._current_round}.{board.id} '
                    f'{board.white_player.last_name} '
                    f'{board.white_player.first_name} '
                    f'{board.white_player.rating} '
                    f'{white_result} '
                    f'{board.black_player.last_name} '
                    f'{board.black_player.first_name} '
                    f'{board.black_player.rating}')

    def write_chessevent_info_to_database(self, chessevent_tournament: ChessEventTournament) -> int:
        with self.papi_database:
            self.papi_database.write_chessevent_info(chessevent_tournament)
            player_id: int = 1
            for chessevent_player in chessevent_tournament.players:
                player_id += 1
                self.papi_database.add_chessevent_player(player_id, chessevent_player)
            self.papi_database.commit()
        return player_id - 1


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
            self, config_reader: ConfigReader, default_tournament_path: Path,
            chessevent_connections: dict[str, ChessEventConnection]):
        self._config_reader: ConfigReader = config_reader
        self._default_tournament_path: Path = default_tournament_path
        self._chessevent_connections: dict[str, ChessEventConnection] = chessevent_connections
        self.tournaments: dict[str, Tournament] = {}
        for tournament_id in self._read_tournament_ids():
            self._build_tournament(tournament_id)
        if not self.tournaments:
            self._config_reader.add_error('aucun tournoi initialisé')

    def _read_tournament_ids(self) -> list[str]:
        tournament_ids: list[str] = self._config_reader.get_subsection_keys_with_prefix('tournament')
        # NOTE(Amaras) Special case of tournament: handicap depends on
        # the [tournament] section being there.
        if 'handicap' in tournament_ids:
            tournament_ids.remove('handicap')
        if 'tournament' in self._config_reader:
            if tournament_ids:
                section_keys: str = ', '.join('[tournament.' + id + ']' for id in tournament_ids)
                self._config_reader.add_error(
                    f"la rubrique [tournament] ne doit être utilisée que lorsque l'évènement ne compte "
                    f"qu'un tournoi, d'autres rubriques sont présentes ({section_keys})",
                    'tournament.*'
                )
                return []
            default_tournament_id: str = 'default'
            old_tournament_section_key: str = 'tournament'
            new_tournament_section_key: str = 'tournament.' + default_tournament_id
            self._config_reader.rename_section(old_tournament_section_key, new_tournament_section_key)
            self._config_reader.add_debug(
                f'un seul tournoi, la rubrique [{old_tournament_section_key}] a '
                f'été renommée [{new_tournament_section_key}]',
                old_tournament_section_key
            )
            old_handicap_section_key: str = 'tournament.handicap'
            if old_handicap_section_key in self._config_reader:
                new_handicap_section_key = f'tournament.{default_tournament_id}.handicap'
                self._config_reader.rename_section(old_handicap_section_key, new_handicap_section_key)
                self._config_reader.add_debug(
                    f'un seul tournoi, la rubrique [{old_handicap_section_key}] a '
                    f'été renommée [{new_tournament_section_key}]'
                )
            tournament_ids.append(default_tournament_id)
        elif not tournament_ids:
            self._config_reader.add_error('aucun tournoi trouvé', 'tournament.*')
        return tournament_ids

    def _build_tournament(self, tournament_id: str):
        section_key: str = f'tournament.{tournament_id}'
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
                    f'La rubrique [{section_key}] est en fait une option',
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
        default_name: str = tournament_id
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
            chessevent_connection = None
        else:
            key = 'chessevent_connection_id'
            chessevent_connection: ChessEventConnection | None = None
            chessevent_connection_id: str | None = None
            try:
                chessevent_connection_id = section[key]
            except KeyError:
                pass
            if chessevent_connection_id:
                try:
                    chessevent_connection = self._chessevent_connections[chessevent_connection_id]
                except KeyError:
                    self._config_reader.add_warning(
                        f'connexion à Chess Event [{chessevent_connection_id}] introuvable',
                        section_key, 'chessevent_tournament_name')
                    chessevent_tournament_name = None
            else:
                if len(self._chessevent_connections) == 0:
                    self._config_reader.add_warning(
                        'aucune connexion à Chess Event définie', section_key, 'chessevent_tournament_name')
                    chessevent_tournament_name = None
                elif len(self._chessevent_connections) > 1:
                    self._config_reader.add_warning(
                        f'plusieurs connexions à Chess Event sont définies, la connexion doit être précisée à '
                        'l\'aide de l\'option chess_connection_id', section_key, 'chessevent_tournament_name')
                    chessevent_tournament_name = None
                else:
                    chessevent_connection = list(self._chessevent_connections.values())[0]
        if not chessevent_tournament_name:
            self._config_reader.add_info(
                'la création du fichier Papi depuis la plateforme Chess Event ne sera pas disponible', section_key)

        tournament_section_keys: list[str] = [
            'path',
            'filename',
            'name',
            'ffe_id',
            'ffe_password',
            'chessevent_connection_id',
            'chessevent_tournament_name',
        ]
        for key, value in section.items():
            if key not in tournament_section_keys:
                self._config_reader.add_warning('option inconnue', section_key, key)
        handicap_section_key = 'tournament.' + tournament_id + '.handicap'
        handicap_values = self._build_tournament_handicap(handicap_section_key)
        if handicap_values[0] is not None and ffe_id is not None:
            self._config_reader.add_warning(
                'les tournois à handicap ne devraient pas être homologués',
                handicap_section_key
            )

        self.tournaments[tournament_id] = Tournament(
            tournament_id, name, file, ffe_id, ffe_password, *handicap_values, chessevent_connection,
            chessevent_tournament_name)

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
