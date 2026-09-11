from copy import copy
from datetime import date
from typing import Annotated, Any

from argon2 import PasswordHasher
from litestar import post, get, delete, patch
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest
from litestar.response import Template
from litestar.status_codes import HTTP_200_OK
from litestar_htmx import HTMXTemplate

from common import is_valid_email
from common.i18n import _
from data.access_levels.access_levels import AccessLevel, AccessLevelScope
from data.access_levels.actions import AuthAction
from data.access_levels.manager import AccessLevelManager
from data.account import Account, Permission
from data.input_output.managers import DataSourceManager
from data.player import Player
from database.sqlite.event.event_store import (
    StoredAccount,
    StoredPermission,
    StoredRole,
)
from plugins.manager import plugin_manager
from plugins.utils import AccountPluginData
from utils.enum import FormAction, RoleType, FideArbiterTitle
from web.controllers.admin.base_event_admin_controller import (
    BaseEventAdminWebContext,
    BaseEventAdminController,
)
from web.controllers.admin.player_admin_controller import PlayerAdminController
from web.controllers.base_controller import WebContext
from web.guards import EventGuard, ActionGuard, ManageAccountGuard
from web.messages import Message
from web.session import SessionAccountsShowDetails, SessionPlayersActiveDataSource
from web.utils import RequestUtils, SelectOption


class AccountAdminWebContext(BaseEventAdminWebContext):
    def __init__(self, request: HTMXRequest, reload_event: bool = False):
        super().__init__(request, reload_event=reload_event)
        assert self.admin_event is not None
        self.admin_account: Account | None = RequestUtils.get_optional_account(request)
        self.admin_permission: Permission | None = None
        access_level = RequestUtils.get_optional_access_level(request)
        if access_level:
            assert self.admin_account is not None
            self.admin_permission = next(
                (
                    permission
                    for permission in self.admin_account.permissions
                    if permission.access_level == access_level
                ),
                None,
            )
            if not self.admin_permission:
                raise NotFoundException(
                    f'Unknown access level [{access_level}] for '
                    f'account [{self.admin_account.full_name}].'
                )

    def get_admin_account(self) -> Account:
        assert self.admin_account is not None
        return self.admin_account

    def get_admin_permission(self) -> Permission:
        assert self.admin_permission is not None
        return self.admin_permission

    @property
    def template_context(self) -> dict[str, Any]:
        return super().template_context | {
            'admin_event_tab': 'admin-event-accounts-tab',
            'show_details': SessionAccountsShowDetails(self.request).get(),
            'admin_account': self.admin_account,
            'admin_permission': self.admin_permission,
            'data_sources': DataSourceManager().objects(),
            'selected_data_source': SessionPlayersActiveDataSource(self.request).get(),
        }


