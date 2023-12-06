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

    def read_data(self) -> str | None:
        url: str = CHESSEVENT_URL
        try:
            post: dict[str, str] = {
                'user_id': self.__tournament.chessevent_connection.user_id,
                'password': self.__tournament.chessevent_connection.password,
                'event_id': self.__tournament.chessevent_connection.event_id,
                'tournament_name': self.__tournament.chessevent_tournament_name,
            }
            chessevent_string: str = (f'{post["user_id"]}:{"*" * min(len(post["password"]), 8)}'
                                      f'@{post["event_id"]}/{post["tournament_name"]}')
            logger.debug(f'Interrogation de la plateforme Chess Event {chessevent_string}...')
            # Redirections are handled manually to pass the data at each redirection
            response: Response = self.post(url, data=post, allow_redirects=False)
            while response.status_code in [301, 302]:
                redirect_url = response.headers['location']
                logger.debug(f'redirection vers {redirect_url}...')
                response = self.post(redirect_url, data=post, allow_redirects=False)
            logger.debug(f'Code HTTP de la réponse : {response.status_code}')
            logger.debug(f'Entêtes de la réponse : {response.headers}')
            data: str = response.content.decode()
            logger.debug(f'Données de la réponse : {data}')
            if response.status_code == 200:
                logger.debug(f'Données récupérées de la plateforme Chess Event : {len(data)} octets')
                return data
            match response.status_code:
                case 401:
                    logger.error(f'Les identifiants {post["user_id"]}/{post["password"]} '
                                 f'ont été rejetés par la plateforme Chess Event ({chessevent_string}), '
                                 f'code d\'erreur : {response.status_code}')
                case 403:
                    logger.error(f'L\'accès au tournoi {post["tournament_name"]} n\'est pas '
                                 f'autorisé pour les identifiants {post["user_id"]}/{post["password"]} '
                                 f'({chessevent_string}), code d\'erreur : {response.status_code}')
                case 496:
                    logger.error(f'Un paramètre est manquant dans la requête à la plateforme Chess Event '
                                 f'({chessevent_string}, code d\'erreur : {response.status_code} - '
                                 f'{json.loads(data)["error"]})')
                case 497:
                    logger.error(f'L\'identifiant {post["user_id"]} est introuvable sur la plateforme Chess Event '
                                 f'({chessevent_string}, code d\'erreur : {response.status_code} - '
                                 f'{json.loads(data)["error"]})')
                case 498:
                    logger.error(f'Le tournoi {post["tournament_name"]} est introuvable sur la plateforme Chess Event '
                                 f'({chessevent_string}, code d\'erreur : {response.status_code} - '
                                 f'{json.loads(data)["error"]})')
                case 499:
                    logger.error(f'L\'évènement {post["event_id"]} est introuvable sur la plateforme Chess Event '
                                 f'({chessevent_string}, code d\'erreur : {response.status_code} - '
                                 f'{json.loads(data)["error"]})')
                case _:
                    logger.error(f'Réponse invalide de la plateforme Chess Event '
                                 f'({chessevent_string}, code d\'erreur {response.status_code} - '
                                 f'{response.status_code})')
        except ConnectionError as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error(f'Veuillez vérifier votre connection à internet')
        except TimeoutError as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error('Le site Chess Event est indisponible')
        except Exception as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
        return None
