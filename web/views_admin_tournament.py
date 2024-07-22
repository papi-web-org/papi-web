import re
from logging import Logger
from typing import Annotated

from litestar import post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate

from common.logger import get_logger
from data.tournament import Tournament
from data.event import Event, get_events_by_uniq_id
from web.messages import Message
from web.views_admin import AAdminController

logger: Logger = get_logger()


class AdminTournamentController(AAdminController):
    @staticmethod
    def _admin_validate_tournament_update_data(
            admin_event: Event,
            admin_tournament: Tournament,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        tournament_uniq_id: str = data.get('tournament_uniq_id', '')
        if not tournament_uniq_id:
            errors['tournament_uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
        else:
            if tournament_uniq_id.find('/') != -1:
                errors['tournament_uniq_id'] = "le caractère « / » n\'est pas autorisé"
            else:
                if admin_tournament:
                    if (tournament_uniq_id != admin_tournament.uniq_id
                            and tournament_uniq_id in admin_event.tournaments):
                        errors['tournament_uniq_id'] = \
                            f'Un autre tournoi avec l\'identifiant [{tournament_uniq_id}] existe déjà.'
                else:
                    if tournament_uniq_id in admin_event.tournaments:
                        errors['tournament_uniq_id'] = f'Le tournoi [{tournament_uniq_id}] existe déjà.'
        tournament_path: str = data.get('tournament_path', '')
        if not tournament_path:
            errors['tournament_path'] = 'Veuillez entrer le répertoire du fichier Papi.'
        tournament_filename: str = data.get('tournament_filename', '')
        tournament_ffe_id: str = data.get('tournament_ffe_id', '')
        if not tournament_filename and not tournament_ffe_id:
            error: str = 'Veuillez entrer le nom du fichier Papi ou le numéro d\'homologation FFE.'
            errors['tournament_filename'] = error
            errors['tournament_ffe_id'] = error
        tournament_ffe_password: str = data.get('tournament_ffe_password', '')
        if tournament_ffe_password and not re.match('^[A-Z]{10}$', tournament_ffe_password):
            errors['tournament_ffe_id'] = \
                'Le mot de passe du tournoi sur le site FFE doit être composé de 10 lettres majuscules.'
        return errors

    @staticmethod
    def _admin_tournament_render_edit_modal(
            admin_event: Event,
            admin_tournament: Tournament | None,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_tournament_edit_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'admin_tournament': admin_tournament,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-tournament-render-edit-modal',
        name='admin-tournament-render-edit-modal'
    )
    async def htmx_admin_tournament_render_edit_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_tournament_uniq_id: str = data.get('admin_tournament_uniq_id', '')
        admin_tournament: Tournament | None = None
        if admin_tournament_uniq_id:
            try:
                admin_tournament = admin_event.tournaments[
                    admin_tournament_uniq_id]
                data: dict[str, str] = {
                    'tournament_uniq_id': admin_tournament.uniq_id,
                    'tournament_name': admin_tournament.name,
                }
            except KeyError:
                Message.error(request, f'Le tournoi [{admin_tournament_uniq_id}] est introuvable.')
                return self._render_messages(request)
        else:
            data: dict[str, str] = {}
        errors: dict[str, str] = self._admin_validate_tournament_update_data(admin_event, admin_tournament, data)
        return self._admin_tournament_render_edit_modal(admin_event, admin_tournament, data, errors)

    @post(
        path='/admin-tournament-update',
        name='admin-tournament-update'
    )
    async def htmx_admin_tournament_update(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_tournament_uniq_id: str = data.get('admin_tournament_uniq_id', '')
        admin_tournament: Tournament | None = None
        if admin_tournament_uniq_id:
            try:
                admin_tournament = admin_event.tournaments[
                    admin_tournament_uniq_id]
            except KeyError:
                Message.error(request, f'Le tournoi [{admin_tournament_uniq_id}] est introuvable.')
                return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_tournament_update_data(
            admin_event, admin_tournament, data)
        if errors:
            return self._admin_tournament_render_edit_modal(
                admin_event, admin_tournament, data, errors)
        if admin_tournament:
            # TODO Update the tournament
            # admin_event: Event = UPDATE_TOURNAMENT(data)
            # Message.success(
            #     request, f'Lr tournoi [{admin_tournament.uniq_id}] a été modifié.')
            # admin_event.tournaments[admin_tournament.uniq_id] = admin_tournament
            # if data['tournament_uniq_id'] != admin_tournament.uniq_id:
            #     delete admin_event.tournaments['tournament_uniq_id'])
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(
            #     request, events, admin_event=admin_event, admin_tournament=admin_tournament)
            Message.error(
                request,
                f'La modification des tournois par l\'interface web n\'est pas encore implémentée.')
        else:
            # TODO Create the tournament
            # admin_tournament: Tournament = CREATE_TOURNAMENT(data)
            # Message.success(request, f'Le tournoi [{admin_tournaments.uniq_id}] a été créé.')
            # admin_event.tournaments[admin_tournament.uniq_id] = admin_tournament
            events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
            # return _admin_render_index(
            #     request, events, admin_event=admin_event, admin_tournament=admin_tournament)
            Message.error(request,
                          f'La création des tournois par l\'interface web n\'est pas encore implémentée.')
        return self._admin_render_index(
            request, events, admin_event=admin_event, admin_event_selector='@tournaments')

    @staticmethod
    def _admin_validate_tournament_delete_data(
            admin_tournament: Tournament,
            data: dict[str, str] | None = None,
    ) -> dict[str, str]:
        errors: dict[str, str] = {}
        if data is None:
            data = {}
        tournament_uniq_id: str = data.get('tournament_uniq_id', '')
        if not tournament_uniq_id:
            errors['tournament_uniq_id'] = 'Veuillez entrer l\'identifiant du tournoi.'
        elif tournament_uniq_id != admin_tournament.uniq_id:
            errors['tournament_uniq_id'] = f'L\'identifiant entré n\'est pas valide.'
        return errors

    @staticmethod
    def _admin_tournament_render_delete_modal(
            admin_event: Event,
            admin_tournament: Tournament,
            data: dict[str, str] | None = None,
            errors: dict[str, str] | None = None,
    ) -> Template:
        return HTMXTemplate(
            template_name='admin_tournament_delete_modal.html',
            re_swap='innerHTML',
            re_target='#admin-modal-container',
            context={
                'admin_event': admin_event,
                'admin_tournament': admin_tournament,
                'data': data,
                'errors': errors,
            })

    @post(
        path='/admin-tournament-render-delete-modal',
        name='admin-tournament-render-delete-modal'
    )
    async def htmx_admin_event_render_delete_modal(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_tournament_uniq_id: str = data.get('admin_tournament_uniq_id', '')
        try:
            admin_tournament: Tournament = admin_event.tournaments[admin_tournament_uniq_id]
            data: dict[str, str] = {}
            errors: dict[str, str] = self._admin_validate_tournament_delete_data(admin_tournament, data)
            return self._admin_tournament_render_delete_modal(admin_event, admin_tournament, data, errors)
        except KeyError:
            Message.error(request, f'La connexion à ChessEvent [{admin_tournament_uniq_id}] est introuvable.')
            return self._render_messages(request)

    @post(
        path='/admin-tournament-delete',
        name='admin-tournament-delete'
    )
    async def htmx_admin_event_delete(
            self, request: HTMXRequest,
            data: Annotated[
                dict[str, str],
                Body(media_type=RequestEncodingType.URL_ENCODED),
            ],
    ) -> Template:
        events_by_id: dict[str, Event] = get_events_by_uniq_id(load_screens=False, with_tournaments_only=False)
        admin_event_uniq_id: str = data.get('admin_event_uniq_id', '')
        try:
            admin_event: Event = events_by_id[admin_event_uniq_id]
        except KeyError:
            Message.error(request, f'L\'évènement [{admin_event_uniq_id}] est introuvable.')
            return self._render_messages(request)
        admin_tournament_uniq_id: str = data.get('admin_tournament_uniq_id', '')
        try:
            admin_tournament: Tournament = admin_event.tournaments[admin_tournament_uniq_id]
        except KeyError:
            Message.error(request, f'La connexion à ChessEvent [{admin_tournament_uniq_id}] est introuvable.')
            return self._render_messages(request)
        errors: dict[str, str] = self._admin_validate_tournament_delete_data(admin_tournament, data)
        if errors:
            return self._admin_tournament_render_delete_modal(admin_event, admin_tournament, data, errors)
        # TODO Delete the tournament
        # DELETE_TOURNAMENT(data)
        # Message.success(
        #     request, f'Le tournoi [{admin_tournament.uniq_id}] a été supprimé.')
        # del admin_event.tournaments[admin_tournament.uniq_id]
        Message.error(request,
                      f'La suppression des tournois par l\'interface web n\'est pas encore implémentée.')
        events: list[Event] = sorted(events_by_id.values(), key=lambda event: event.name)
        return self._admin_render_index(request, events, admin_event=admin_event, admin_event_selector='@tournaments')