class AccountAdminController(BaseEventAdminController):
    guards = [
        EventGuard(),
        ActionGuard(AuthAction.MANAGE_ACCOUNTS),
        ManageAccountGuard(),
    ]

    @classmethod
    def admin_event_account_render(
        cls,
        web_context: AccountAdminWebContext,
        template_context: dict[str, Any] | None = None,
    ) -> Template:
        return cls._admin_base_event_render(
            web_context.template_context | (template_context or {})
        )

    @get(
        path='/event/{event_uniq_id:str}/accounts',
        name='admin-event-accounts-tab',
    )
    async def htmx_admin_event_accounts_tab(
        self,
        request: HTMXRequest,
        show_details: FromQuery[bool | None],
    ) -> Template:
        if show_details is not None:
            SessionAccountsShowDetails(request).set(show_details)
        return self.admin_event_account_render(AccountAdminWebContext(request))

    # --------------------------------------------------------------------------
    # Accounts
    # --------------------------------------------------------------------------

    @classmethod
    def _account_form_modal_context(
        cls,
        web_context: AccountAdminWebContext,
        action: FormAction,
        data: dict[str, str],
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        admin_event = web_context.get_admin_event()
        plugin_results = plugin_manager.hook_for_event(
            admin_event, 'get_account_form_fields_template_and_data'
        )()

        plugin_form_fields_templates = [template for template, __ in plugin_results]
        form_fields_templates_data = {
            key: value for __, data in plugin_results for key, value in data.items()
        }

        default_data = WebContext.values_dict_to_form_data(
            {
                'first_name': '',
                'last_name': '',
                'fide_id': '',
                'fide_arbiter_title': '',
                'password': '',
                'mail': '',
                'phone': '',
                'active': True,
                'access_levels': [],
                'tournament_ids': [],
                'chief_tournament_ids': [],
                'deputy_tournament_ids': [],
                'arbiter_tournament_ids': [],
            }
        )
        fide_arbiter_title_options = {'': '-'} | {
            title.value: title.name for title in FideArbiterTitle
        }
        form_data = default_data | data
        return {
            'fide_arbiter_title_options': fide_arbiter_title_options,
            'plugin_form_fields_templates': plugin_form_fields_templates,
            'modal': 'account',
            'action': action,
            'tournament_options': web_context.get_tournament_options(),
            'data': form_data,
            'errors': errors or {},
        } | form_fields_templates_data

    @staticmethod
    def _account_form_data_from_account(account: Account) -> dict[str, str]:
        stored_account = account.stored_account

        stored_plugin_data = stored_account.plugin_data
        plugin_form_data: dict[str, str] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Account.plugin_data_class_by_plugin_id().items():
            plugin_form_data |= plugin_data_class.from_stored_value(
                stored_plugin_data.get(plugin_id, {})
            ).to_form_data()

        chief_role = account.get_role(RoleType.CHIEF_ARBITER)
        deputy_role = account.get_role(RoleType.DEPUTY_ARBITER)
        arbiter_role = account.get_role(RoleType.ARBITER)

        return WebContext.values_dict_to_form_data(
            {
                'first_name': stored_account.first_name,
                'last_name': stored_account.last_name,
                'active': stored_account.active,
                'fide_id': stored_account.fide_id,
                'fide_arbiter_title': stored_account.fide_arbiter_title,
                'mail': stored_account.mail,
                'phone': stored_account.phone,
                'chief_tournament_ids': chief_role.tournament_ids or [],
                'deputy_tournament_ids': deputy_role.tournament_ids or [],
                'arbiter_tournament_ids': arbiter_role.tournament_ids or [],
            }
            | plugin_form_data
        )

    @post(
        path='/account-modal/from-search/{event_uniq_id:str}/{data_source_id:str}/{player_source_id:str}',
        name='account-modal-from-search',
    )
    async def htmx_account_modal_from_search(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
        data_source_id: FromPath[str],
        player_source_id: FromPath[str],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        try:
            data_source = DataSourceManager().get_object(data_source_id)
        except KeyError:
            raise NotFoundException(f'Unknown data source [{data_source_id}].')

        stored_player, errors = await PlayerAdminController.get_search_stored_player(
            data_source, player_source_id, date.today()
        )
        if stored_player:
            stored_account = StoredAccount(
                id=0,
                active=True,
                first_name=stored_player.first_name,
                last_name=stored_player.last_name,
                fide_id=stored_player.fide_id,
                fide_arbiter_title=stored_player.transient_arbiter_titles.get(
                    'fide', ''
                ),
                mail=WebContext.form_data_to_str(data, 'mail'),
                phone=WebContext.form_data_to_str(data, 'phone'),
                plugin_data={
                    plugin_id: plugin_data_class.from_stored_player(
                        stored_player
                    ).to_stored_value()
                    for plugin_id, plugin_data_class in Account.plugin_data_class_by_plugin_id().items()
                },
            )
            data = self._account_form_data_from_account(Account(stored_account))
        template_context = self._account_form_modal_context(
            web_context, FormAction.CREATE, data, errors
        )
        return HTMXTemplate(
            template_name='/admin/accounts/account_information_form_section.html',
            context=web_context.template_context | template_context,
            re_target='#information-section',
            re_swap='outerHTML',
        )

    @get(
        path='/account-modal/create/{event_uniq_id:str}',
        name='admin-account-create-modal',
    )
    async def htmx_admin_account_create_modal(self, request: HTMXRequest) -> Template:
        web_context = AccountAdminWebContext(request)
        template_context = self._account_form_modal_context(
            web_context, FormAction.CREATE, {}
        )
        return self.admin_event_account_render(web_context, template_context)

    @get(
        path='/account-modal/update/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-update-modal',
    )
    async def htmx_admin_account_update_modal(self, request: HTMXRequest) -> Template:
        web_context = AccountAdminWebContext(request)
        template_context = self._account_form_modal_context(
            web_context,
            FormAction.UPDATE,
            self._account_form_data_from_account(web_context.get_admin_account()),
        )
        return self.admin_event_account_render(web_context, template_context)

    @get(
        path='/account-modal/clone/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-clone-modal',
    )
    async def htmx_admin_account_clone_modal(self, request: HTMXRequest) -> Template:
        web_context = AccountAdminWebContext(request)
        account = web_context.get_admin_account()
        template_context = self._account_form_modal_context(
            web_context,
            FormAction.CLONE,
            self._account_form_data_from_account(account)
            | {'chief_tournament_ids': ''},
        )
        return self.admin_event_account_render(web_context, template_context)

    @get(
        path='/account-modal/delete/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-delete-modal',
    )
    async def htmx_admin_account_delete_modal(self, request: HTMXRequest) -> Template:
        return self.admin_event_account_render(
            AccountAdminWebContext(request),
            {'modal': 'account_delete'},
        )

    @post(
        path='/account-create-defaults/{event_uniq_id:str}',
        name='admin-account-create-defaults',
    )
    async def htmx_admin_account_create_defaults(
        self, request: HTMXRequest
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        web_context.get_admin_event().create_predefined_accounts()
        Message.success(request, _('Default accounts have been created.'))
        return self.admin_event_account_render(web_context)

    @staticmethod
    def _read_account_form_data(
        data: dict[str, Any],
        web_context: AccountAdminWebContext,
        action: FormAction,
    ) -> tuple[StoredAccount | None, dict[str, str]]:
        errors: dict[str, str] = {}
        event = web_context.get_admin_event()
        account = web_context.admin_account

        flat_data = WebContext.flatten_list_data(data)

        first_name = WebContext.form_data_to_str(flat_data, 'first_name') or ''
        last_name = WebContext.form_data_to_str(flat_data, field := 'last_name') or ''
        fide_id = WebContext.form_data_to_int(flat_data, 'fide_id')
        fide_arbiter_title = (
            WebContext.form_data_to_str(flat_data, 'fide_arbiter_title') or ''
        )

        if not last_name:
            errors[field] = _('This field is required.')
        if 'first_name' not in errors and 'last_name' not in errors:
            full_name = Player.player_full_name(first_name, last_name)
            check_full_name_not_used: bool
            if account and action == FormAction.UPDATE:
                check_full_name_not_used = account.full_name != Player.player_full_name(
                    first_name, last_name
                )
            else:
                check_full_name_not_used = True
            if check_full_name_not_used and full_name in (
                account.full_name for account in event.accounts_by_id.values()
            ):
                errors[field] = _('Account [{account_name}] already exists.').format(
                    account_name=full_name
                )

        password = WebContext.form_data_to_str(flat_data, 'password')
        password_hash: str | None
        if not password:
            if action == FormAction.UPDATE:
                assert account is not None
                password_hash = account.password_hash
            else:
                password_hash = None
        else:
            password_hash = PasswordHasher().hash(password)

        mail = WebContext.form_data_to_str(flat_data, field := 'mail')
        if mail and not is_valid_email(mail):
            errors[field] = _('Please supply a valid email address.')
        phone = WebContext.form_data_to_str(flat_data, field := 'phone')

        chief_tournament_ids = WebContext.form_data_to_list_int(
            flat_data, 'chief_tournament_ids'
        )
        deputy_tournament_ids = WebContext.form_data_to_list_int(
            flat_data, 'deputy_tournament_ids'
        )
        arbiter_tournament_ids = WebContext.form_data_to_list_int(
            flat_data, 'arbiter_tournament_ids'
        )
        tournament_ids_by_field = {
            'chief_tournament_ids': chief_tournament_ids,
            'deputy_tournament_ids': deputy_tournament_ids,
            'arbiter_tournament_ids': arbiter_tournament_ids,
        }
        seen_tournament_ids: set[int] = set()
        for field, tournament_ids in tournament_ids_by_field.items():
            if seen_tournament_ids.intersection(tournament_ids):
                errors[field] = _(
                    'Cannot have multiple arbiter roles on the same tournament.'
                )
            seen_tournament_ids.update(tournament_ids)
        stored_roles: list[StoredRole] = []
        if chief_tournament_ids:
            stored_roles.append(
                StoredRole(
                    account_id=None,
                    role=RoleType.CHIEF_ARBITER.value,
                    tournament_ids=chief_tournament_ids,
                )
            )
        if deputy_tournament_ids:
            stored_roles.append(
                StoredRole(
                    account_id=None,
                    role=RoleType.DEPUTY_ARBITER.value,
                    tournament_ids=deputy_tournament_ids,
                )
            )
        if arbiter_tournament_ids:
            stored_roles.append(
                StoredRole(
                    account_id=None,
                    role=RoleType.ARBITER.value,
                    tournament_ids=arbiter_tournament_ids,
                )
            )

        plugin_manager.hook_for_event(
            web_context.get_admin_event(), 'validate_account_form_fields'
        )(
            data=data,
            errors=errors,
        )

        if errors:
            return None, errors

        plugin_data: dict[str, dict[str, Any]] = {}
        for (
            plugin_id,
            plugin_data_class,
        ) in Account.plugin_data_class_by_plugin_id().items():
            previous_object: AccountPluginData | None = None
            if account is not None:
                previous_object = account.plugin_data.get(plugin_id)

            plugin_data[plugin_id] = plugin_data_class.from_form_data(
                data, action=action, previous_object=previous_object
            ).to_stored_value()

        stored_account = StoredAccount(
            id=account.id if account and action == FormAction.UPDATE else None,
            active=WebContext.form_data_to_bool(flat_data, 'active'),
            last_name=last_name,
            first_name=first_name,
            fide_id=fide_id,
            fide_arbiter_title=fide_arbiter_title,
            password_hash=password_hash,
            mail=mail,
            phone=phone,
            stored_roles=stored_roles,
            plugin_data=plugin_data,
        )
        return stored_account, errors

    @post(path='/account-create/{event_uniq_id:str}', name='admin-account-create')
    async def htmx_admin_account_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        stored_account, errors = self._read_account_form_data(
            data, web_context, FormAction.CREATE
        )
        if not stored_account:
            return self.admin_event_account_render(
                web_context,
                self._account_form_modal_context(
                    web_context,
                    FormAction.CREATE,
                    WebContext.values_dict_to_form_data(data),
                    errors,
                ),
            )
        event = web_context.get_admin_event()
        stored_account.stored_permissions = copy(
            event.anonymous_account.stored_account.stored_permissions
        )
        account = event.create_account(stored_account)

        Message.success(
            request,
            _('Account [{account_name}] has been created.').format(
                account_name=account.full_name
            ),
        )
        web_context = AccountAdminWebContext(request, reload_event=True)
        return self.admin_event_account_render(web_context)

    @patch(
        path='/account-update/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-update',
    )
    async def htmx_admin_account_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        stored_account, errors = self._read_account_form_data(
            data, web_context, FormAction.UPDATE
        )
        if not stored_account:
            return self.admin_event_account_render(
                web_context,
                self._account_form_modal_context(
                    web_context,
                    FormAction.UPDATE,
                    WebContext.values_dict_to_form_data(data),
                    errors,
                ),
            )
        event = web_context.get_admin_event()
        account = web_context.get_admin_account()
        stored_account.id = account.id
        stored_account.stored_permissions = copy(
            account.stored_account.stored_permissions
        )
        event.update_account(stored_account)
        Message.success(
            request,
            _('Account [{account_name}] has been updated.').format(
                account_name=account.full_name
            ),
        )
        web_context = AccountAdminWebContext(request, reload_event=True)
        return self.admin_event_account_render(web_context)

    @post(
        path='/account-clone/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-clone',
    )
    async def htmx_admin_account_clone(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        stored_account, errors = self._read_account_form_data(
            data, web_context, FormAction.CLONE
        )
        if not stored_account:
            return self.admin_event_account_render(
                web_context,
                self._account_form_modal_context(
                    web_context,
                    FormAction.CLONE,
                    WebContext.values_dict_to_form_data(data),
                    errors,
                ),
            )
        event = web_context.get_admin_event()
        cloned_account = web_context.get_admin_account()
        stored_account.stored_permissions = copy(
            cloned_account.stored_account.stored_permissions
        )
        account = event.create_account(stored_account)
        Message.success(
            request,
            _('Account [{account_name}] has been created.').format(
                account_name=account.full_name
            ),
        )
        web_context = AccountAdminWebContext(request, reload_event=True)
        return self.admin_event_account_render(web_context)

    @delete(
        path='/account-delete/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_account_delete(self, request: HTMXRequest) -> Template:
        web_context = AccountAdminWebContext(request)
        event = web_context.get_admin_event()
        account = web_context.get_admin_account()
        event.delete_account(account)
        Message.success(
            request,
            _('Account [{account_name}] has been deleted.').format(
                account_name=account.full_name
            ),
        )
        web_context = AccountAdminWebContext(request, reload_event=True)
        return self.admin_event_account_render(web_context)

    # --------------------------------------------------------------------------
    # Account permissions
    # --------------------------------------------------------------------------

    @classmethod
    def _permissions_modal_context(
        cls, web_context: AccountAdminWebContext
    ) -> dict[str, Any]:
        return {
            'modal': 'account_permissions',
            'can_add_permission': bool(cls._selectable_access_levels(web_context)),
        }

    @classmethod
    def _selectable_access_levels(
        cls, web_context: AccountAdminWebContext
    ) -> list[AccessLevel]:
        return cls._permission_form_modal_context(web_context, FormAction.CREATE)[
            'selectable_access_levels'
        ]

    @staticmethod
    def _permission_form_modal_context(
        web_context: AccountAdminWebContext,
        action: FormAction,
        data: dict[str, str] | None = None,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        account = web_context.get_admin_account()
        permission = web_context.admin_permission
        manageable_access_levels = web_context.client.manageable_access_levels
        if account.anonymous:
            manageable_access_levels = [
                access_level
                for access_level in manageable_access_levels
                if not access_level.needs_account
            ]
        permissions_by_access_level = account.get_permissions_by_access_level(
            avoid_access_level=permission.access_level if permission else None
        )
        current_access_levels = account.access_levels
        if permission:
            current_access_levels.remove(permission.access_level)
        inherited_permissions_by_access_level = {
            access_level: permission_
            for access_level, permission_ in permissions_by_access_level.items()
            if permission_.inherited and permission_.tournament_ids is None
        }
        not_selectable = current_access_levels + list(
            inherited_permissions_by_access_level
        )
        selectable_access_levels = [
            access_level
            for access_level in manageable_access_levels
            if access_level not in not_selectable
        ]
        tournament_access_level_ids = [
            access_level.id
            for access_level in manageable_access_levels
            if access_level.scope == AccessLevelScope.TOURNAMENT
        ]
        access_level_options: dict[str, SelectOption] = {}
        for access_level in manageable_access_levels:
            tooltip = access_level.help_text
            if access_level in current_access_levels:
                tooltip = _('Access level already defined for the account.')
            if access_level in inherited_permissions_by_access_level:
                tooltip = _('Inherited by permission [{permission}].').format(
                    permission=getattr(
                        inherited_permissions_by_access_level[
                            access_level
                        ].inherited_by,
                        'name',
                    )
                )
            access_level_options[access_level.id] = SelectOption(
                name=access_level.name,
                tooltip=tooltip,
                disabled=access_level in not_selectable,
            )
        default_data = WebContext.values_dict_to_form_data(
            {
                'access_level': (
                    selectable_access_levels[0].id if selectable_access_levels else None
                ),
                'tournament_ids': None,
            }
        )
        return {
            'modal': 'account_permission_form',
            'action': action,
            'access_level_options': access_level_options,
            'selectable_access_levels': selectable_access_levels,
            'tournament_access_level_ids': tournament_access_level_ids,
            'tournament_options': web_context.get_tournament_options(),
            'data': default_data | (data or {}),
            'errors': errors or {},
        }

    @get(
        path='/account-permissions-modal/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-permissions-modal',
    )
    async def htmx_admin_account_permissions_modal(
        self, request: HTMXRequest
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        return self.admin_event_account_render(
            web_context, self._permissions_modal_context(web_context)
        )

    @get(
        path='/account-permission-create-modal/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-permission-create-modal',
    )
    async def htmx_admin_account_permission_create_modal(
        self, request: HTMXRequest
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        template_context = self._permission_form_modal_context(
            web_context, FormAction.CREATE
        )
        return self.admin_event_account_render(web_context, template_context)

    @get(
        path=(
            '/account-permission-update-modal/'
            '{event_uniq_id:str}/{account_id:int}/{access_level:str}'
        ),
        name='admin-account-permission-update-modal',
    )
    async def htmx_admin_account_permission_update_modal(
        self, request: HTMXRequest
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        permission = web_context.get_admin_permission()
        data = WebContext.values_dict_to_form_data(
            {
                'access_level': permission.access_level.id,
                'tournament_ids': list(permission.tournament_ids or []),
            }
        )
        template_context = self._permission_form_modal_context(
            web_context, FormAction.UPDATE, data
        )
        return self.admin_event_account_render(web_context, template_context)

    @classmethod
    def _validate_permission_form_data(
        cls, web_context: AccountAdminWebContext, data: dict[str, str]
    ) -> dict[str, str]:
        account = web_context.get_admin_account()
        errors: dict[str, str] = {}
        access_level_id = (
            WebContext.form_data_to_str(data, field := 'access_level') or ''
        )
        try:
            access_level = AccessLevelManager().get_object(access_level_id)
        except KeyError:
            errors[field] = f'Unknown access level [{access_level_id}].'
            return errors

        if access_level not in cls._selectable_access_levels(web_context):
            errors[field] = (
                f'You are not allowed to set access level [{access_level.id}].'
            )
        if access_level.scope == AccessLevelScope.TOURNAMENT:
            tournament_ids = WebContext.form_data_to_list_int(
                data, field := 'tournament_ids'
            )
            if not tournament_ids:
                return errors
            event = web_context.get_admin_event()
            for tournament_id in tournament_ids:
                if tournament_id not in event.tournaments_by_id:
                    errors[field] = (
                        f'Invalid tournament ID [{tournament_id}] '
                        f'for event in [{event.uniq_id}].'
                    )
            permissions_by_access_level = account.get_permissions_by_access_level(
                avoid_access_level=getattr(
                    web_context.admin_permission, 'access_level', None
                )
            )
            if access_level in permissions_by_access_level:
                permission = permissions_by_access_level[access_level]
                if permission.tournament_ids and set(tournament_ids).issubset(
                    permission.tournament_ids
                ):
                    errors[field] = _(
                        'These tournaments are already included for '
                        'this account by a higher access level.'
                    )

        return errors

    @post(
        path='/account-permission-create/{event_uniq_id:str}/{account_id:int}',
        name='admin-account-permission-create',
    )
    async def htmx_admin_account_permission_create(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        event = web_context.get_admin_event()
        account = web_context.get_admin_account()
        flat_data = WebContext.flatten_list_data(data)
        if errors := self._validate_permission_form_data(web_context, flat_data):
            template_context = self._permission_form_modal_context(
                web_context, FormAction.CREATE, flat_data, errors
            )
            return self.admin_event_account_render(web_context, template_context)
        access_level = AccessLevelManager().get_object(
            WebContext.form_data_to_str(flat_data, 'access_level') or ''
        )
        stored_permission = StoredPermission(
            account_id=account.id, access_level=access_level.id
        )
        if access_level.scope == AccessLevelScope.TOURNAMENT:
            stored_permission.tournament_ids = WebContext.form_data_to_list_int(
                flat_data, 'tournament_ids'
            )
        event.add_account_permission(account, stored_permission)
        web_context.admin_permission = None
        return self.admin_event_account_render(
            web_context, self._permissions_modal_context(web_context)
        )

    @patch(
        path=(
            '/account-permission-update/'
            '{event_uniq_id:str}/{account_id:int}/{access_level:str}'
        ),
        name='admin-account-permission-update',
    )
    async def htmx_admin_account_permission_update(
        self,
        request: HTMXRequest,
        data: Annotated[
            dict[str, str | list[str]],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        event = web_context.get_admin_event()
        account = web_context.get_admin_account()
        permission = web_context.get_admin_permission()
        flat_data = WebContext.flatten_list_data(data)
        if errors := self._validate_permission_form_data(web_context, flat_data):
            template_context = self._permission_form_modal_context(
                web_context, FormAction.UPDATE, flat_data, errors
            )
            return self.admin_event_account_render(web_context, template_context)
        access_level_ = AccessLevelManager().get_object(
            WebContext.form_data_to_str(flat_data, 'access_level') or ''
        )
        stored_permission = StoredPermission(
            account_id=account.id, access_level=access_level_.id
        )
        if access_level_.scope == AccessLevelScope.TOURNAMENT:
            stored_permission.tournament_ids = WebContext.form_data_to_list_int(
                flat_data, 'tournament_ids'
            )
        event.update_account_permission(account, permission, stored_permission)
        web_context.admin_permission = None
        return self.admin_event_account_render(
            web_context, self._permissions_modal_context(web_context)
        )

    @delete(
        path=(
            '/account-permission-delete/'
            '{event_uniq_id:str}/{account_id:int}/{access_level:str}'
        ),
        name='admin-account-permission-delete',
        status_code=HTTP_200_OK,
    )
    async def htmx_admin_account_permission_delete(
        self, request: HTMXRequest
    ) -> Template:
        web_context = AccountAdminWebContext(request)
        event = web_context.get_admin_event()
        account = web_context.get_admin_account()
        permission = web_context.get_admin_permission()
        event.delete_account_permission(account, permission)
        web_context.admin_permission = None
        return self.admin_event_account_render(
            web_context, self._permissions_modal_context(web_context)
        )
