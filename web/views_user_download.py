from io import BytesIO
from pathlib import Path

from logging import Logger
from zipfile import ZipFile, ZipInfo

from litestar import get, Response
from litestar.response import Template, File
from litestar.contrib.htmx.request import HTMXRequest

from common.logger import get_logger
from data.loader import EventLoader
from data.tournament import NewTournament
from web.messages import Message
from web.views_user_index import AUserController

logger: Logger = get_logger()


class UserDownloadController(AUserController):
    @get(
        path='/user-download-event-tournaments/{event_uniq_id:str}',
        name='user-download-event-tournaments'
    )
    async def htmx_user_download_event_tournaments(
            self, request: HTMXRequest, event_uniq_id: str
    ) -> Response[bytes] | Template:
        response, event = self._load_event_context(
            request, EventLoader.get(request=request, lazy_load=False), event_uniq_id)
        if response:
            return response
        tournament_files: list[Path] = [
            tournament.file
            for tournament in event.tournaments_by_id.values()
            if tournament.file_exists
        ]
        if not tournament_files:
            Message.error(request, f'Aucun fichier de tournoi pour l\'évènement [{event_uniq_id}].')
            return self._render_messages(request)
        archive = BytesIO()
        with ZipFile(archive, 'w') as zip_archive:
            for tournament_file in tournament_files:
                zip_entry: ZipInfo = ZipInfo(tournament_file.name)
                with open(tournament_file, 'rb') as tournament_handler:
                    zip_archive.writestr(
                        zip_entry, tournament_handler.read())
        return Response(content=bytes(archive.getbuffer()), media_type='application/zip')

    @get(
        path='/user-download-tournament/{event_uniq_id:str}/{tournament_uniq_id:str}',
        name='user-download-tournament'
    )
    async def htmx_user_download_tournament(
            self, request: HTMXRequest, event_uniq_id: str, tournament_id: int
    ) -> File | Template:
        response, event = self._load_event_context(
            request, EventLoader.get(request=request, lazy_load=False), event_uniq_id)
        if response:
            return response
        try:
            tournament: NewTournament = event.tournaments_by_id[tournament_id]
        except KeyError:
            Message.error(request, f'Le tournoi [{tournament_id}] n\'existe pas.')
            return self._render_messages(request)
        if not tournament.file_exists:
            Message.error(request, f'Le fichier [{tournament.file}] n\'existe pas.')
            return self._render_messages(request)
        return File(path=tournament.file, filename=tournament.file.name)
