import json
import logging
import re
from distutils.version import StrictVersion
from json import JSONDecodeError
from logging import Logger
from typing import Any

from requests import Response, get
from requests.exceptions import ConnectionError, Timeout, RequestException, HTTPError
from common.config_reader import TMP_DIR
from common.papi_web_config import PapiWebConfig, PAPI_WEB_VERSION
from common.logger import get_logger, configure_logger

logger: Logger = get_logger()
configure_logger(logging.INFO)


class Engine:
    def __init__(self):
        if not TMP_DIR.is_dir():
            TMP_DIR.mkdir(parents=True)
        logger.info('Reading configuration file...')
        self._config = PapiWebConfig()
        self._check_version()

    def _check_version(self):
        last_stable_version: str | None = self._get_last_stable_version()
        if not last_stable_version:
            logger.warning('La vérification de la version a échoué')
            return
        if last_stable_version == PAPI_WEB_VERSION:
            logger.info(f'Votre version de Papi-web est à jour')
            return
        last_stable_matches = re.match(r'^.*(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+).*$', last_stable_version)
        if re.match(r'^.*(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+).*$', PAPI_WEB_VERSION):
            if last_stable_version > PAPI_WEB_VERSION:
                logger.warning(f'Une version plus récente que la vôtre est disponible ({last_stable_version})')
            else:
                logger.warning(f'Vous utilisez une version plus récente que la dernière version stable disponible, '
                               f'vous ne seriez pas développeur des fois ?')
            return
        if not (matches := re.match(r'^.*(?P<major>\d+)\.(?P<minor>\d+)-rc(?P<rc>\d+).*$', PAPI_WEB_VERSION)):
            raise ValueError('Version de Papi-web invalide')
        if last_stable_matches.group('major') > matches.group('major'):
            logger.warning(f'Une version majeure plus récente que la vôtre est disponible ({last_stable_version})')
            return
        if last_stable_matches.group('minor') > matches.group('minor'):
            logger.warning(f'Une version stable plus récente que la vôtre est disponible ({last_stable_version})')
            return
        logger.info(f'Vous utilisez une version non stabilisée plus récente que la dernière version stable '
                    f'disponible ({last_stable_version})')

    @staticmethod
    def _get_last_stable_version() -> str | None:
        url: str = 'https://api.github.com/repos/pascalaubry/papi-web/releases'
        try:
            logger.debug(f'Recherche d\'une version plus récente sur GitHub ({url})...')
            response: Response = get(url, allow_redirects=True)
            response.raise_for_status()
            if not response:
                logger.debug(f'Pas de réponse reçue de GitHub ({url})')
                return None
            data: str = response.content.decode()
            logger.debug(f'Données de la réponse : {data}')
            if response.status_code == 200:
                logger.debug(f'Données récupérées de la plateforme GitHub : {len(data)} octets')
            try:
                entries: list[dict[str, Any]] = json.loads(data)
            except JSONDecodeError as jde:
                logger.debug(f'Impossible de décoder le JSON reçu: {jde}')
                return None
            versions: list[str] = []
            for entry in entries:
                name: str = entry['name']
                if matches := re.match(r'.*(\d+\.\d+\.\d+).*', name):
                    version: str = matches.group(1)
                    logger.debug(f'name=[{name}] > version=[{version}]')
                    versions.append(version)
                else:
                    logger.debug(f'name=[{name}]: no stable version number')
            if not versions:
                logger.debug('Aucune version stable trouvée')
                return None
            versions.sort(key=StrictVersion)
            logger.debug(f'releases={versions}')
            return versions[-1]
        except ConnectionError as e:
            logger.warning(f'Veuillez vérifier votre connection à internet : {e}')
            return None
        except Timeout as e:
            logger.warning(f'La plateforme Github est indisponible : {e}')
            return None
        except HTTPError as e:
            logger.warning(f'La plateforme Github a renvoyé l\'erreur {e.errno} {e.strerror}')
            return None
        except RequestException as e:
            logger.warning(f'La plateforme Github a renvoyé une erreur : {e}')
            return None
