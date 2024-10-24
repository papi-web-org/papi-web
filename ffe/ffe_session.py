import re
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from AdvancedHTMLParser import AdvancedHTMLParser, AdvancedTag
from requests import Session, Response
from requests.exceptions import ConnectionError, Timeout, RequestException
from logging import Logger

from common.papi_web_config import TMP_DIR
from data.tournament import Tournament
from common.logger import get_logger
from database.papi import PapiDatabase
from database.sqlite import EventDatabase

logger: Logger = get_logger()

FFE_URL: str = 'http://admin.echecs.asso.fr'

VIEW_STATE_INPUT_ID: str = '__VIEWSTATE'
VIEW_STATE_GENERATOR_INPUT_ID: str = '__VIEWSTATEGENERATOR'
EVENT_VALIDATION_INPUT_ID: str = '__EVENTVALIDATION'

VIEW_LINK_ID: str = 'ctl00_ContentPlaceHolderMain_LinkViewTournoi'
SET_VISIBLE_LINK_ID: str = 'ctl00_ContentPlaceHolderMain_CmdAfficherTournoi'
SET_VISIBLE_EVENT: str = SET_VISIBLE_LINK_ID.replace('_', '$')
FEES_LINK_ID: str = 'ctl00_ContentPlaceHolderMain_CmdFactureHomologation'
FEES_EVENT: str = 'ctl00$ContentPlaceHolderMain$CmdFactureHomologation'
UPLOAD_LINK_ID: str = 'ctl00_ContentPlaceHolderMain_CmdUploadPapi'
UPLOAD_EVENT: str = UPLOAD_LINK_ID.replace('_', '$')
UPLOAD_FILE_ID: str = 'ctl00$ContentPlaceHolderMain$UploadPapi'

FEES_DIR: Path = Path('fees')


