import re
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from AdvancedHTMLParser import AdvancedHTMLParser, AdvancedTag
from requests import Session, Response
from logging import Logger

from data.tournament import Tournament
from common.logger import get_logger

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
    def __init__(self, tournament: Tournament):
        super().__init__()
        self.__tournament = tournament
        self.__init_vars: Optional[Dict[str, str]] = None
        self.__auth_vars: Optional[Dict[str, str]] = None
        self.__tournament_ffe_url: Optional[str] = None

    def __read_url(self, url: str, data: Dict[str, str] = None, files: Dict[str, Path] = None) -> Optional[str]:
        handlers: Dict[str, Any] = {}
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
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error(f'Veuillez vérifier votre connection à internet')
        except TimeoutError as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
            logger.error('Le site fédéral est indisponible')
        except Exception as e:
            logger.error(f'[{url}] [{e.__class__.__name__}] [{e}]')
        for handler in handlers.values():
            handler.close()
        return None

    @staticmethod
    def __parse_html(html: str) -> Tuple[Optional[AdvancedHTMLParser], Optional[str]]:
        parser: AdvancedHTMLParser = AdvancedHTMLParser()
        error: Optional[str] = None
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
    def __get_state_vars(parser: AdvancedHTMLParser, url: str) -> Optional[Dict[str, str]]:
        result: Dict[str, str] = {}
        for id in [VIEW_STATE_INPUT_ID, VIEW_STATE_GENERATOR_INPUT_ID, EVENT_VALIDATION_INPUT_ID, ]:
            tag: AdvancedTag = parser.getElementById(id)
            if not tag:
                logger.error(f'[{url}] input[id=[{id}] not found')
                return None
            result[id] = tag.attributesDict['value']
        return result

    def ffe_init(self) -> bool:
        url = FFE_URL
        html: str = self.__read_url(url)
        if not html:
            return False
        parser, error = self.__parse_html(html)
        if error:
            return False
        self.__init_vars = self.__get_state_vars(parser, url)
        return True

    def ffe_auth(self) -> bool:
        url = FFE_URL + '/Default.aspx'
        post_data: Dict[str, str] = {
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
        auth_vars: Dict[str, Optional[str]] = self.__get_state_vars(parser, url)
        for id in [SET_VISIBLE_LINK_ID, FEES_LINK_ID, UPLOAD_LINK_ID, ]:
            tag: AdvancedTag = parser.getElementById(id)
            auth_vars[id] = tag.innerText if tag else None
        tag: AdvancedTag = parser.getElementById(VIEW_LINK_ID)
        if not tag:
            # logger.error(f'[{url}] a[id=[{VIEW_LINK_ID}] not found')
            logger.error(f'L\'authentification a échoué (vérifier les codes)')
            return False
        self.__auth_vars = auth_vars
        self.__tournament_ffe_url = tag.attributesDict['href']
        return True

    def test(self):
        logger.info(f'Tournoi [{self.__tournament.ffe_id}] :')
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info(f'auth OK: {self.__tournament_ffe_url}')

    def get_fees(self):
        logger.info(f'Tournoi [{self.__tournament_ffe_url}] :')
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info(f'auth OK: {self.__tournament_ffe_url}')
        if self.__auth_vars[FEES_LINK_ID] is None:
            logger.warning(
                f'Lien de facturation non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé '
                f'ou que le tournoi n\'a pas déjà été archivé)')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() == 'tournoi exempté de droits':
            logger.info(f'Tournoi exempt de droits d\'homologation')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() != 'afficher la facture':
            logger.error(f'Lien de facturation non reconnu [{self.__auth_vars[FEES_LINK_ID]}]')
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post_data: Dict[str, str] = {
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
            logger.error(f'[{FEES_DIR.resolve()}] n\'est pas un répertoire')
            return
        base: AdvancedTag = AdvancedTag('base')
        base.setAttribute('href', FFE_URL)
        parser, error = self.__parse_html(html)
        if error:
            return False
        head: AdvancedTag = parser.getElementsByTagName('head')[0]
        head.insertBefore(base, head.getChildren()[0])
        file: Path = Path(FEES_DIR, str(self.__tournament.ffe_id) + '-fees.html')
        with open(file, 'w') as f:
            f.write(parser.getHTML())
        logger.info(f'Facture d\'homologation enregistrée dans [{file}]')
        webbrowser.open(f'file://{file.resolve()}', new=2)
        logger.info(f'fees OK')
        return

    def upload(self, set_visible: bool):
        logger.info(f'Mise à jour du tournoi [{self.__tournament.ffe_id}] ({self.__tournament.file}):')
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info(f'auth OK: {self.__tournament_ffe_url}')
        if self.__auth_vars[UPLOAD_LINK_ID] is None:
            logger.warning(f'Lien de mise en ligne non trouvé (vérifier que le tournoi n\'est pas terminé)')
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post: Dict[str, str] = {
            '__EVENTTARGET': UPLOAD_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        html: str = self.__read_url(url, data=post, files={UPLOAD_FILE_ID: self.__tournament.file, })
        if not html:
            return
        parser, error = self.__parse_html(html)
        if error:
            return
        self.__tournament.ffe_upload_marker.touch()
        logger.info(f'upload OK')
        if not set_visible:
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID] is None:
            logger.warning(f'Lien d\'affichage non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé)')
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('desactiver'):
            logger.info(f'Les données sont déjà affichées')
            return
        if not self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('activer'):
            logger.error(f'Lien d\'affichage non reconnu [{self.__auth_vars[SET_VISIBLE_LINK_ID]}]')
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post_data: Dict[str, str] = {
            '__EVENTTARGET': SET_VISIBLE_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        html: str = self.__read_url(url, post_data)
        if not html:
            return
        logger.info(f'show OK')
