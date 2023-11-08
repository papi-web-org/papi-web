from pathlib import Path
from logging import Logger
from enum import Enum, StrEnum
from itertools import product
from typing import NamedTuple, Self
from contextlib import suppress

from database.access import AccessDatabase
from data.pairing import Pairing
from data.player import Player
from common.logger import get_logger

from data.util import Result, TournamentPairing, PlayerSex, PlayerTitle, Color

logger: Logger = get_logger()

RESULT_LOSS = Result.Loss
RESULT_GAIN = Result.Gain
RESULT_DRAW_OR_BYE_05 = Result.DrawOrHPB


class TournamentRating(StrEnum):
    Standard = 'Standard'
    Rapid = 'Rapide'
    Blitz = 'Blitz'

    @classmethod
    def from_db(cls, value) -> Self:
        match value:
            case 'Standard':
                return cls.Standard
            case 'Rapide':
                return cls.Rapid
            case 'Blitz':
                return cls.Blitz
            case _:
                raise ValueError(f'Unknown value: {value}')

    @classmethod
    def from_db_field(cls, value):
        match value:
            case 'Elo':
                return cls.Standard
            case 'Rapide':
                return cls.Rapid
            case 'Blitz':
                return cls.Blitz
            case _:
                raise ValueError(f"Unknown value: {value}")

    @property
    def db_field(self):
        match self:
            case TournamentRating.Standard:
                return 'Elo'
            case TournamentRating.Rapid:
                return 'Rapide'
            case TournamentRating.Blitz:
                return 'Blitz'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @property
    def db_field_type(self):
        match self:
            case TournamentRating.Standard:
                return 'Fide'
            case TournamentRating.Rapid:
                return 'RapideFide'
            case TournamentRating.Blitz:
                return 'BlitzFide'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @classmethod
    def from_db_int(cls, value) -> Self:
        match value:
            case 1:
                return cls.Standard
            case 2:
                return cls.Rapid
            case 3:
                return cls.Blitz
            case _:
                raise ValueError(f'Unknown value:  {value}')


TOURNAMENT_RATING_STANDARD: int = 1
TOURNAMENT_RATING_RAPID: int = 2
TOURNAMENT_RATING_BLITZ: int = 3
TOURNAMENT_RATING_DB_FIELDS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Elo',
    TOURNAMENT_RATING_RAPID: 'Rapide',
    TOURNAMENT_RATING_BLITZ: 'Blitz',
}
TOURNAMENT_RATING_VALUES: dict[str, int] = {v: k for k, v in TOURNAMENT_RATING_DB_FIELDS.items()}
TOURNAMENT_RATING_STRINGS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Standard',
    TOURNAMENT_RATING_RAPID: 'Rapide',
    TOURNAMENT_RATING_BLITZ: 'Blitz',
}
TOURNAMENT_RATING_TYPE_DB_FIELDS: dict[int, str] = {
    TOURNAMENT_RATING_STANDARD: 'Fide',
    TOURNAMENT_RATING_RAPID: 'RapideFide',
    TOURNAMENT_RATING_BLITZ: 'BlitzFide',
}


class TournamentInfo(NamedTuple):
    rounds: int
    pairing: TournamentPairing
    rating: TournamentRating
    rating_limit1: int
    rating_limit2: int


class PapiDatabase(AccessDatabase):
    """The database class, using the Papi format of the French Chess Federation
    Tournament manager."""

    def __init__(self, file: Path):
        super().__init__(file)

    def __enter__(self):
        super().enter()

    def __exit__(self, exc_type, exc_value, traceback):
        self._close()

    def _query(self, query: str, params: tuple = ()):
        self._execute(query, params)
        self._commit()

    def close(self):
        self._close()

    def __read_var(self, name) -> str:
        query: str = 'SELECT Value FROM INFO WHERE Variable = ?'
        self._execute(query, (name,))
        return self._fetchval()

    def read_info(self) -> TournamentInfo:
        """Reads the dabase and returns basic information about the
        tournament."""
        rounds: int = int(self.__read_var('NbrRondes'))
        pairing = TournamentPairing.from_db(self.__read_var('Pairing'))
        rating = TournamentRating.from_db_field(self.__read_var('ClassElo'))
        rating_limit1: int = int(self.__read_var('EloBase1'))
        rating_limit2: int = int(self.__read_var('EloBase2'))
        return TournamentInfo(rounds, pairing, rating, rating_limit1, rating_limit2)

    def read_players(self, rating: int, rounds: int) -> dict[int, Player]:
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
                    color = Color.from_db(color)
                pairings[round] = Pairing(
                    color, row[f'{round_str}Adv'],
                    Result.from_db_int(row[f'{round_str}Res']))
            players[row['Ref']] = Player(
                row['Ref'], row['Nom'] or '', row['Prenom'] or '',
                PlayerSex.from_db(row['Sexe']),
                PlayerTitle.from_db_str(row['FideTitre'].strip()),
                row[TournamentRating.from_db(rating).db_field],
                row[TournamentRating.from_db(rating).db_field_type],
                row['Fixe'], pairings)
        return players

    def add_result(self, player_id: int, round: int, result: Result):
        """Writes the given result to the database."""
        query: str = f'UPDATE joueur SET Rd{round:0>2}Res = ? WHERE Ref = ?'
        self._query(query, (result.value, player_id,))
