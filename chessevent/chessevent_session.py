import json

from logging import Logger
from requests import Session, Response
from requests.exceptions import ConnectionError, Timeout, RequestException  # pylint: disable=redefined-builtin

from common.papi_web_config import PapiWebConfig
from data.tournament import Tournament
from common.logger import get_logger

logger: Logger = get_logger()


class ChessEventSession(Session):
    """A Requests session specialised for communication with
    the ChessEvent platform."""
    def __init__(self, tournament: Tournament):
        super().__init__()
        self._tournament: Tournament = tournament

    def read_data(self) -> str | None:
        """Reads the data of the tournament from ChessEvent.
        If the data could be successfully retrieved and decode, returns
        it encoded as a JSON string.
        If an error occurred, logs ir and returns None"""
        url: str = PapiWebConfig.chessevent_download_url
        try:
            post: dict[str, str] = {
                'user_id': self._tournament.chessevent.user_id,
                'password': self._tournament.chessevent.password,
                'event_id': self._tournament.chessevent.event_id,
                'tournament_name': self._tournament.chessevent_tournament_name,
            }
            chessevent_string: str = (f'{post["user_id"]}:{"*" * 8}'
                                      f'@{post["event_id"]}/{post["tournament_name"]}')
            logger.debug('Interrogation de la plateforme Chess Event %s...', chessevent_string)
            # Redirections are handled manually to pass the data at each redirection
            response: Response = self.post(url, data=post, allow_redirects=False)
            while response.status_code in [301, 302]:
                redirect_url = response.headers['location']
                logger.debug('redirection vers %s...', redirect_url)
                response = self.post(redirect_url, data=post, allow_redirects=False)
            logger.debug('Code HTTP de la réponse : %s', response.status_code)
            logger.debug('Entêtes de la réponse : %s', response.headers)
            data: str = response.content.decode()
            logger.debug('Données de la réponse : %s', data)
            if response.status_code == 200:
                logger.debug('Données récupérées de la plateforme Chess Event : %s octets',
                             len(data))
                return data
            match response.status_code:
                case 401:
                    logger.error('Les identifiants pour %s '
                                 'ont été rejetés par la plateforme Chess Event (%s), '
                                 'code d\'erreur : %s',
                                 post["user_id"], chessevent_string, response.status_code)
                case 403:
                    logger.error('L\'accès au tournoi %s n\'est pas '
                                 'autorisé pour %s '
                                 '(%s), code d\'erreur : %s',
                                 post["tournament_name"], post["user_id"],
                                 chessevent_string, response.status_code)
                case 496:
                    logger.error('Un paramètre est manquant dans la requête à la plateforme Chess Event '
                                 '(%s, code d\'erreur : %s - '
                                 '%s)',
                                 chessevent_string, response.status_code, json.loads(data)["error"])
                case 497:
                    logger.error('L\'identifiant %s est introuvable sur la plateforme Chess Event '
                                 '(%s, code d\'erreur : %s - %s)',
                                 post["user_id"], chessevent_string, response.status_code,
                                 json.loads(data)["error"])
                case 498:
                    logger.error('Le tournoi %s est introuvable sur la plateforme Chess Event '
                                 '(%s, code d\'erreur : %s - %s)',
                                 post["tournament_name"], chessevent_string, response.status_code,
                                 json.loads(data)["error"])
                case 499:
                    logger.error('L\'évènement %s est introuvable sur la plateforme Chess Event '
                                 '(%s, code d\'erreur : %s - %s)',
                                 post["event_id"], chessevent_string, response.status_code,
                                 json.loads(data)["error"])
                case _:
                    logger.error('Réponse invalide de la plateforme Chess Event '
                                 '(%s, code d\'erreur %s - %s)',
                                 chessevent_string, response.status_code, response.status_code)
        except ConnectionError as e:
            logger.error('Veuillez vérifier votre connection à internet [%s] : %s', url, e)
        except Timeout as e:
            logger.error('La plateforme Chess Event est indisponible [%s] : %s', url, e)
        except RequestException as e:
            logger.error('La plateforme Chess Event a renvoyé une erreur [%s] : %s', url, e)
        return None
