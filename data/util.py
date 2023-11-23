"""A file grouping all the "utility" classes/enum: Result, Color, PlayerTitle,
PlayerSex, TournamentPairing, TournamentRating"""

from enum import StrEnum, IntEnum, auto
from logging import Logger
from typing import Self

from common.logger import get_logger

logger: Logger = get_logger()


class Result(IntEnum):
    """An enum representing the results in the database.
    Should be subclassed if the point value is not the default"""
    NOT_PAIRED = 0
    LOSS = 1
    DRAW_OR_HPB = 2  # HPB = Halp Point Bye
    GAIN = 3
    FORFEIT_LOSS = 4
    DOUBLE_FORFEIT = 5
    PAB_OR_FORFEIT_GAIN_OR_FPB = 6  # PAB = Pairing-Allocated-Bye, FPB = Full Point Bye

    def __str__(self) -> str:
        match self:
            case Result.GAIN:
                return '1-0'
            case Result.LOSS:
                return '0-1'
            case Result.DRAW_OR_HPB:
                return '1/2'
            case Result.NOT_PAIRED:
                return ''
            case Result.FORFEIT_LOSS:
                return 'F-1'
            case Result.PAB_OR_FORFEIT_GAIN_OR_FPB:
                return '1-F'
            case Result.DOUBLE_FORFEIT:
                return 'F-F'
            case _:
                raise ValueError(f'Unknown value: {self}')

    ''' TODO remove this method (seems to be unused)
    @classmethod
    def from_db_str(cls, value: str) -> Self:
        """Decode the result value from the result string"""
        match value:
            case '':
                return Result.NOT_PAIRED
            case '1-0':
                return Result.GAIN
            case '0-1':
                return Result.LOSS
            case '1/2':
                return Result.DRAW_OR_HPB
            case '1-F':
                return Result.PAB_OR_FORFEIT_GAIN_OR_FPB
            case 'F-1':
                return Result.FORFEIT_LOSS
            case 'F-F':
                return Result.DOUBLE_FORFEIT
            case _:
                raise ValueError(f'Unknown value: {value}')'''

    @classmethod
    def from_papi_value(cls, value: int) -> Self:
        match value:
            case 0:
                return cls.NOT_PAIRED
            case 1:
                return cls.LOSS
            case 2:
                return cls.DRAW_OR_HPB
            case 3:
                return cls.GAIN
            case 6:
                return cls.PAB_OR_FORFEIT_GAIN_OR_FPB
            case 4:
                return cls.FORFEIT_LOSS
            case 5:
                return cls.DOUBLE_FORFEIT
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> int:
        return self.value

    @property
    def point_value(self) -> float:
        """
        The default value in points, according to FIDE rules, with a
        full-point Pairing Allocated Bye.
        """
        match self:
            case Result.NOT_PAIRED | Result.LOSS | Result.FORFEIT_LOSS | Result.DOUBLE_FORFEIT:
                return 0.0
            case Result.DRAW_OR_HPB:
                return 0.5
            case Result.GAIN | Result.PAB_OR_FORFEIT_GAIN_OR_FPB:
                return 1.0

    @property
    def opposite_result(self) -> Self:
        """Given a `Result` instance (white result), returns the result of the
        opponent.

        >>> Result.GAIN.opposite_result == Result.LOSS
        True

        >>> Result.LOSS.opposite_result == Result.GAIN
        True

        >>> Result.DRAW_OR_HPB.opposite_result == Result.DRAW_OR_HPB
        True

        >>> Result.NOT_PAIRED.opposite_result == Result.NOT_PAIRED
        True
        """
        match self:
            case Result.LOSS:
                return Result.GAIN
            case Result.GAIN:
                return Result.LOSS
            case Result.DRAW_OR_HPB:
                return Result.DRAW_OR_HPB
            case Result.PAB_OR_FORFEIT_GAIN_OR_FPB:
                return Result.FORFEIT_LOSS
            case Result.FORFEIT_LOSS:
                return Result.PAB_OR_FORFEIT_GAIN_OR_FPB
            case Result.DOUBLE_FORFEIT:
                return Result.DOUBLE_FORFEIT
            case Result.NOT_PAIRED:
                return Result.NOT_PAIRED
            case _:
                raise ValueError(f"Unknown value: {self}")

    @classmethod
    def imputable_results(cls) -> tuple[Self, Self, Self]:
        return cls.GAIN, cls.DRAW_OR_HPB, cls.LOSS


