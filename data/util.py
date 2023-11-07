"""A file grouping all the "utility" classes/enum: Result, Color, PlayerTitle,
PlayerSex, TournamentPairing, TournamentRating"""

from enum import StrEnum, IntEnum
from typing import Self


class Result(IntEnum):
    """An enum representing the results in the database.
    Should be subclassed if the point value is not the default"""
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
            # NOTE(Amaras) This is not the behaviour from before the refactor
            # TODO(Amaras) ensure this behaviour is the intended one
            case Result.ForfeitLoss:
                return 'F-1'
            case Result.ExeForfeitGainFPB:
                return '1-F'
            case Result.DoubleForfeit:
                return 'F-F'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @classmethod
    def from_db_str(cls, value: str) -> Self:
        """Decode the result value from the result string"""
        match value:
            case '':
                return Result.NotPaired
            case '1-0':
                return Result.Gain
            case '0-1':
                return Result.Loss
            case '1/2':
                return Result.DrawOrHPB
            case '1-F':
                return Result.ExeForfeitGainFPB
            case 'F-1':
                return Result.ForfeitLoss
            case 'F-F':
                return Result.DoubleForfeit
            case _:
                raise ValueError(f'Unknown value: {value}')

    @classmethod
    def from_db_int(cls, value: int) -> Self:
        match value:
            case 0:
                return cls.NotPaired
            case 1:
                return cls.Loss
            case 2:
                return cls.DrawOrHPB
            case 3:
                return cls.Gain
            case 6:
                return cls.ExeForfeitGainFPB
            case 4:
                return cls.ForfeitLoss
            case 5:
                return cls.DoubleForfeit
            case _:
                raise ValueError(f'Unknwon value: {value}')

    @property
    def point_value(self) -> float:
        """
        The default value in points, according to FIDE rules, with a
        full-point Pairing Allocated Bye.
        """
        match self:
            case Result.NotPaired | Result.Loss | Result.ForfeitLoss | Result.DoubleForfeit:
                return 0
            case Result.DrawOrHPB:
                return 0.5
            case Result.Gain | Result.ExeForfeitGainFPB:
                return 1

    def opposite_result(self) -> Self:
        """Given a `Result` instance (white result), returns the result of the
        opponent.

        >>> Result.opposite_result(Result.Gain) == Result.Loss
        True

        >>> Result.opposite_result(Result.Loss) == Result.Gain
        True

        >>> Result.opposite_result(Result.DrawOrHPB) == Result.DrawOrHPB
        True

        >>> Result.opposite_result(Result.NotPaired) == Result.NotPaired
        True
        """
        match self:
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
                raise ValueError(f"Unknown value: {self}")


class TournamentPairing(StrEnum):
    """An enumeration representing the supported types of tournament
    pairings.
    Currently, only Swiss Dutch, along with several accelerations, are supported.
    A project for Berger-paired tournaments is in the TODO list."""
    Standard = 'Standard'
    Haley = 'Haley'
    HaleySoft = 'HaleySoft'
    SAD = 'SAD'
    # Berger = NotImplemented

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
                raise NotImplementedError
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
            # case TournamentPairing.Berger:
                # raise NotImplementedError
            case _:
                raise ValueError('Unknown Pairing Type: {self}')


class PlayerSex(StrEnum):
    M = 'M'
    F = 'F'

    @classmethod
    def from_db(cls, value) -> Self:
        match value:
            case 'M' | 'm':
                return cls.M
            case 'F' | 'f':
                return cls.F
            case _:
                raise ValueError(f'Unknown value: {value}')

    @classmethod
    def from_bd(cls, value: str) -> Self | None:
        match value:
            case 'M':
                return PlayerSex.M
            case 'F':
                return PlayerSex.F
            case '':
                return None
            case _:
                raise ValueError(f'Unknown value: {value}')


class PlayerTitle(IntEnum):
    """The possible FIDE titles: GM, WGM, IM, WIM, FM, WFM.
    Also includes the "no title" case, but does not include CM nor WCM."""
    g = 6
    gf = 5
    m = 4
    mf = 3
    f = 2
    ff = 1
    no = 0

    @classmethod
    def from_db(cls, value: int) -> Self:
        match value:
            case 0:
                return PlayerTitle.no
            case 1:
                return PlayerTitle.ff
            case 2:
                return PlayerTitle.f
            case 3:
                return PlayerTitle.mf
            case 4:
                return PlayerTitle.m
            case 5:
                return PlayerTitle.gf
            case 6:
                return PlayerTitle.g
            case _:
                raise ValueError(f"Unknown title value: {value}")

    @classmethod
    def from_db_str(cls, value) -> Self:
        match value:
            case '':
                return cls.no
            case 'ff':
                return cls.ff
            case 'f':
                return cls.f
            case 'mf':
                return cls.mf
            case 'm':
                return cls.m
            case 'gf':
                return cls.gf
            case 'g':
                return cls.g
            case _:
                raise ValueError(f'Unknown title: {value}')

    def __str__(self):
        if self == PlayerTitle.no:
            return ''
        return f'{self.name}'


class Color(StrEnum):
    White = 'W'
    Black = 'B'

    def __str__(self):
        match self:
            case Color.White:
                return 'Blancs'
            case Color.Black:
                return 'Noirs'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @property
    def db_value(self):
        match self:
            case Color.White:
                return 'B'
            case Color.Black:
                return 'N'
            case _:
                raise ValueError(f'Unknown value:  {self}')

    @classmethod
    def from_db(cls, value: str) -> Self:
        """Decode the database value"""
        match value:
            case 'B':
                return Color.White
            case 'N':
                return Color.Black
            case _:
                raise ValueError(f'Unknown value: {value}')
