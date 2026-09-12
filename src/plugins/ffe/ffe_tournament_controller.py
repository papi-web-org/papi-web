from functools import partial
from pathlib import Path
from typing import Annotated, Any

from litestar import post, get
from litestar.enums import RequestEncodingType
from litestar.params import Body, FromPath
from litestar.response import Template, File
from litestar_htmx import HTMXRequest, ClientRedirect, HTMXTemplate

from common import SharlyChessException
from common.i18n import _
from common.logger import get_logger
from common.network import NetworkMonitor
from data.access_levels.actions import AuthAction
from data.tournament import Tournament
from plugins import ffe
from plugins.ffe import PLUGIN_NAME
from plugins.ffe.ffe_background_uploader import FfeBackgroundUploader
from plugins.ffe.ffe_session import FFESession
from plugins.ffe.utils import FFEUtils
from plugins.utils import PluginUtils
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminController,
)
from web.controllers.admin.tournament_admin_controller import TournamentAdminWebContext
from web.controllers.base_controller import WebContext
from web.guards import ActionGuard, EventGuard, TournamentActionGuard
from web.messages import Message

logger = get_logger()
get_data = partial(PluginUtils.get_plugin_data, PLUGIN_NAME)


class FfeTournamentController(BaseEventAdminController):
    """Controller for all the FFE endpoints used on the tournaments page."""

    guards = [
        EventGuard(),
        ActionGuard(AuthAction.VIEW_TOURNAMENTS_TAB),
    ]

    @post(
        path='/ffe/test-auth/{event_uniq_id:str}',
        name='ffe-test-auth',
    )
    async def htmx_ffe_test_auth(
        self,
        event_uniq_id: FromPath[str],
        data: Annotated[
            dict[str, Any],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        ffe_auth_valid: bool | None = None

        if NetworkMonitor.connected():
            ffe_id: int = 0
            try:
                ffe_id = WebContext.form_data_to_int(data, 'ffe_id') or 0
            except ValueError:
                pass
            ffe_password: str = WebContext.form_data_to_str(data, 'ffe_password') or ''

            if ffe_id and ffe_password:
                ffe_auth_valid = FFESession(tournament=None).test_auth(
                    ffe_id=ffe_id, ffe_password=ffe_password
                )

        errors = {}
        # Compare to False, None means 'unable to check'
        if ffe_auth_valid is False:
            errors['ffe_id'] = _('Invalid FFE certification number or password.')
            errors['ffe_password'] = _('Invalid FFE certification number or password.')

        return HTMXTemplate(
            template_name='ffe_tournament_ffe_auth_fields.html',
            context={
                'data': {
                    'ffe_id': data['ffe_id'],
                    'ffe_password': data['ffe_password'],
                },
                'ffe_auth_valid': ffe_auth_valid is True,
                'ffe_password_visible': data['ffe_password_visible'] == 'true',
                'event_uniq_id': event_uniq_id,
                'errors': errors,
            },
        )

    @post(
        path='/ffe/make-visible/{event_uniq_id:str}/{tournament_id:int}',
        name='ffe-make-visible',
        guards=[TournamentActionGuard(AuthAction.PUBLISH_RESULTS)],
    )
    async def htmx_ffe_make_visible(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        FfeBackgroundUploader.upload_tournament(
            tournament.event.uniq_id, tournament.id, set_visible=True
        )
        if FFEUtils.get_tournament_plugin_data(tournament).upload_failure_id:
            Message.error(
                request,
                _(
                    'Tournament visibility could not be set, consult '
                    'Menu > Data Transfer > FFE for more details.'
                ),
            )
        else:
            Message.success(request, _('Tournament is now visible on the FFE website.'))

        return self.render_messages(request)

    @post(
        path='/ffe/upload-tournament/{event_uniq_id:str}/{tournament_id:int}',
        name='ffe-upload-single-tournament',
        guards=[TournamentActionGuard(AuthAction.PUBLISH_RESULTS)],
    )
    async def htmx_ffe_upload_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        FfeBackgroundUploader.upload_tournament(tournament.event.uniq_id, tournament.id)
        if FFEUtils.get_tournament_plugin_data(tournament).upload_failure_id:
            Message.error(
                request,
                _(
                    'Tournament upload failed, consult Menu > '
                    'Data Transfer > FFE for more details.'
                ),
            )
        else:
            Message.success(request, _('Tournament successfully uploaded.'))

        return self.render_messages(request)

    @staticmethod
    def tournament_fees_file(tournament: Tournament) -> Path:
        return (
            ffe.TMP_DIR / 'fees' / tournament.event.uniq_id / f'{tournament.name}.html'
        )

    @get(
        path='/ffe/extract-fees/{event_uniq_id:str}/{tournament_id:int}',
        name='ffe-extract-fees',
        guards=[TournamentActionGuard(AuthAction.DOWNLOAD_FEES)],
    )
    async def htmx_ffe_extract_fees(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        tournament_id: FromPath[int],
    ) -> Template | ClientRedirect:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        try:
            if html := FFESession(tournament).get_fees():
                fees_file = self.tournament_fees_file(tournament)
                fees_file.parent.mkdir(parents=True, exist_ok=True)
                with open(fees_file, 'w') as f:
                    f.write(html)
                url: str = request.app.route_reverse(
                    'ffe-download-fees',
                    event_uniq_id=event_uniq_id,
                    tournament_id=tournament_id,
                )
                logger.debug(
                    'Fees written to [%s], redirecting to [%s].',
                    fees_file,
                    url,
                )
                response: ClientRedirect = ClientRedirect(redirect_to=url)
                # cf https://github.com/bigskysoftware/htmx/issues/3189
                response.set_header('HX-Trigger', 'download_ready')
                return response
            else:
                Message.info(request, _('Tournament exempt from registration fees.'))
        except SharlyChessException as e:
            Message.error(request, str(e))
        return self.render_messages(request)

    @get(
        path='/ffe/download-fees/{event_uniq_id:str}/{tournament_id:int}',
        name='ffe-download-fees',
        guards=[TournamentActionGuard(AuthAction.DOWNLOAD_FEES)],
    )
    async def ffe_download_fees(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        tournament_id: FromPath[int],
    ) -> Template | File:
        web_context = TournamentAdminWebContext(request, tournament_id)
        tournament = web_context.get_admin_tournament()
        file: Path = self.tournament_fees_file(tournament)
        return File(
            path=file,
            filename=f'{event_uniq_id}-{tournament.name}-fees.html',
        )