class TournamentType(IntEnum):
    """An enumeration representing the supported types of tournaments."""
    UNKNOWN = 0
    SWISS = 1
    CHAMPIONSHIP = 2

    @classmethod
    def from_papi_value(cls, value) -> Self:
        match value:
            case 'Suisse':
                return cls.SWISS
            case 'ToutesRondes':
                return cls.CHAMPIONSHIP
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case TournamentType.SWISS:
                return 'Suisse'
            case TournamentType.CHAMPIONSHIP:
                return 'ToutesRondes'
            case _:
                raise ValueError(f'Unknown tie break: {self}')

    def __str__(self) -> str:
        match self:
            case TournamentType.UNKNOWN:
                return 'Inconnu'
            case TournamentType.SWISS:
                return 'Système suisse'
            case TournamentType.CHAMPIONSHIP:
                return 'Toutes rondes'
            case _:
                raise ValueError(f'Unknown tie break: {self}')


class TournamentRating(IntEnum):
    UNKNOWN = 0
    STANDARD = 1
    RAPID = 2
    BLITZ = 3

    @classmethod
    def from_papi_value(cls, value) -> Self:
        match value:
            case 'Elo':
                return cls.STANDARD
            case 'Rapide':
                return cls.RAPID
            case 'Blitz':
                return cls.BLITZ
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case TournamentRating.STANDARD:
                return 'Elo'
            case TournamentRating.RAPID:
                return 'Rapide'
            case TournamentRating.BLITZ:
                return 'Blitz'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @property
    def papi_value_field(self) -> str:
        match self:
            case TournamentRating.UNKNOWN:
                return 'Inconnu'
            case TournamentRating.STANDARD:
                return 'Elo'
            case TournamentRating.RAPID:
                return 'Rapide'
            case TournamentRating.BLITZ:
                return 'Blitz'
            case _:
                raise ValueError(f'Unknown value: {self}')

    @property
    def papi_type_field(self) -> str:
        match self:
            case TournamentRating.STANDARD:
                return 'Fide'
            case TournamentRating.RAPID:
                return 'RapideFide'
            case TournamentRating.BLITZ:
                return 'BlitzFide'
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case TournamentRating.STANDARD:
                return 'Classement standard'
            case TournamentRating.RAPID:
                return 'Classement rapide'
            case TournamentRating.BLITZ:
                return 'Classement blitz'
            case _:
                raise ValueError(f'Unknown rating: {self}')


class TournamentPairing(IntEnum):
    """An enumeration representing the supported types of tournament
    pairings.
    Currently, only Swiss Dutch, along with several accelerations, are supported.
    A project for Berger-paired tournaments is in the TODO list."""
    # NOTE(PA) never thought of it because Berger-paired tournaments can be managed in Papi by
    # Berger-pairing all the rounds and setting the pairing-type back to Swiss in the end.
    # NOTE(Amaras) Based on your remark, this sounds like a bad API design which
    # is why I thought about doing something to make it better.
    UNKNOWN = 0
    STANDARD = 1
    HALEY = 2
    HALEY_SOFT = 3
    SAD = 4
    NICOIS = 5
    BERGER = 6

    @classmethod
    def from_papi_value(cls, value) -> Self:
        match value:
            case 'Standard':
                return cls.STANDARD
            case 'Haley':
                return cls.HALEY
            case 'HaleySoft':
                return cls.HALEY_SOFT
            case 'SAD':
                return cls.SAD
            case 'Nicois':
                return cls.NICOIS
            case 'Berger':
                raise NotImplementedError
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case TournamentPairing.STANDARD:
                return 'Standard'
            case TournamentPairing.HALEY:
                return 'Haley'
            case TournamentPairing.HALEY_SOFT:
                return 'HaleySoft'
            case TournamentPairing.SAD:
                return 'SAD'
            case TournamentPairing.NICOIS:
                return 'Nicois'
            case TournamentPairing.BERGER:
                raise NotImplementedError
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case TournamentPairing.UNKNOWN:
                return 'Inconnu'
            case TournamentPairing.STANDARD:
                return 'Système suisse standard'
            case TournamentPairing.HALEY:
                return 'Système de Haley'
            case TournamentPairing.HALEY_SOFT:
                return 'Système de Haley dégressif'
            case TournamentPairing.SAD:
                return 'Système accéléré dégressif (SAD)'
            case TournamentPairing.NICOIS:
                return 'Système accéléré niçois'
            case TournamentPairing.BERGER:
                raise NotImplementedError
            case _:
                raise ValueError(f'Unknown pairing type: {self}')


