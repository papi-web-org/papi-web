from io import BytesIO
from pathlib import Path

from logging import Logger
from typing import Annotated
from zipfile import ZipFile, ZipInfo

from litestar import Response, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, File, Redirect
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from web.messages import Message
from web.views import WebContext, AController
from web.views_user import AUserController, EventUserWebContext, TournamentUserWebContext

logger: Logger = get_logger()


class UserDownloadController(AUserController):
    @post(
        path='/user-download-event-tournaments',
        name='user-download-event-tournaments'
    )
    async def htmx_user_download_event_tournaments(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> Response[bytes] | Template:
        web_context: EventUserWebContext = EventUserWebContext(request, data, False)
        if web_context.error:
            return web_context.error
        tournament_files: list[Path] = [
            tournament.file
            for tournament in web_context.user_event.tournaments_by_id.values()
            if tournament.file_exists
        ]
        if not tournament_files:
            return AController.redirect_error(
                request, f'Aucun fichier de tournoi pour l\'évènement [{web_context.user_event.uniq_id}].')
        archive = BytesIO()
        with ZipFile(archive, 'w') as zip_archive:
            for tournament_file in tournament_files:
                zip_entry: ZipInfo = ZipInfo(tournament_file.name)
                with open(tournament_file, 'rb') as tournament_handler:
                    zip_archive.writestr(
                        zip_entry, tournament_handler.read())
        return Response(content=bytes(archive.getbuffer()), media_type='application/zip')

    @post(
        path='/user-download-tournament',
        name='user-download-tournament'
    )
    async def htmx_user_download_tournament(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> File | Template | Redirect:
        web_context: TournamentUserWebContext = TournamentUserWebContext(request, data, None)
        if web_context.error:
            return web_context.error
        if not web_context.tournament.file_exists:
            return AController.redirect_error(
                request, f'Le fichier [{web_context.tournament.file}] n\'existe pas.')
        return File(path=web_context.tournament.file, filename=web_context.tournament.file.name)
