from pathlib import Path
from logging import Logger
from enum import Enum, StrEnum
from itertools import product
from typing import NamedTuple

from database.access import AccessDatabase
from data.pairing import Pairing
from data.player import Player, PLAYER_TITLE_VALUES, COLOR_DB_VALUES
from common.logger import get_logger

logger: Logger = get_logger()


class Result(Enum):
    NotPaired = 0
    Loss = 1
    DrawOrHPB = 2
    Gain = 3
    ForfeitLoss = 4
    DoubleForfeit = 5
    ExeForfeitGainFPB = 6

    def __str__(self):
        match self:
            case Result.Gain:
                return '1-0'
            case Result.Loss:
                return '0-1'
            case Result.DrawOrHPB:
                return '1/2'
            case Result.NotPaired:
                return ''
            case Result.ForfeitLoss:
                return '1-F'
            case Result.ExeForfeitGainFPB:
                return '1-F'
            case Result.DoubleForfeit:
                return 'F-F'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @staticmethod
    def opposite_result(self, white_result: Result) -> Result:
        match white_result:
            case Result.Loss:
                return Result.Gain
            case Result.Gain:
                return Result.Loss
            case Result.DrawOrHPB:
                return Result.DrawOrHPB
            case Result.ExeForfeitGainFPB:
                return Result.ForfeitLoss
            case Result.ForfeitLoss:
                return Result.ExeForfeitGainFPB
            case Result.DoubleForfeit:
                return Result.DoubleForfeit
            case Result.NotPaired:
                return Result.NotPaired
            case _:
                raise ValueError(f"Unknown value: {white_result}")


RESULT_NOT_PAIRED: int = 0              # forfeit (opp is None, not paired)
RESULT_LOSS: int = 1                    # loss (opp > 1)
RESULT_DRAW_OR_BYE_05: int = 2          # draw (opp > 1) or bye 0.5pt (opp is None)
RESULT_GAIN: int = 3                    # won (opp > 1)
RESULT_FORFEIT_LOSS: int = 4            # forfeit (opp > 1, paired)
RESULT_DOUBLE_FORFEIT: int = 5          # double forfeit (opp > 1)
RESULT_EXE_FORFEIT_GAIN_BYE_1: int = 6  # exempt (opp == 1), forfeit won (opp > 1), bye 1pt (opp is None)

RESULT_STRINGS: dict[int, str] = {
    RESULT_NOT_PAIRED: '',
    RESULT_LOSS: '0-1',
    RESULT_DRAW_OR_BYE_05: '1/2',
    RESULT_GAIN: '1-0',
    RESULT_FORFEIT_LOSS: '1-F',
    RESULT_DOUBLE_FORFEIT: 'F-F',
    RESULT_EXE_FORFEIT_GAIN_BYE_1: '1-F',
}


class TournamentPairing(StrEnum):
    Standard = 'Standard'
    Haley = 'Haley'
    HaleySoft = 'HaleySoft'
    SAD = 'SAD'
    Berger = NotImplemented

    @classmethod
    def from_db(cls, value):
        match value:
            case 'Standard':
                return cls.Standard
            case 'SAD':
                return cls.SAD
            case 'Haley':
                return cls.Haley
            case 'HaleySoft':
                return cls.HaleySoft
            case 'Berger':
                return cls.Berger
            case _:
                raise ValueError('Unknown value: {value}')

    def __str__(self):
        match self:
            case TournamentPairing.Standard:
                return 'Standard'
            case TournamentPairing.Haley:
                return 'Haley'
            case TournamentPairing.HaleySoft:
                return 'Haley Dégressif'
            case TournamentPairing.SAD:
                return 'Système Accéléré Dégressif'
            case TournamentPairing.Berger:
                raise NotImplementedError
            case _:
                raise ValueError('Unknown Pairing Type: {self}')


