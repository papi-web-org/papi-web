import json

from requests import Session, Response
from logging import Logger

from data.tournament import Tournament
from common.logger import get_logger

logger: Logger = get_logger()

CHESSEVENT_URL: str = 'https://services.breizh-chess-online.fr/chessevent/download'


class ChessEventSession(Session):
    def __init__(self, tournament: Tournament):
        super().__init__()
        self.__tournament = tournament

    # TODO remove the method when the Chess Event gateway is available
    @staticmethod
    def __self_made_json_data() -> str:
        return json.dumps({
            'name': '36e open Fide de Domloup',
            'type': 1,  # Suisse
            'rounds': 5,
            'pairing': 2,  # Standard
            'time_control': 'G3600 + 30',
            'location': 'Domloup',
            'arbiter': 'AUBRY Pascal C69548',
            'start': 1708767000,  # 2024-02-24 09:30
            'end': 1708880400,  # 2024-02-25 17:00
            'tie_break_1': 2,  # Buchholz tronqué
            'tie_break_2': 3,  # Buchholz médian
            'tie_break_3': 5,  # Performance
            'rating': 1,  # Standard
            'players': [
                {
                    'last_name': 'AUBRY',
                    'first_name': 'Pascal',
                    'ffe_id': 'C69548',
                    'fide_id': 20671806,
                    'gender': 2,
                    'birth': -41990400,  # 1968-09-02
                    'category': 9,  # Sep
                    'standard_rating': 1458,
                    'standard_rating_type': 3,  # F
                    'rapid_rating': 1440,
                    'rapid_rating_type': 3,  # F
                    'blitz_rating': 1440,
                    'blitz_rating_type': 1,  # E
                    'title': 0,
                    'license': 3,  # A
                    'federation': 'FRA',
                    'league': 'BRE',
                    'club_id': 1918,
                    'club': 'Echiquier Domloupéen',
                    'email': 'pascal.aubry@echecs35.fr',
                    'phone': '0677939521',
                    'fee': 25.0,
                    'paid': 25.0,
                    'check_in': False,
                    'board': 99,
                    'skipped_rounds': {
                        1: 0.5,  # bye ronde 1
                        3: 0.0,  # absent ronde 3
                    },
                },
            ],
        })

    def read_data(self) -> str | None:
        url: str = CHESSEVENT_URL
        try:
            post: dict[str, str] = {
                'user_id': self.__tournament.chessevent_connection.user_id,
                'password': self.__tournament.chessevent_connection.password,
                'event_id': self.__tournament.chessevent_connection.event_id,
                'tournament_id': self.__tournament.chessevent_tournament_id,
            }
            response: Response = self.post(url, data=post)
            data: str = response.content.decode()
            match response.status_code:
                case 200:
                    logger.info(f'Données récupérées de la plateforme Chess Event : {len(data)} octets')
                    return data
                case 401:
                    logger.error(f'Les identifiants {self.__tournament.chessevent_connection.user_id}/'
                                 f'{self.__tournament.chessevent_connection.password} '
                                 f'ont été rejetés par la plateforme Chess Event')
                case 403:
                    logger.error(f'L\'accès au tournoi {self.__tournament.chessevent_tournament_id} n\'est pas '
                                 f'autorisé pour les identifiants {self.__tournament.chessevent_connection.user_id}/'
                                 f'{self.__tournament.chessevent_connection.password}')
                case 404:  # TODO remove the case when the Chess Event gateway is available
                    logger.error('Chess Event status code #404, temporarily sending self-made data...')
                    return self.__self_made_json_data()
                case 499:
                    logger.error(f'L\'évènement {self.__tournament.chessevent_connection.event_id} est introuvable '
                                 f'sur la plateforme Chess Event')
                case 498:
                    logger.error(f'Le tournoi {self.__tournament.chessevent_tournament_id} est introuvable '
                                 f'sur la plateforme Chess Event')
                case _:
                    logger.error(
                        f'Réponse invalide de la plateforme Chess Event (code d\'erreur {response.status_code})')
        except ConnectionError as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error(f'Veuillez vérifier votre connection à internet')
        except TimeoutError as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error('Le site Chess Event est indisponible')
        except Exception as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
        return None