class FFESession(Session):
    """A requests session specialized for communication with the FFE website.
    Currently, it relies on hacks, because no API is available."""
    def __init__(self, tournament: Tournament):
        super().__init__()
        self.__tournament: Tournament = tournament
        self.__init_vars: dict[str, str] | None = None
        self.__auth_vars: dict[str, str] | None = None
        self.__tournament_ffe_url: str | None = None

    def __read_url(self, url: str, data: dict[str, str] = None, files: dict[str, Path] = None) -> str | None:
        handlers: dict[str, Any] = {}
        try:
            if not data and not files:
                response: Response = self.get(url)
                return response.content.decode()
            if not files:
                response: Response = self.post(url, data=data)
                return response.content.decode()
            for file_id, file_name in files.items():
                handler = open(file_name, 'rb')
                handlers[file_id] = handler
            response: Response = self.post(url, data=data, files=handlers)
            content: str = response.content.decode()
            for handler in handlers.values():
                handler.close()
            return content
        except ConnectionError as e:
            logger.error('Veuillez vérifier votre connection à internet [%s] : %s', url, e)
        except Timeout as e:
            logger.error('Le site fédéral est indisponible [%s] : %s', url, e)
        except RequestException as e:
            logger.error('Le site fédéral a renvoyé une erreur [%s] : %s', url, e)
        for handler in handlers.values():
            handler.close()
        return None

    @staticmethod
    def __parse_html(html: str) -> tuple[AdvancedHTMLParser | None, str | None]:
        parser: AdvancedHTMLParser = AdvancedHTMLParser()
        error: str | None = None
        parser.parseStr(html)
        tag: AdvancedTag = parser.getElementById('ctl00_ContentPlaceHolderMain_LabelError')
        if tag:
            if tag.innerText:
                matches = re.match(r'^Transfert du fichier : .*\.papi \(\d+ octets\) achevé$', tag.innerText)
                if not matches:
                    error = tag.innerText
                    logger.error(error)
        return parser, error

    @staticmethod
    def __get_state_vars(parser: AdvancedHTMLParser, url: str) -> dict[str, str] | None:
        result: dict[str, str] = {}
        for id_ in [VIEW_STATE_INPUT_ID, VIEW_STATE_GENERATOR_INPUT_ID, EVENT_VALIDATION_INPUT_ID, ]:
            tag: AdvancedTag = parser.getElementById(id_)
            if not tag:
                logger.error('[%s] input[id=[%s] not found', url, id_)
                return None
            result[id_] = tag.attributesDict['value']
        return result

    def __ffe_init(self) -> bool:
        url = FFE_URL
        html: str = self.__read_url(url)
        if not html:
            return False
        parser, error = self.__parse_html(html)
        if error:
            return False
        self.__init_vars = self.__get_state_vars(parser, url)
        return True

    def __ffe_auth(self) -> bool:
        url = FFE_URL + '/Default.aspx'
        post_data: dict[str, str] = {
            VIEW_STATE_INPUT_ID: self.__init_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__init_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__init_vars[EVENT_VALIDATION_INPUT_ID],
            'ctl00$TextLogin': self.__tournament.ffe_id,
            'ctl00$TextPassword': self.__tournament.ffe_password,
            'ctl00$CmdLogin.x': '12',
            'ctl00$CmdLogin.y': '6',
        }
        html: str = self.__read_url(url, post_data)
        if not html:
            return False
        parser, error = self.__parse_html(html)
        if error:
            return False
        auth_vars: dict[str, str | None] = self.__get_state_vars(parser, url)
        for id_ in [SET_VISIBLE_LINK_ID, FEES_LINK_ID, UPLOAD_LINK_ID, ]:
            tag: AdvancedTag = parser.getElementById(id_)
            auth_vars[id_] = tag.innerText if tag else None
        tag: AdvancedTag = parser.getElementById(VIEW_LINK_ID)
        if not tag:
            logger.error('L\'authentification a échoué (vérifier les codes)')
            return False
        self.__auth_vars = auth_vars
        self.__tournament_ffe_url = tag.attributesDict['href']
        return True

    def test(self):
        """Try logging in to the FFE website."""
        logger.info('Tournoi [%s] :', self.__tournament.ffe_id)
        if not self.__ffe_init():
            return
        # logger.info('init OK')
        if not self.__ffe_auth():
            return
        logger.info('auth OK: %s', self.__tournament_ffe_url)

    def get_fees(self):
        logger.info('Tournoi [%s] :', self.__tournament_ffe_url)
        if not self.__ffe_init():
            return
        # logger.info('init OK')
        if not self.__ffe_auth():
            return
        logger.info('auth OK: %s', self.__tournament_ffe_url)
        if self.__auth_vars[FEES_LINK_ID] is None:
            logger.warning(
                'Lien de facturation non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé '
                'ou que le tournoi n\'a pas déjà été archivé)')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() == 'tournoi exempté de droits':
            logger.info('Tournoi exempt de droits d\'homologation')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() != 'afficher la facture':
            logger.error('Lien de facturation non reconnu [%s]', self.__auth_vars[FEES_LINK_ID])
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post_data: dict[str, str] = {
            '__EVENTTARGET': FEES_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        html: str = self.__read_url(url, post_data)
        if not html:
            return
        if not FEES_DIR.exists():
            FEES_DIR.mkdir(parents=True)
        if not FEES_DIR.is_dir():
            logger.error('[%s] n\'est pas un répertoire', FEES_DIR.resolve())
            return
        base: AdvancedTag = AdvancedTag('base')
        base.setAttribute('href', FFE_URL)
        parser, error = self.__parse_html(html)
        if error:
            return False
        head: AdvancedTag = parser.getElementsByTagName('head')[0]
        head.insertBefore(base, head.getChildren()[0])
        file: Path = Path(FEES_DIR, str(self.__tournament.ffe_id) + '-fees.html')
        with open(file, 'w', encoding="utf-8") as f:
            f.write(parser.getHTML())
        logger.info('Facture d\'homologation enregistrée dans [%s]', file)
        webbrowser.open(f'file://{file.resolve()}', new=2)
        logger.info('fees OK')
        return

    def upload(self, set_visible: bool):
        logger.info(
            'Mise à jour du tournoi [%s] (%s) sur le site fédéral :',
            self.__tournament.ffe_id, self.__tournament.file)
        if not self.__ffe_init():
            return
        # logger.info('init OK')
        if not self.__ffe_auth():
            return
        logger.info('auth OK: %s', self.__tournament_ffe_url)
        if self.__auth_vars[UPLOAD_LINK_ID] is None:
            logger.warning('Lien de mise en ligne non trouvé (vérifier que le tournoi n\'est pas terminé)')
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post: dict[str, str] = {
            '__EVENTTARGET': UPLOAD_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        date: str = datetime.fromtimestamp(time.time()).strftime("%Y%m%d%H%M%S")
        tmp_file: Path = TMP_DIR / 'ffe' / f'{self.__tournament.file.stem}-{date}{self.__tournament.file.suffix}'
        tmp_file.parents[0].mkdir(parents=True, exist_ok=True)
        logger.debug('Copie de %s vers %s...', self.__tournament.file, tmp_file)
        tmp_file.write_bytes(self.__tournament.file.read_bytes())
        with PapiDatabase(tmp_file, write=True) as tmp_database:
            tmp_database: PapiDatabase
            logger.debug('Suppression des données personnelles des joueur·euses...')
            tmp_database.delete_players_personal_data()
            logger.debug('Suppression des forfaits si aucun appariement...')
            tmp_database.remove_forfeits_if_no_pairings()
            tmp_database.commit()
        html: str = self.__read_url(url, data=post, files={UPLOAD_FILE_ID: tmp_file, })
        tmp_file.unlink()
        if not html:
            return
        _, error = self.__parse_html(html)
        if error:
            return
        with EventDatabase(self.__tournament.event.uniq_id, write=True) as event_database:
            event_database.set_tournament_last_ffe_upload(self.__tournament.id)
            event_database.commit()
        logger.info('upload OK')
        if not set_visible:
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID] is None:
            logger.warning('Lien d\'affichage non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé)')
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('désactiver'):
            logger.info('Les données sont déjà affichées')
            return
        if not self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('activer'):
            logger.error('Lien d\'affichage non reconnu [%s]', self.__auth_vars[SET_VISIBLE_EVENT])
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post_data: dict[str, str] = {
            '__EVENTTARGET': SET_VISIBLE_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        html: str = self.__read_url(url, post_data)
        if not html:
            return
        logger.info('show OK')
