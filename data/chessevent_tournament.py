from logging import Logger

from common.logger import get_logger
from data.chessevent_player import ChessEventPlayer
from data.util import TournamentType, TournamentPairing, TournamentTieBreak, TournamentRating

logger: Logger = get_logger()


class ChessEventTournament:
    def __init__(self, chessevent_tournament_info: dict[str, str | int | float | list[dict[str, bool | str | int | dict[int, float] | None]]]):
        self.name: str = ''
        self.type: TournamentType = TournamentType.UNKNOWN
        self.rounds: int = 0
        self.pairing: TournamentPairing = TournamentPairing.UNKNOWN
        self.time_control: str = ''
        self.location: str = ''
        self.arbiter: str = ''
        self.start: float = 0.0
        self.end: float = 0.0
        self.tie_breaks: list[TournamentTieBreak] = [TournamentTieBreak.NONE, ] * 3
        self.rating: TournamentRating = TournamentRating.UNKNOWN
        self.ffe_id: int = 0
        self.players: list[ChessEventPlayer] = []
        self.error = True
        key: str = ''
        try:
            self.name = str(chessevent_tournament_info[key := 'name'])
            self.type = TournamentType(int(chessevent_tournament_info[key := 'type']))
            self.rounds = int(chessevent_tournament_info[key := 'rounds'])
            if self.rounds not in range(25):  # the 0-value is set by default later
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
            ffe_id = chessevent_tournament_info[key := 'ffe_id']
            if ffe_id:
                self.ffe_id = int(ffe_id)
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
        lines.append(f'  - Dates : {self.start} - {self.end}')
        for tie_break_index in range(1, 4):
            lines.append(f'  - Départage n°{tie_break_index} : {self.tie_breaks[tie_break_index]}')
        lines.append(f'  - Classement utilisé : {self.rating}')
        lines.append(f'  - Homologation : {self.ffe_id}')
        return '\n'.join(lines)
