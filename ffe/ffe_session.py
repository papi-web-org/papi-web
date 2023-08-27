import os
import webbrowser
from typing import Optional, Dict, Any
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

FEES_DIR: str = 'fees'


class FFESession(Session):
    def __init__(self, tournament: Tournament):
        super().__init__()
        self.__tournament = tournament
        self.__init_vars: Optional[Dict[str, str]] = None
        self.__auth_vars: Optional[Dict[str, str]] = None
        self.__tournament_ffe_url: Optional[str] = None

    def __read_url(self, url: str, data: Dict[str, str] = None, files: Dict[str, str] = None) -> Optional[str]:
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
                response: Response = self.post(url, data=data)
                for handler in handlers.values():
                    handler.close()
                return response.content.decode()
        except ConnectionError as e:
            logger.error('[{}] [{}]'.format(e.__class__.__name__, url, e))
            logger.error('Veuillez vérifier votre connection à internet')
        except TimeoutError as e:
            logger.error('[{}] [{}]'.format(e.__class__.__name__, url, e))
            logger.error('Le site fédéral est indisponible')
        except Exception as e:
            logger.error('[{}] [{}]'.format(e.__class__.__name__, url, e))
        for handler in handlers.values():
            handler.close()
        return None

    @staticmethod
    def __parse_html(html: str) -> Optional[AdvancedHTMLParser]:
        parser: AdvancedHTMLParser = AdvancedHTMLParser()
        parser.parseStr(html)
        return parser

    @staticmethod
    def __get_state_vars(parser: AdvancedHTMLParser, url: str) -> Optional[Dict[str, str]]:
        result: Dict[str, str] = {}
        for id in [VIEW_STATE_INPUT_ID, VIEW_STATE_GENERATOR_INPUT_ID, EVENT_VALIDATION_INPUT_ID, ]:
            tag: AdvancedTag = parser.getElementById(id)
            if not tag:
                logger.error('[{}] input[id=[{}] not found'.format(url, id))
                return None
            result[id] = tag.attributesDict['value']
        return result

    def ffe_init(self) -> bool:
        url = FFE_URL
        html: str = self.__read_url(url)
        if not html:
            return False
        parser: AdvancedHTMLParser = self.__parse_html(html)
        if not parser:
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
        parser: AdvancedHTMLParser = self.__parse_html(html)
        if not parser:
            return False
        auth_vars: Dict[str, Optional[str]] = self.__get_state_vars(parser, url)
        for id in [SET_VISIBLE_LINK_ID, FEES_LINK_ID, UPLOAD_LINK_ID, ]:
            tag: AdvancedTag = parser.getElementById(id)
            auth_vars[id] = tag.innerText if tag else None
        tag: AdvancedTag = parser.getElementById(VIEW_LINK_ID)
        if not tag:
            # logger.error('[{}] a[id=[{}] not found'.format(url, VIEW_LINK_ID))
            logger.error('L\'authentification a échoué (vérifier les codes)')
            return False
        self.__auth_vars = auth_vars
        self.__tournament_ffe_url = tag.attributesDict['href']
        return True

    def test(self):
        logger.info('Tournoi [{}] :'.format(self.__tournament.ffe_id))
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info('auth OK: {}'.format(self.__tournament_ffe_url))

    '''def set_visible(self):
        logger.info('Tournoi [{}] :'.format(self.__tournament.ffe_id))
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info('auth OK: {}'.format(self.__tournament_ffe_url))
        if self.__auth_vars[SET_VISIBLE_LINK_ID] is None:
            logger.warning('Lien d\'affichage non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé)')
            return False
        if self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('desactiver'):
            logger.info('Les données sont déjà affichées')
            return True
        if not self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('activer'):
            logger.error('Lien d\'affichage non reconnu [{}]'.format(self.__auth_vars[SET_VISIBLE_LINK_ID]))
            return False
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
            return False
        logger.info('show OK')
        return True'''

    def get_fees(self):
        logger.info('Tournoi [{}] :'.format(self.__tournament.ffe_id))
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info('auth OK: {}'.format(self.__tournament_ffe_url))
        if self.__auth_vars[FEES_LINK_ID] is None:
            logger.warning(
                'Lien de facturation non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé '
                'ou que le tournoi n\'a pas déjà été archivé)')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() == 'tournoi exempté de droits':
            logger.info('Tournoi exempt de droits d\'homologation')
            return
        if self.__auth_vars[FEES_LINK_ID].lower() != 'afficher la facture':
            logger.error('Lien de facturation non reconnu [{}]'.format(self.__auth_vars[FEES_LINK_ID]))
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
        if not os.path.exists(FEES_DIR):
            os.makedirs(FEES_DIR)
        if not os.path.isdir(FEES_DIR):
            logger.error('[{}] n\'est pas un répertoire'.format(os.path.realpath(FEES_DIR)))
            return
        base: AdvancedTag = AdvancedTag('base')
        base.setAttribute('href', FFE_URL)
        parser: AdvancedHTMLParser = self.__parse_html(html)
        if not parser:
            return
        head: AdvancedTag = parser.getElementsByTagName('head')[0]
        head.insertBefore(base, head.getChildren()[0])
        file: str = os.path.join(FEES_DIR, str(self.__tournament.ffe_id) + '-fees.html')
        with open(file, 'w') as f:
            f.write(parser.getHTML())
        logger.info('Facture d\'homologation enregistrée dans [{}]'.format(file))
        webbrowser.open('file://' + os.path.realpath(file), new=2)
        logger.info('fees OK')
        return

    def upload(self, set_visible: bool):
        logger.info('Mise à jour du tournoi [{}] ({}):'.format(self.__tournament.ffe_id, self.__tournament.file))
        if not self.ffe_init():
            return
        # logger.info('init OK')
        if not self.ffe_auth():
            return
        logger.info('auth OK: {}'.format(self.__tournament_ffe_url))
        if self.__auth_vars[UPLOAD_LINK_ID] is None:
            logger.warning('Lien de mise en ligne non trouvé (vérifier que le tournoi n\'est pas terminé)')
            return
        url = FFE_URL + '/MonTournoi.aspx'
        post: Dict[str, str] = {
            '__EVENTTARGET': UPLOAD_EVENT,
            '__EVENTARGUMENT': '',
            VIEW_STATE_INPUT_ID: self.__auth_vars[VIEW_STATE_INPUT_ID],
            VIEW_STATE_GENERATOR_INPUT_ID: self.__auth_vars[VIEW_STATE_GENERATOR_INPUT_ID],
            EVENT_VALIDATION_INPUT_ID: self.__auth_vars[EVENT_VALIDATION_INPUT_ID],
        }
        html: str = self.__read_url(url, data=post, files={UPLOAD_EVENT: self.__tournament.file, })
        if not html:
            return
        from pathlib import Path
        Path(self.__tournament.ffe_upload_marker).touch()
        logger.info('upload OK')
        if not set_visible:
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID] is None:
            logger.warning('Lien d\'affichage non trouvé (vérifier qu\'un fichier Papi a déjà été téléchargé)')
            return
        if self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('desactiver'):
            logger.info('Les données sont déjà affichées')
            return
        if not self.__auth_vars[SET_VISIBLE_LINK_ID].lower().startswith('activer'):
            logger.error('Lien d\'affichage non reconnu [{}]'.format(self.__auth_vars[SET_VISIBLE_LINK_ID]))
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
        logger.info('show OK')