class TournamentTieBreak(IntEnum):
    """An enumeration representing the supported types of tournament
    tie breaks."""
    NONE = 0
    BUCHHOLZ = 1
    BUCHHOLZ_CUT_TOP = 2
    BUCHHOLZ_CUT_TOP_BOTTOM = 3
    CUMULATIVE = 4
    PERFORMANCE = 5
    BUCHHOLZ_SUM = 6
    WINS = 7
    KASHDAN = 8
    KOYA = 9
    SONNENBORN_BERGER = 10

    @classmethod
    def from_papi_value(cls, value) -> Self:
        match value:
            case '':
                return cls.NONE
            case 'Solkoff':
                return cls.BUCHHOLZ
            case 'Brésilien':
                return cls.BUCHHOLZ_CUT_TOP
            case 'Harkness':
                return cls.BUCHHOLZ_CUT_TOP_BOTTOM
            case 'Cumulatif':
                return cls.CUMULATIVE
            case 'Performance':
                return cls.PERFORMANCE
            case 'SommeDesBuchholz':
                return cls.BUCHHOLZ_SUM
            case 'Nombre de Victoires':
                return cls.WINS
            case 'Kashdan':
                return cls.KASHDAN
            case 'Koya':
                return cls.KOYA
            case 'Sonnenborn-Berger':
                return cls.SONNENBORN_BERGER
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case TournamentTieBreak.NONE:
                return ''
            case TournamentTieBreak.BUCHHOLZ:
                return 'Solkoff'
            case TournamentTieBreak.BUCHHOLZ_CUT_TOP:
                return 'Brésilien'
            case TournamentTieBreak.BUCHHOLZ_CUT_TOP_BOTTOM:
                return 'Harkness'
            case TournamentTieBreak.CUMULATIVE:
                return 'Cumulatif'
            case TournamentTieBreak.PERFORMANCE:
                return 'Performance'
            case TournamentTieBreak.BUCHHOLZ_SUM:
                return 'SommeDesBuchholz'
            case TournamentTieBreak.WINS:
                return 'Nombre de Victoires'
            case TournamentTieBreak.KASHDAN:
                return 'Kashdan'
            case TournamentTieBreak.KOYA:
                return 'Koya'
            case TournamentTieBreak.SONNENBORN_BERGER:
                return 'Sonnenborn-Berger'
            case _:
                raise ValueError(f'Unknown tie break: {self}')

    def __str__(self) -> str:
        match self:
            case TournamentTieBreak.NONE:
                return 'Aucun'
            case TournamentTieBreak.BUCHHOLZ:
                return 'Buchholz'
            case TournamentTieBreak.BUCHHOLZ_CUT_TOP:
                return 'Buchholz tronqué'
            case TournamentTieBreak.BUCHHOLZ_CUT_TOP_BOTTOM:
                return 'Buchholz médian'
            case TournamentTieBreak.CUMULATIVE:
                return 'Cumulatif'
            case TournamentTieBreak.PERFORMANCE:
                return 'Performance'
            case TournamentTieBreak.BUCHHOLZ_SUM:
                return 'Somme des buchholz'
            case TournamentTieBreak.WINS:
                return 'Nombre de victoire'
            case TournamentTieBreak.KASHDAN:
                return 'Kashdan'
            case TournamentTieBreak.KOYA:
                return 'Koya'
            case TournamentTieBreak.SONNENBORN_BERGER:
                return 'Sonnenborn-Berger'
            case _:
                raise ValueError(f'Unknown tie break: {self}')


