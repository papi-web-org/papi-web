from logging import Logger

from common.logger import get_logger
from data.chessevent_player import ChessEventPlayer
from data.util import TournamentType, TournamentPairing, TournamentTieBreak, TournamentRating

logger: Logger = get_logger()


class ChessEventTournament:
    """A class representing all the data of a ChessEvent tournament."""
    def __init__(
            self,
            chessevent_tournament_info: dict[
                str,
                str | int | float | list[dict[str, bool | str | int | dict[int, float] | None]]
            ]):
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
        self.check_in_started: bool = False
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
                if chessevent_player.check_in:
                    self.check_in_started = True
                if chessevent_player.error:
                    return
                self.players.append(chessevent_player)
        except KeyError:
            logger.error('Champ %s non trouvé dans la réponse de Chess Event', key)
            return
        except (TypeError, ValueError):
            logger.error(
                'Valeur du champ %s non valide ([%s]) '
                'dans la réponse de Chess Event', key, chessevent_tournament_info[key])
            return
        self.error = False

    def __str__(self) -> str:
        return '\n'.join(
            [
                f'  - Nom : {self.name}',
                f'  - Type : {self.type}',
                f'  - Nombre de rondes : {self.rounds}',
                f'  - Appariement : {self.pairing}',
                f'  - Cadence : {self.time_control}',
                f'  - Lieu : {self.location}',
                f'  - Arbitre : {self.arbiter}',
                f'  - Dates : {self.start} - {self.end}',
            ] + [
                f'  - Départage n°{tie_break_index} : {self.tie_breaks[tie_break_index]}'
                for tie_break_index in range(1, 4)
            ] + [
                f'  - Classement utilisé : {self.rating}',
                f'  - Homologation : {self.ffe_id}',
            ]
        )