TOURNAMENT_PAIRING_STANDARD: int = 1
TOURNAMENT_PAIRING_HALEY: int = 2
TOURNAMENT_PAIRING_HALEY_SOFT: int = 3
TOURNAMENT_PAIRING_SAD: int = 4
TOURNAMENT_PAIRING_DB_VALUES: dict[int, str] = {
    TOURNAMENT_PAIRING_STANDARD: 'Standard',
    TOURNAMENT_PAIRING_HALEY: 'Haley',
    TOURNAMENT_PAIRING_HALEY_SOFT: 'HaleySoft',
    TOURNAMENT_PAIRING_SAD: 'SAD',
}
TOURNAMENT_PAIRING_VALUES: dict[str, int] = {v: k for k, v in TOURNAMENT_PAIRING_DB_VALUES.items()}
TOURNAMENT_PAIRING_STRINGS: dict[int, str] = {
    TOURNAMENT_PAIRING_STANDARD: 'Standard',
    TOURNAMENT_PAIRING_HALEY: 'Haley',
    TOURNAMENT_PAIRING_HALEY_SOFT: 'Haley Dégressif',
    TOURNAMENT_PAIRING_SAD: 'Système Accéléré Dégressif',
}


class TournamentRating(StrEnum):
    Standard = 'Standard'
    Rapid = 'Rapide'
    Blitz = 'Blitz'

    @classmethod
    def from_db(cls, value):
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

    def __init__(self, file: Path):
        super().__init__(file)

    def _query(self, query: str, params: tuple = ()):
        self._execute(query, params)
        self._commit()

    def close(self):
        self._close()

    def __read_var(self, name) -> str:
        query: str = 'SELECT Value FROM INFO WHERE Variable = ?'
        self._execute(query, (name, ))
        return self._fetchval()

    def read_info(self) -> TournamentInfo:
        rounds: int = int(self.__read_var('NbrRondes'))
        pairing: int = TournamentRating.from_db(self.__read_var('Pairing'))
        rating: int = TournamentRating.from_db(self.__read_var('ClassElo'))
        rating_limit1: int = int(self.__read_var('EloBase1'))
        rating_limit2: int = int(self.__read_var('EloBase2'))
        return TournamentInfo(rounds, pairing, rating, rating_limit1, rating_limit2)

    def read_players(self, rating: int, rounds: int) -> dict[int, Player]:
        players: dict[int, Player] = {}
        player_fields: list[str] = [
            'Ref', 'Nom', 'Prenom', 'Sexe', 'FideTitre', 'Fixe',
            'Elo', 'Rapide', 'Blitz', 'Fide', 'RapideFide', 'BlitzFide',
        ]
        for rd, suffix in product(range(1, rounds + 1),  ['Cl', 'Adv', 'Res']):
            player_fields.append(f'Rd{rd:0>2}{suffix}')
        query: str = f'SELECT {", ".join(player_fields)} FROM joueur ORDER BY Ref'
        self._execute(query)
        for row in self._fetchall():
            pairings: dict[int, Pairing] = {}
            for round in range(1, rounds + 1):
                round_str = f'Rd{round:0>2}'
                color: str = row[f'{round_str}Cl']
                if color in COLOR_DB_VALUES:
                    color = COLOR_DB_VALUES[color]
                pairings[round] = Pairing(
                    color, row[f'{round_str}Adv'],
                    row[f'{round_str}Res'])
            players[row['Ref']] = Player(
                row['Ref'], row['Nom'] or '', row['Prenom'] or '', row['Sexe'],
                PLAYER_TITLE_VALUES[row['FideTitre'].strip()],
                row[TOURNAMENT_RATING_DB_FIELDS[rating]],
                row[TOURNAMENT_RATING_TYPE_DB_FIELDS[rating]],
                row['Fixe'], pairings)
        return players

    def add_result(self, player_id: int, round: int, result: Result):
        query: str = f'UPDATE joueur SET Rd{round:0>2}Res = ? WHERE Ref = ?'
        self._query(query, (result.value, player_id, ))