class PlayerGender(IntEnum):
    NONE = 0
    FEMALE = 1
    MALE = 2

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        match value:
            case '':
                return cls.NONE
            case 'F' | 'f':
                return cls.FEMALE
            case 'M' | 'm':
                return cls.MALE
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case PlayerGender.NONE:
                return ''
            case PlayerGender.FEMALE:
                return 'F'
            case PlayerGender.MALE:
                return 'M'
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case PlayerGender.NONE:
                return 'Aucun'
            case PlayerGender.FEMALE:
                return 'Femme'
            case PlayerGender.MALE:
                return 'Homme'
            case _:
                raise ValueError(f'Unknown value: {self}')


class PlayerLicense(IntEnum):
    NONE = 0
    N = 1
    B = 2
    A = 3

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        match value:
            case '':
                return cls.NONE
            case 'N':
                return cls.N
            case 'B':
                return cls.B
            case 'A':
                return cls.A
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case PlayerLicense.NONE:
                return ''
            case PlayerLicense.N:
                return 'N'
            case PlayerLicense.B:
                return 'B'
            case PlayerLicense.A:
                return 'A'
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case PlayerLicense.NONE:
                return 'Aucune'
            case PlayerLicense.N:
                return 'Licence non renouvelée'
            case PlayerLicense.B:
                return 'Licence B'
            case PlayerLicense.A:
                return 'Licence A'
            case _:
                raise ValueError(f'Unknown value: {self}')


class PlayerCategory(IntEnum):
    NONE = 0
    U8 = 1
    U10 = 2
    U12 = 3
    U14 = 4
    U16 = 5
    U18 = 6
    U20 = 7
    Sen = 8
    Sep = 9
    Vet = 10

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        match value:
            case '':
                return cls.NONE
            case 'Ppo':
                return cls.U8
            case 'Pou':
                return cls.U10
            case 'Pup':
                return cls.U12
            case 'Ben':
                return cls.U14
            case 'Min':
                return cls.U16
            case 'Cad':
                return cls.U18
            case 'Jun':
                return cls.U20
            case 'Sen':
                return cls.Sen
            case 'Sep':
                return cls.Sep
            case 'Vet':
                return cls.Vet
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case PlayerCategory.NONE:
                return ''
            case PlayerCategory.U8:
                return 'Ppo'
            case PlayerCategory.U10:
                return 'Pou'
            case PlayerCategory.U12:
                return 'Pup'
            case PlayerCategory.U14:
                return 'Ben'
            case PlayerCategory.U16:
                return 'Min'
            case PlayerCategory.U18:
                return 'Cad'
            case PlayerCategory.U20:
                return 'Jun'
            case PlayerCategory.Sen:
                return 'Sen'
            case PlayerCategory.Sep:
                return 'Sep'
            case PlayerCategory.Vet:
                return 'Vet'
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case PlayerCategory.NONE:
                return ''
            case PlayerCategory.U8:
                return 'U8'
            case PlayerCategory.U10:
                return 'U10'
            case PlayerCategory.U12:
                return 'U12'
            case PlayerCategory.U14:
                return 'U14'
            case PlayerCategory.U16:
                return 'U16'
            case PlayerCategory.U18:
                return 'U18'
            case PlayerCategory.U20:
                return 'U20'
            case PlayerCategory.Sen:
                return 'Sen'
            case PlayerCategory.Sep:
                return 'Sep'
            case PlayerCategory.Vet:
                return 'Vet'
            case _:
                raise ValueError(f'Unknown value: {self}')


class PlayerRatingType(IntEnum):
    NONE = 0
    ESTIMATED = 1
    NATIONAL = 2
    FIDE = 3

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        match value:
            case '':
                return cls.NONE
            case 'E':
                return cls.ESTIMATED
            case 'N':
                return cls.NATIONAL
            case 'F':
                return cls.FIDE
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case PlayerRatingType.NONE:
                return ''
            case PlayerRatingType.ESTIMATED:
                return 'E'
            case PlayerRatingType.NATIONAL:
                return 'N'
            case PlayerRatingType.FIDE:
                return 'F'
            case _:
                raise ValueError(f'Unknown value: {self}')

    def __str__(self) -> str:
        match self:
            case PlayerRatingType.NONE:
                return ''
            case PlayerRatingType.ESTIMATED:
                return 'E'
            case PlayerRatingType.NATIONAL:
                return 'N'
            case PlayerRatingType.FIDE:
                return 'F'
            case _:
                raise ValueError(f'Unknown value: {self}')


