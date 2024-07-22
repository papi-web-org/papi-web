import json
import logging
import re
from json import JSONDecodeError
from logging import Logger
from typing import Any

from packaging.version import Version

from requests import Response, get
from requests.exceptions import ConnectionError, Timeout, RequestException, \
    HTTPError  # pylint: disable=redefined-builtin
from common.config_reader import TMP_DIR
from common.papi_web_config import PapiWebConfig, PAPI_WEB_VERSION
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()
configure_logger(logging.INFO)


class Engine:
    def __init__(self):
        try:
            TMP_DIR.mkdir(parents=True, exist_ok=True)
        except PermissionError as pe:
            logger.critical(f'Impossible de créer le répertoire {TMP_DIR.absolute()} :-(')
            raise pe
        logger.info('Reading configuration file...')
        self._config = PapiWebConfig()
        self._check_version()

    def _check_version(self):
        last_stable_version: Version | None = self._get_last_stable_version()
        if not last_stable_version:
            logger.warning('La vérification de la version a échoué')
            return
        if last_stable_version == PAPI_WEB_VERSION:
            logger.info('Votre version de Papi-web est à jour')
            return
        last_stable_matches = re.match(
            r'^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$', str(last_stable_version))
        if re.match(r'^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$', str(PAPI_WEB_VERSION)):
            if last_stable_version > PAPI_WEB_VERSION:
                logger.warning('Une version plus récente que la vôtre est disponible (%s)',
                               last_stable_version)
            else:
                logger.warning('Vous utilisez une version plus récente que la dernière version stable disponible, '
                               'vous ne seriez pas développeur des fois ?')
            return
        if not (matches := re.match(r'^(?P<major>\d+)\.(?P<minor>\d+)rc(?P<rc>\d+)$', str(PAPI_WEB_VERSION))):
            raise ValueError(f'Version de Papi-web invalide [{str(PAPI_WEB_VERSION)}]')
        if last_stable_matches.group('major') > matches.group('major'):
            logger.warning('Une version majeure plus récente que la vôtre est disponible (%s)',
                           last_stable_version)
            return
        if last_stable_matches.group('minor') > matches.group('minor'):
            logger.warning('Une version stable plus récente que la vôtre est disponible (%s)',
                           last_stable_version)
            return
        logger.info('Vous utilisez une version non stabilisée plus récente que la dernière version stable '
                    'disponible (%s)', last_stable_version)

    @staticmethod
    def _get_last_stable_version() -> Version | None:
        url: str = 'https://api.github.com/repos/papi-web-org/papi-web/releases'
        try:
            logger.debug('Recherche d\'une version plus récente sur GitHub (%s)...', url)
            response: Response = get(url, allow_redirects=True, timeout=5)
            response.raise_for_status()
            if not response:
                logger.debug('Pas de réponse reçue de GitHub (%s)', url)
                return None
            data: str = response.content.decode()
            logger.debug('Données de la réponse : %s', data)
            if response.status_code == 200:
                logger.debug('Données récupérées de la plateforme GitHub : %s octets',
                             len(data))
            try:
                entries: list[dict[str, Any]] = json.loads(data)
            except JSONDecodeError as jde:
                logger.debug('Impossible de décoder le JSON reçu: %s', jde)
                return None
            versions: list[str] = []
            for entry in entries:
                tag_name: str = entry['tag_name']
                if matches := re.match(r'^(\d+\.\d+\.\d+)$', tag_name):
                    version: str = matches.group(1)
                    logger.debug('tag_name=[%s] > version=[%s]', tag_name, version)
                    versions.append(version)
                else:
                    logger.debug('tag_name=[%s]: no stable version number', tag_name)
            if not versions:
                logger.debug('Aucune version stable trouvée')
                return None
            versions.sort(key=Version)
            logger.debug('releases=%s', versions)
            return Version(versions[-1])
        except ConnectionError as e:
            logger.warning('Veuillez vérifier votre connection à internet : %s', e)
            return None
        except Timeout as e:
            logger.warning('La plateforme Github est indisponible : %s', e)
            return None
        except HTTPError as e:
            logger.warning('La plateforme Github a renvoyé l\'erreur %s %s', e.errno, e.strerror)
            return None
        except RequestException as e:
            logger.warning('La plateforme Github a renvoyé une erreur : %s', e)
            return None
