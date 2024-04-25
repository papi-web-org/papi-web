import re
from datetime import datetime, timedelta
from pathlib import Path
from logging import Logger
from itertools import product
from typing import NamedTuple, Self
from contextlib import suppress

from common.config_reader import TMP_DIR
from data.chessevent_player import ChessEventPlayer
from data.chessevent_tournament import ChessEventTournament
from database.access import AccessDatabase
from data.pairing import Pairing
from data.player import Player
from common.logger import get_logger

from data.util import Result, TournamentPairing, PlayerGender, PlayerTitle, Color, TournamentRating

logger: Logger = get_logger()


class TournamentInfo(NamedTuple):
    rounds: int
    pairing: TournamentPairing
    rating: TournamentRating
    rating_limit1: int
    rating_limit2: int


class PapiDatabase(AccessDatabase):
    """The database class, using the Papi format of the French Chess Federation
    Tournament manager."""

    def __init__(self, event_id: str, tournament_id: str, file: Path, method: str):
        # event_id and tournament_id are needed to store/read skipped rounds
        # as long as skipped rounds are not stored in the database but files
        self.event_id = event_id
        self.tournament_id = tournament_id
        super().__init__(file, method)

    def __enter__(self) -> Self:
        return super().__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        super().__exit__(exc_type, exc_value, traceback)

    def commit(self):
        self._commit()

    def _read_var(self, name: str) -> str:
        query: str = 'SELECT `Value` FROM `info` WHERE `Variable` = ?'
        self._execute(query, (name,))
        return self._fetchval()

    def read_info(self) -> TournamentInfo:
        """Reads the database and returns basic information about the
        tournament."""
        rounds: int = int(self._read_var('NbrRondes'))
        pairing: TournamentPairing = TournamentPairing.from_papi_value(self._read_var('Pairing'))
        rating: TournamentRating = TournamentRating.from_papi_value(self._read_var('ClassElo'))
        rating_limit1: int = int(self._read_var('EloBase1'))
        rating_limit2: int = int(self._read_var('EloBase2'))
        return TournamentInfo(rounds, pairing, rating, rating_limit1, rating_limit2)

    def read_players(self, tournament_rating: TournamentRating, rounds: int) -> dict[int, Player]:
        """Reads the database and fetches the Player identification, pairings
        and results."""
        players: dict[int, Player] = {}
        player_fields: list[str] = [
            'Ref', 'Nom', 'Prenom', 'Sexe', 'FideTitre', 'Fixe',
            'Elo', 'Rapide', 'Blitz', 'Fide', 'RapideFide', 'BlitzFide',
            'Pointe'
        ]
        for rd, suffix in product(range(1, rounds + 1), ['Cl', 'Adv', 'Res']):
            player_fields.append(f'Rd{rd:0>2}{suffix}')
        query: str = f'SELECT {", ".join(player_fields)} FROM joueur ORDER BY Ref'
        self._execute(query)
        for row in self._fetchall():
            pairings: dict[int, Pairing] = {}
            for round_ in range(1, rounds + 1):
                round_str = f'Rd{round_:0>2}'
                color: str = row[f'{round_str}Cl']
                with suppress(ValueError):
                    color = Color.from_papi_value(color)
                pairings[round_] = Pairing(
                    color, row[f'{round_str}Adv'],
                    Result.from_papi_value(row[f'{round_str}Res']))
            players[row['Ref']] = Player(
                row['Ref'], row['Nom'] or '', row['Prenom'] or '',
                PlayerGender.from_papi_value(row['Sexe']),
                PlayerTitle.from_papi_value(row['FideTitre']),
                row[tournament_rating.papi_value_field],
                row[tournament_rating.papi_type_field],
                row['Fixe'] == 1,
                row['Pointe'],
                pairings)
        return players

    def add_board_result(self, player_id: int, round_: int, result: Result):
        """Writes the given result to the database."""
        query: str = f'UPDATE `joueur` SET `Rd{round_:0>2}Res` = ? WHERE `Ref` = ?'
        self._execute(query, (result.value, player_id, ))
    
    def remove_board_result(self, player_id: int, round_: int):
        query: str = f'UPDATE `joueur` SET `Rd{round_:0>2}Res` = 0 WHERE `Ref` = ?'
        self._execute(query, (player_id, ))

    @staticmethod
    def _timestamp_to_papi_date(ts: float) -> str:
        dt: datetime
        if ts >= 0:
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime(1970, 1, 1) + timedelta(seconds=ts)
        return dt.strftime('%d/%m/%Y')

    def __write_var(self, name: str, value):
        query: str = 'UPDATE `info` SET `Value` = ? WHERE `Variable` = ?'
        self._execute(query, (value, name, ))

    @property
    def skipped_rounds_dir(self) -> Path:
        return TMP_DIR / 'events' / self.event_id / 'skipped_rounds' / self.tournament_id

    def delete_skipped_rounds(self):
        for file in self.skipped_rounds_dir.glob('*'):
            file.unlink()
        # self.skipped_rounds_dir.unlink(missing_ok=True)

    def store_player_skipped_rounds(self, player_id: int, skipped_rounds: dict[int, float]):
        if skipped_rounds:
            self.skipped_rounds_dir.mkdir(parents=True, exist_ok=True)
            for round_, result in skipped_rounds.items():
                # add a new file
                filename: str = f'{player_id} {round_} {result}'
                skipped_round_file: Path = self.skipped_rounds_dir / filename
                skipped_round_file.touch()
                logger.info('le fichier [%s] a été créé', skipped_round_file)

    def read_tournament_skipped_rounds(self) -> dict[int, dict[int, float]]:
        tournament_skipped_rounds: dict[int, dict[int, float]] = {}
        glob_pattern: str = '*'
        regex = re.compile(r'(\d+) (\d+) (.*)$')
        for file in self.skipped_rounds_dir.glob(glob_pattern):
            if matches := regex.match(file.name):
                player_id: int = int(matches.group(1))
                round: int = int(matches.group(2))
                result: float = float(matches.group(3))
                if player_id not in tournament_skipped_rounds:
                    tournament_skipped_rounds[player_id] = {}
                tournament_skipped_rounds[player_id][round] = result
        return tournament_skipped_rounds

    def read_player_skipped_rounds(self, player_id: int) -> dict[int, float]:
        player_skipped_rounds: dict[int, float] = {}
        glob_pattern: str = f'{player_id} *'
        regex = re.compile(r'(\d+) (\d+) (.*)$')
        for file in self.skipped_rounds_dir.glob(glob_pattern):
            if matches := regex.match(file.name):
                round: int = int(matches.group(2))
                result: float = float(matches.group(3))
                player_skipped_rounds[round] = result
        return player_skipped_rounds

    def write_chessevent_info(self, chessevent_tournament: ChessEventTournament):
        """Writes vars to the database."""
        default_rounds: int = 7
        if not chessevent_tournament.rounds:
            logger.warning(
                'Le nombre de rondes n\'a pas été indiqué sur Chess Event, défini par défaut à %s.',
                default_rounds)
            chessevent_tournament.rounds = default_rounds
        data: dict[str, str | int] = {
            'Nom': chessevent_tournament.name,
            'Genre': chessevent_tournament.type.to_papi_value,
            'NbrRondes': chessevent_tournament.rounds,
            'Pairing': chessevent_tournament.pairing.to_papi_value,
            'Cadence': chessevent_tournament.time_control,
            'Lieu': chessevent_tournament.location,
            'Arbitre': chessevent_tournament.arbiter,
            'DateDebut': self._timestamp_to_papi_date(chessevent_tournament.start),
            'DateFin': self._timestamp_to_papi_date(chessevent_tournament.end),
            'Dep1': chessevent_tournament.tie_breaks[0].to_papi_value,
            'Dep2': chessevent_tournament.tie_breaks[1].to_papi_value,
            'Dep3': chessevent_tournament.tie_breaks[2].to_papi_value,
            'ClassElo': chessevent_tournament.rating.to_papi_value,
            'Homologation': str(chessevent_tournament.ffe_id),
        }
        # queries: list[str] = []
        # params: list[str] = []
        # for name, value in data.items():
        #     queries.append('UPDATE `info` SET `Value` = ? WHERE `Variable` = ?')
        #     params.extend([value, name, ])
        # self._execute('; '.join(queries), tuple(params))
        for name, value in data.items():
            query: str = 'UPDATE `info` SET `Value` = ? WHERE `Variable` = ?'
            self._execute(query, (value, name, ))

    def add_chessevent_player(self, player_id: int, player: ChessEventPlayer, check_in_started: bool):
        """Adds a player to the database."""
        data: dict[str, str | int | float | None] = {
            'Ref': player_id,
            'RefFFE': player.ffe_id,
            'NrFFE': player.ffe_license_number if player.ffe_license_number else None,
            'Nom': player.last_name,
            'Prenom': player.first_name,
            'Sexe': player.gender.to_papi_value,
            'NeLe': self._timestamp_to_papi_date(player.birth),
            'Cat': player.category.to_papi_value,
            'AffType': player.ffe_license.to_papi_value,
            'Elo': player.standard_rating,
            'Rapide': player.rapid_rating,
            'Blitz': player.blitz_rating,
            'Federation': player.federation,
            'ClubRef': player.ffe_club_id,
            'Club': player.ffe_club,
            'Ligue': player.ffe_league,
            'Fide': player.standard_rating_type.to_papi_value,
            'RapideFide': player.rapide_rating_type.to_papi_value,
            'BlitzFide': player.blitz_rating_type.to_papi_value,
            'FideCode': player.fide_id if player.fide_id else None,
            'FideTitre': player.title.to_papi_value,
            'Pointe': check_in_started and player.check_in,
            'InscriptionRegle': player.paid,
            'InscriptionDu': player.fee,
            'Tel': player.phone,
            'EMail': player.email,
            'Fixe': player.board,
            'Flotteur': 'X' * 24,
            'Pts': 0,
            'PtA': 0,
        }
        for round_ in range(1, 25):
            data[f'Rd{round_:0>2}Adv'] = None
            if round_ not in player.skipped_rounds:
                data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                if player.check_in or not check_in_started:
                    data[f'Rd{round_:0>2}Cl'] = 'R'
                else:
                    data[f'Rd{round_:0>2}Cl'] = 'F'
            else:
                data[f'Rd{round_:0>2}Cl'] = 'F'
                match player.skipped_rounds[round_]:
                    case 0.0:
                        data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                    case 0.5:
                        data[f'Rd{round_:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                    case _:
                        raise ValueError
        query: str = f'INSERT INTO `joueur`({", ".join(data.keys())}) VALUES ({", ".join(["?"] * len(data))})'
        params = tuple(data.values())
        self._execute(query, params)

    def delete_players_personal_data(self):
        """Delete all personal data from the database."""
        query: str = 'UPDATE `joueur` SET Tel = ?, EMail = ?'
        self._execute(query, ('', '', ))

    def get_checked_in_players_number(self) -> int:
        """Return the number players already checked in."""
        query: str = 'SELECT COUNT(`Ref`) FROM `joueur` WHERE `Pointe` AND `Ref` > 1'
        self._execute(query)
        return self._fetchval()

    def _check_in_player(self, player_id: int):
        logger.debug('Checking in player %d', player_id)
        checked_in_players_number: int = self.get_checked_in_players_number()
        player_skipped_rounds: dict[int, float]
        if not checked_in_players_number:
            logger.debug('set all players forfeit for all rounds (except player %d)', player_id)
            data: dict[str, str | int | float | None] = {
            }
            for round_ in range(1, 25):
                data[f'Rd{round_:0>2}Adv'] = None
                data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                data[f'Rd{round_:0>2}Cl'] = 'F'
            actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
            query: str = f'UPDATE `joueur` SET {actions} WHERE Ref NOT IN (1, ?)'
            params = tuple(list(data.values()) + [player_id, ])
            self._execute(query, params)
            # set byes (no need for forfeits, already set)
            tournament_skipped_rounds: dict[int, dict[int, float]] = self.read_tournament_skipped_rounds()
            player_skipped_rounds: dict[int, float] = tournament_skipped_rounds.get(player_id, [])
            for other_player_id in tournament_skipped_rounds:
                if other_player_id != player_id:
                    data: dict[str, str | int | float | None] = {
                    }
                    for round_, result in tournament_skipped_rounds[other_player_id].items():
                        if round_ in range(1, 25):
                            match result:
                                case 0.0:
                                    pass
                                case 0.5:
                                    data[f'Rd{round_:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                                case _:
                                    raise ValueError
                    if data:
                        logger.debug('set byes for player %d: %s', other_player_id, data)
                        actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
                        query: str = f'UPDATE `joueur` SET {actions} WHERE Ref = ?'
                        params = tuple(list(data.values()) + [other_player_id, ])
                        self._execute(query, params)
                    else:
                        logger.debug('no byes for player %d', other_player_id)
                else:
                    logger.debug('do skipped round for player %d', other_player_id)
        else:
            player_skipped_rounds = self.read_player_skipped_rounds(player_id)
        # Set the player checked in and unpaired for all rounds
        logger.debug('byes and forfeits for player %d: %s', player_id, player_skipped_rounds)
        logger.debug('Set player %d checked in and unpaired for all rounds', player_id)
        data: dict[str, str | int | float | None] = {
            'Pointe': True,
        }
        for round_ in range(1, 25):
            data[f'Rd{round_:0>2}Adv'] = None
            if round_ not in player_skipped_rounds:
                data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                data[f'Rd{round_:0>2}Cl'] = 'R'
            else:
                data[f'Rd{round_:0>2}Cl'] = 'F'
                match player_skipped_rounds[round_]:
                    case 0.0:
                        data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                    case 0.5:
                        data[f'Rd{round_:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                    case _:
                        raise ValueError
        actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
        query: str = f'UPDATE `joueur` SET {actions} WHERE Ref = ?'
        params = tuple(list(data.values()) + [player_id, ])
        self._execute(query, params)

    def _check_out_player(self, player_id: int):
        logger.debug('Checking out player %s', player_id)
        checked_in_players_number: int = self.get_checked_in_players_number()
        if checked_in_players_number == 1:
            logger.debug('set all players unpaired for all rounds')
            data: dict[str, str | int | float | None] = {
                'Pointe': False,
            }
            for round_ in range(1, 25):
                data[f'Rd{round_:0>2}Adv'] = None
                data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                data[f'Rd{round_:0>2}Cl'] = 'R'
            actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
            query: str = f'UPDATE `joueur` SET {actions} WHERE Ref > 1'
            params = tuple(list(data.values()))
            self._execute(query, params)
            # set byes and forfeits
            tournament_skipped_rounds: dict[int, dict[int, float]] = self.read_tournament_skipped_rounds()
            for other_player_id, player_skipped_rounds in tournament_skipped_rounds.items():
                data: dict[str, str | int | float | None] = {
                }
                for round_, result in player_skipped_rounds.items():
                    if round_ in range(1, 25):
                        data[f'Rd{round_:0>2}Cl'] = 'F'
                        match result:
                            case 0.0:
                                data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                                pass
                            case 0.5:
                                data[f'Rd{round_:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                            case _:
                                raise ValueError
                if data:
                    actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
                    query: str = f'UPDATE `joueur` SET {actions} WHERE Ref = ?'
                    params = tuple(list(data.values()) + [other_player_id, ])
                    self._execute(query, params)
        else:
            logger.debug('Set the player checked out and forfeit for all rounds')
            player_skipped_rounds: dict[int, float] = self.read_player_skipped_rounds(player_id)
            data: dict[str, str | int | float | None] = {
                'Pointe': False,
            }
            for round_ in range(1, 25):
                data[f'Rd{round_:0>2}Adv'] = None
                data[f'Rd{round_:0>2}Cl'] = 'F'
                if round_ not in player_skipped_rounds:
                    data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                else:
                    match player_skipped_rounds[round_]:
                        case 0.0:
                            data[f'Rd{round_:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                        case 0.5:
                            data[f'Rd{round_:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                        case _:
                            raise ValueError
            actions: str = ', '.join([f'`{key}` = ?' for key in data.keys()])
            query: str = f'UPDATE `joueur` SET {actions} WHERE Ref = ?'
            params = tuple(list(data.values()) + [player_id, ])
            self._execute(query, params)

    def check_in_player(self, player_id: int, check_in: bool):
        if check_in:
            self._check_in_player(player_id)
        else:
            self._check_out_player(player_id)