class PlayerTitle(IntEnum):
    """The possible FIDE titles: GM, WGM, IM, WIM, FM, WFM.
    Also includes the "no title" case, but does not include CM nor WCM."""
    GRANDMASTER = 6
    WOMAN_GRANDMASTER = 5
    INTERNATIONAL_MASTER = 4
    WOMAN_INTERNATIONAL_MASTER = 3
    FIDE_MASTER = 2
    WOMAN_FIDE_MASTER = 1
    NONE = 0

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        match value.strip():
            case '':
                return PlayerTitle.NONE
            case 'ff':
                return PlayerTitle.WOMAN_FIDE_MASTER
            case 'f':
                return PlayerTitle.FIDE_MASTER
            case 'mf':
                return PlayerTitle.WOMAN_INTERNATIONAL_MASTER
            case 'm':
                return PlayerTitle.INTERNATIONAL_MASTER
            case 'gf':
                return PlayerTitle.WOMAN_GRANDMASTER
            case 'g':
                return PlayerTitle.GRANDMASTER
            case _:
                raise ValueError(f"Unknown title value: {value}")

    @property
    def to_papi_value(self) -> str:
        match self:
            case PlayerTitle.NONE:
                return ''
            case PlayerTitle.WOMAN_FIDE_MASTER:
                return 'ff'
            case PlayerTitle.FIDE_MASTER:
                return 'f'
            case PlayerTitle.WOMAN_INTERNATIONAL_MASTER:
                return 'mf'
            case PlayerTitle.INTERNATIONAL_MASTER:
                return 'm'
            case PlayerTitle.WOMAN_GRANDMASTER:
                return 'gf'
            case PlayerTitle.GRANDMASTER:
                return 'g'
            case _:
                raise ValueError(f'Unknown title: {self}')

    def __str__(self) -> str:
        return self.to_papi_value


class Color(StrEnum):
    WHITE = 'W'
    BLACK = 'B'

    @classmethod
    def from_papi_value(cls, value: str) -> Self:
        """Decode the database value"""
        match value:
            case 'B':
                return Color.WHITE
            case 'N':
                return Color.BLACK
            case _:
                raise ValueError(f'Unknown value: {value}')

    @property
    def to_papi_value(self) -> str:
        match self:
            case Color.WHITE:
                return 'B'
            case Color.BLACK:
                return 'N'
            case _:
                raise ValueError(f'Unknown value:  {self}')

    def __str__(self) -> str:
        match self:
            case Color.WHITE:
                return 'Blancs'
            case Color.BLACK:
                return 'Noirs'
            case _:
                raise ValueError(f'Unknown value: {self}')


class ScreenType(StrEnum):
    Boards = auto()
    Players = auto()
    Results = auto()

    def __str__(self) -> str:
        match self:
            case ScreenType.Boards:
                return "Appariements par table"
            case ScreenType.Players:
                return "Appariements par joueur.euse"
            case ScreenType.Results:
                return "Résultats"
            case _:
                raise ValueError

    @classmethod
    def from_str(cls, value) -> Self:
        match value:
            case 'boards':
                return cls.Boards
            case 'players':
                return cls.Players
            case 'results':
                return cls.Results
            case _:
                raise ValueError(f'Invalid board type: {value}')

    @classmethod
    def names(cls) -> list[str]:
        return [member.value for member in iter(cls)]


