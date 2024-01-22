from datetime import datetime, timedelta
from pathlib import Path
from logging import Logger
from itertools import product
from typing import NamedTuple, Self
from contextlib import suppress

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

    def __init__(self, file: Path, method: str):
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
        ]
        for rd, suffix in product(range(1, rounds + 1), ['Cl', 'Adv', 'Res']):
            player_fields.append(f'Rd{rd:0>2}{suffix}')
        query: str = f'SELECT {", ".join(player_fields)} FROM joueur ORDER BY Ref'
        self._execute(query)
        for row in self._fetchall():
            pairings: dict[int, Pairing] = {}
            for round in range(1, rounds + 1):
                round_str = f'Rd{round:0>2}'
                color: str = row[f'{round_str}Cl']
                with suppress(ValueError):
                    color = Color.from_papi_value(color)
                pairings[round] = Pairing(
                    color, row[f'{round_str}Adv'],
                    Result.from_papi_value(row[f'{round_str}Res']))
            players[row['Ref']] = Player(
                row['Ref'], row['Nom'] or '', row['Prenom'] or '',
                PlayerGender.from_papi_value(row['Sexe']),
                PlayerTitle.from_papi_value(row['FideTitre']),
                row[tournament_rating.papi_value_field],
                row[tournament_rating.papi_type_field],
                row['Fixe'], pairings)
        return players

    def add_board_result(self, player_id: int, round: int, result: Result):
        """Writes the given result to the database."""
        query: str = f'UPDATE `joueur` SET `Rd{round:0>2}Res` = ? WHERE `Ref` = ?'
        self._execute(query, (result.value, player_id, ))

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

    def write_chessevent_info(self, chessevent_tournament: ChessEventTournament):
        """Writes vars to the database."""
        default_rounds: int = 7
        if not chessevent_tournament.rounds:
            logger.warning(
                f'Le nombre de rondes n\'a pas été indiqué sur Chess Event, défini par défaut à {default_rounds}.')
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
            self._execute('UPDATE `info` SET `Value` = ? WHERE `Variable` = ?', (value, name, ))

    def add_chessevent_player(self, player_id: int, player: ChessEventPlayer):
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
            'Pointe': player.check_in,
            'InscriptionRegle': player.paid,
            'InscriptionDu': player.fee,
            'Tel': player.phone,
            'EMail': player.email,
            'Fixe': player.board,
            'Flotteur': 'X' * 24,
            'Pts': 0,
            'PtA': 0,
        }
        for round in range(1, 25):
            data[f'Rd{round:0>2}Adv'] = None
            if round not in player.skipped_rounds:
                if player.check_in:
                    data[f'Rd{round:0>2}Res'] = Result.NOT_PAIRED.to_papi_value
                    data[f'Rd{round:0>2}Cl'] = 'R'
                else:
                    data[f'Rd{round:0>2}Res'] = Result.FORFEIT_LOSS.to_papi_value
                    data[f'Rd{round:0>2}Cl'] = 'F'
            elif player.skipped_rounds[round] == 0.0:
                data[f'Rd{round:0>2}Res'] = Result.FORFEIT_LOSS.to_papi_value
                data[f'Rd{round:0>2}Cl'] = 'F'
            elif player.skipped_rounds[round] == 0.5:
                data[f'Rd{round:0>2}Res'] = Result.DRAW_OR_HPB.to_papi_value
                data[f'Rd{round:0>2}Cl'] = 'F'
            else:
                raise ValueError
        query: str = f'INSERT INTO `joueur`({", ".join(data.keys())}) VALUES ({", ".join(["?"] * len(data))})'
        params = tuple(data.values())
        self._execute(query, params)

    def delete_players_personal_data(self):
        """Delete all personal data from the database."""
        self._execute('UPDATE `joueur` SET Tel = ?, EMail = ?', ('', '', ))
