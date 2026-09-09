from functools import partial, cached_property
from typing import Any, Annotated

from litestar import get, post, patch
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException
from litestar.params import Body, FromPath
from litestar.response import Template
from litestar_htmx import HTMXRequest, HTMXTemplate

from common.i18n import _
from data.access_levels.actions import AuthAction
from data.tournament import Tournament
from plugins.chess_results import PLUGIN_NAME
from plugins.chess_results.chess_results_background_uploader import (
    CRBackgroundUploader,
)
from plugins.chess_results.utils import CRUtils, CHESS_RESULTS_UPLOAD_DELAY
from plugins.utils import PluginUtils
from web.controllers.admin.base_admin_controller import AdminWebContext
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminController,
)
from web.controllers.admin.tournament_admin_controller import (
    TournamentAdminController,
    TournamentAdminWebContext,
)
from web.controllers.base_controller import WebContext
from web.guards import EventGuard, TournamentActionGuard, ActionGuard
from web.messages import Message

get_data = partial(PluginUtils.get_plugin_data, PLUGIN_NAME)


class CRWebContext(AdminWebContext):
    def __init__(
        self,
        request: HTMXRequest,
        tournament_id: int | None = None,
    ):
        super().__init__(request)
        event = self.get_admin_event()
        self.tournament: Tournament | None = None
        if tournament_id:
            try:
                self.tournament = event.tournaments_by_id[tournament_id]
            except KeyError:
                raise NotFoundException(f'Tournament [{tournament_id}] not found.')

    def get_tournament(self) -> Tournament:
        assert self.tournament is not None
        return self.tournament

    @cached_property
    def allowed_tournaments(self) -> list[Tournament]:
        return self.client.allowed_tournaments_for_action(AuthAction.PUBLISH_RESULTS)

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'cr_utils': CRUtils,
            'tournament': self.tournament,
            'allowed_tournaments': self.allowed_tournaments,
            'CHESS_RESULTS_UPLOAD_DELAY': CHESS_RESULTS_UPLOAD_DELAY,
        }


class ChessResultsController(BaseEventAdminController):
    guards = [EventGuard(), TournamentActionGuard(AuthAction.PUBLISH_RESULTS)]

    @get(
        path='/chess-results/chess-results-upload-modal/{event_uniq_id:str}',
        name='chess-results-upload-modal',
    )
    async def htmx_admin_chess_results_upload_modal(
        self, request: HTMXRequest
    ) -> Template:
        web_context = CRWebContext(request)

        return HTMXTemplate(
            template_name='/chess_results_upload_modal.html',
            re_target='#modal-wrapper',
            trigger_event='modal_opened',
            after='settle',
            context=web_context.template_context,
        )

    @classmethod
    def _render_upload_results(cls, web_context: CRWebContext) -> Template:
        return HTMXTemplate(
            template_name='/chess_results_upload_results.html',
            context=web_context.template_context,
            re_swap='outerHTML',
            re_target='#upload-results',
        )

    @get(
        path='/chess-results/chess-results-upload-results/{event_uniq_id:str}',
        name='chess-results-upload-results',
    )
    async def htmx_admin_chess_results_upload_results(
        self, request: HTMXRequest
    ) -> Template:
        web_context = CRWebContext(request)
        return self._render_upload_results(web_context)

    @post(
        path='/chess-results/chess-results-upload/{event_uniq_id:str}',
        name='chess-results-upload',
    )
    async def htmx_admin_chess_results_upload(self, request: HTMXRequest) -> Template:
        web_context = CRWebContext(request)
        CRBackgroundUploader.upload_event_tournaments(web_context.allowed_tournaments)
        return self._render_upload_results(web_context)

    @post(
        path='/chess-results/chess-results-upload-tournament/{event_uniq_id:str}/{tournament_id:int}',
        name='chess-results-upload-tournament',
    )
    async def htmx_admin_chess_results_upload_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = CRWebContext(request, tournament_id)
        tournament = web_context.get_tournament()

        CRBackgroundUploader.schedule_upload(tournament, True)

        return self._render_upload_results(web_context)

    @patch(
        path='/chess_results/update-event-auto-upload/{event_uniq_id:str}',
        name='chess-results-update-event-auto-upload',
    )
    async def htmx_chess_results_update_event_auto_upload(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = CRWebContext(request)
        event = web_context.get_admin_event()
        plugin_data = CRUtils.get_event_plugin_data(event)
        plugin_data.auto_upload = WebContext.form_data_to_bool(data, 'auto_upload')
        CRUtils.update_event_plugin_data(event, plugin_data)
        for tournament in event.tournaments:
            if not CRUtils.get_tournament_plugin_data(tournament).auto_upload:
                continue
            if plugin_data.auto_upload:
                if CRBackgroundUploader.chess_results_upload_needed(tournament):
                    CRBackgroundUploader.schedule_upload(tournament)
            else:
                CRBackgroundUploader.remove_scheduled_upload(tournament)
        return self._render_upload_results(web_context)

    @patch(
        path='/chess_results/update-tournament-auto-upload/{event_uniq_id:str}/{tournament_id:int}',
        name='chess-results-update-tournament-auto-upload',
    )
    async def htmx_chess_results_update_tournament_auto_upload(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> HTMXTemplate:
        web_context = CRWebContext(request, tournament_id)
        tournament = web_context.get_tournament()

        plugin_data = CRUtils.get_tournament_plugin_data(tournament)
        plugin_data.auto_upload = WebContext.form_data_to_bool(
            data, f'tournament_auto_upload_{tournament.id}'
        )
        CRUtils.update_tournament_plugin_data(tournament, plugin_data)
        if plugin_data.auto_upload:
            if CRBackgroundUploader.chess_results_upload_needed(tournament):
                CRBackgroundUploader.schedule_upload(tournament)
        else:
            CRBackgroundUploader.remove_scheduled_upload(tournament)
        return HTMXTemplate(
            template_name='/chess_results_tournament_statuses.html',
            context=web_context.template_context,
            re_target=f'#tournament-upload-statuses-{tournament.id}',
            re_swap='innerHTML',
        )

    @post(
        path='/chess-results/upload-tournament-from-card/{event_uniq_id:str}/{tournament_id:int}',
        name='chess-results-upload-tournament-from-card',
        guards=[ActionGuard(AuthAction.VIEW_TOURNAMENTS_TAB)],
    )
    async def htmx_ffe_upload_tournament(
        self,
        request: HTMXRequest,
        tournament_id: FromPath[int],
    ) -> Template:
        web_context = CRWebContext(request, tournament_id)
        tournament = web_context.get_tournament()
        CRBackgroundUploader.upload_tournament(tournament.event.uniq_id, tournament.id)
        if CRUtils.get_tournament_plugin_data(tournament).upload_failure_id:
            Message.error(
                request,
                _(
                    'Tournament upload failed, consult Menu > Data '
                    'Transfer > Chess-Results.com for more details.'
                ),
            )
        else:
            Message.success(request, _('Tournament successfully uploaded.'))

        return TournamentAdminController._admin_event_tournaments_render(
            TournamentAdminWebContext(request)
        )