class ChessEventPlayer:
    def __init__(self, chessevent_player_info: dict[str, bool | str | int | dict[int, float] | None]):
        self.last_name: str = ''
        self.first_name: str = ''
        self.ffe_id: str = ''
        self.fide_id: int = 0
        self.gender: PlayerGender = PlayerGender.NONE
        self.birth: float = 0.0
        self.category: PlayerCategory = PlayerCategory.NONE
        self.standard_rating: int = 0
        self.standard_rating_type: PlayerRatingType = PlayerRatingType.NONE
        self.rapid_rating: int = 0
        self.rapide_rating_type: PlayerRatingType = PlayerRatingType.NONE
        self.blitz_rating: int = 0
        self.blitz_rating_type: PlayerRatingType = PlayerRatingType.NONE
        self.title: PlayerTitle = PlayerTitle.NONE
        self.license: PlayerLicense = PlayerLicense.NONE
        self.federation: str = ''
        self.league: str = ''
        self.club_id: int = 0
        self.club: str = ''
        self.email: str = ''
        self.phone: str = ''
        self.fee: str = ''
        self.paid: str = ''
        self.check_in: bool = False
        self.board: int = 0
        self.skipped_rounds: dict[int, float] = {}
        self.error = True
        key: str = ''
        try:
            self.last_name = str(chessevent_player_info[key := 'last_name'])
            self.first_name = str(chessevent_player_info[key := 'first_name'])
            self.ffe_id = str(chessevent_player_info[key := 'ffe_id'])
            key = 'fide_id'
            if chessevent_player_info[key]:
                self.fide_id = int(chessevent_player_info[key])
            key = 'gender'
            if chessevent_player_info[key]:
                self.gender = PlayerGender(int(chessevent_player_info[key]))
            self.birth = float(chessevent_player_info[key := 'birth'])
            key = 'category'
            self.category = PlayerCategory.NONE
            if chessevent_player_info[key]:
                self.category = PlayerCategory(int(chessevent_player_info[key]))
            self.standard_rating = int(chessevent_player_info[key := 'standard_rating'])
            self.standard_rating_type = PlayerRatingType(int(chessevent_player_info[key := 'standard_rating_type']))
            self.rapid_rating = int(chessevent_player_info[key := 'rapid_rating'])
            self.rapide_rating_type = PlayerRatingType(int(chessevent_player_info[key := 'rapid_rating_type']))
            self.blitz_rating = int(chessevent_player_info[key := 'blitz_rating'])
            self.blitz_rating_type = PlayerRatingType(int(chessevent_player_info[key := 'blitz_rating_type']))
            self.title = PlayerTitle(int(chessevent_player_info[key := 'title']))
            self.license = PlayerLicense(int(chessevent_player_info[key := 'license']))
            self.federation = str(chessevent_player_info[key := 'federation'])
            self.league = str(chessevent_player_info[key := 'league'])
            key = 'club_id'
            if chessevent_player_info[key]:
                self.club_id = int(chessevent_player_info[key])
                if self.club_id <= 0:
                    raise ValueError
            self.club = str(chessevent_player_info[key := 'club'])
            self.email = str(chessevent_player_info[key := 'email'])
            self.phone = str(chessevent_player_info[key := 'phone'])
            self.fee = float(chessevent_player_info[key := 'fee'])
            self.paid = float(chessevent_player_info[key := 'paid'])
            self.check_in = bool(chessevent_player_info[key := 'check_in'])
            self.board = int(chessevent_player_info[key := 'board'])
            self.skipped_rounds = {}
            key = 'skipped_rounds'
            for round in chessevent_player_info[key]:
                if int(round) in range(1, 25) and chessevent_player_info[key][round] in [0.0, 0.5]:
                    self.skipped_rounds[int(round)] = chessevent_player_info[key][round]
                else:
                    raise ValueError
        except KeyError:
            logger.error(f'Champ {key} non trouvé pour le·la joueur·euse [{self.last_name} {self.first_name}]')
            return
        except (TypeError, ValueError):
            logger.error(
                f'Valeur du champ {key} non valide ([{chessevent_player_info[key]}]) '
                f'pour le·la joueur·euse [{self.last_name} {self.first_name}]')
            return
        self.error = False

    def __str__(self) -> str:
        lines: list[str] = []
        lines.append(f'  - Nom : {self.last_name} {self.first_name}')
        lines.append(f'  - Titre / FFE / Fide : {self.title} / {self.ffe_id} / {self.fide_id}')
        lines.append(f'  - Licence / Catégorie / Genre : {self.license} / {self.category} / {self.gender}')
        lines.append(f'  - Date de naissance : {self.birth}')
        lines.append(f'  - Classements standard / rapide / blitz : {self.standard_rating}{self.standard_rating_type} '
                     f'/ {self.rapid_rating}{self.rapide_rating_type} / {self.blitz_rating}{self.blitz_rating_type}')
        lines.append(f'  - Fédération / Ligue / Club : {self.federation} / {self.league} / {self.club_id} {self.club}')
        lines.append(f'  - Mél / Tél : {self.email} / {self.phone}')
        lines.append(f'  - Dû / Payé / Pointé·e : {self.fee} / {self.paid} / {self.check_in}')
        lines.append(f'  - Fixe / Rondes : {self.board} / {self.skipped_rounds}')
        return '\n'.join(lines)


class ChessEventTournament:
    def __init__(self, chessevent_tournament_info: dict[str, str | int | float | list[dict[str, bool | str | int | dict[int, float] | None]]]):
        self.name: str = ''
        self.type: TournamentType = TournamentType.UNKNOWN
        self.rounds: int = 0
        self.pairing: TournamentPairing = TournamentPairing.UNKNOWN
        self.time_control: str = ''
        self.location: str = ''
        self.arbiter: str = ''
        self.dates: list[float, float] = [0.0, ] * 2
        self.tie_breaks: list[TournamentTieBreak] = [TournamentTieBreak.NONE, ] * 3
        self.rating: TournamentRating = TournamentRating.UNKNOWN
        self.players: list[ChessEventPlayer] = []
        self.error = True
        key: str = ''
        try:
            self.name = str(chessevent_tournament_info[key := 'name'])
            self.type = TournamentType(int(chessevent_tournament_info[key := 'type']))
            self.rounds = int(chessevent_tournament_info[key := 'rounds'])
            if self.rounds not in range(1, 25):
                raise ValueError
            self.pairing = TournamentPairing(int(chessevent_tournament_info[key := 'pairing']))
            self.time_control = str(chessevent_tournament_info[key := 'time_control'])
            self.location = str(chessevent_tournament_info[key := 'location'])
            self.arbiter = str(chessevent_tournament_info[key := 'arbiter'])
            self.start = float(chessevent_tournament_info[key := 'start'])
            self.end = float(chessevent_tournament_info[key := 'end'])
            for tie_break_index in range(3):
                key = f'tie_break_{tie_break_index + 1}'
                if chessevent_tournament_info[key]:
                    self.tie_breaks[tie_break_index] = TournamentTieBreak(int(chessevent_tournament_info[key]))
            self.rating = TournamentRating(int(chessevent_tournament_info[key := 'rating']))
            key = 'players'
            for chessevent_player_info in chessevent_tournament_info[key]:
                chessevent_player: ChessEventPlayer = ChessEventPlayer(chessevent_player_info)
                if chessevent_player.error:
                    return
                self.players.append(chessevent_player)
        except KeyError:
            logger.error(f'Champ {key} non trouvé dans la réponse de Chess Event')
            return
        except (TypeError, ValueError):
            logger.error(
                f'Valeur du champ {key} non valide ([{chessevent_tournament_info[key]}]) '
                f'dans la réponse de Chess Event')
            return
        self.error = False

    def __str__(self) -> str:
        lines: list[str] = []
        lines.append(f'  - Nom : {self.name}')
        lines.append(f'  - Type : {self.type}')
        lines.append(f'  - Nombre de rondes : {self.rounds}')
        lines.append(f'  - Appariement : {self.pairing}')
        lines.append(f'  - Cadence : {self.time_control}')
        lines.append(f'  - Lieu : {self.location}')
        lines.append(f'  - Arbitre : {self.arbiter}')
        lines.append(f'  - Dates : {self.dates[0]} - {self.dates[1]}')
        for tie_break_index in range(1, 4):
            lines.append(f'  - Départage n°{tie_break_index} : {self.tie_breaks[tie_break_index]}')
        lines.append(f'  - Classement utilisé : {self.rating}')
        return '\n'.join(lines)
