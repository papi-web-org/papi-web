from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash
from text_unidecode import unidecode
from litestar import post, get
from litestar.enums import RequestEncodingType
from litestar.params import Body, FromPath, FromQuery
from litestar.plugins.htmx import HTMXRequest
from litestar.response import Template
from litestar_htmx import HTMXTemplate, ClientRedirect

from common.i18n import _
from data.account import Account
from data.event import Event
from database.sqlite.event.event_database import EventDatabase
from web.controllers.admin.base_admin_controller import AdminWebContext
from web.controllers.admin.base_event_admin_controller import BaseEventAdminWebContext
from web.controllers.base_controller import WebContext, BaseController
from web.guards import EventGuard
from web.login_throttle import LoginThrottle, login_throttle_keys
from web.messages import Message
from web.session import SessionUserAccountId, SessionUserAccountPasswordHash
from web.urls import admin_event_url


class ProfileWebContext(BaseEventAdminWebContext):
    @classmethod
    def get_active_user_account_options(
        cls, active_user_accounts: list[Account]
    ) -> dict[str, str]:
        return {
            cls.value_to_form_data(account.id): account.full_name
            for account in active_user_accounts
            if account.active
        }


class ProfileController(BaseController):
    guards = [EventGuard()]

    @staticmethod
    def _comparable(value: str) -> str:
        """A name reduced to what someone typing it on a phone can be expected
        to get right: no accents, no case, no doubled spaces."""
        return ' '.join(unidecode(value).casefold().split())

    @classmethod
    def _account_id_named(cls, accounts: list[Account], typed: str) -> int | None:
        """The account the typed name identifies, or None.

        Unused while the list of accounts is shown to remote clients as well as
        local ones. Kept for when it is not: what someone types then has to be
        met halfway — the full name in either order, the surname on its own when
        only one account bears it, or the address the account was given. What is
        never accepted is a name matching more than one account, which would log
        somebody in as a colleague."""
        if not typed:
            return None
        comparable = cls._comparable(typed)
        if not comparable:
            return None

        def matches(account: Account) -> bool:
            names = {cls._comparable(account.full_name)}
            if account.first_name:
                names.add(cls._comparable(f'{account.last_name} {account.first_name}'))
            names.add(cls._comparable(account.last_name))
            if account.mail:
                names.add(cls._comparable(account.mail))
            return comparable in names

        matching = [account for account in accounts if matches(account)]
        return matching[0].id if len(matching) == 1 else None

    @classmethod
    def _render_profile_modal(
        cls,
        web_context: AdminWebContext,
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ]
        | None = None,
        errors: dict[str, str] | None = None,
    ) -> Template:
        active_user_account_options: dict[str, str] = {}
        if isinstance(web_context, ProfileWebContext):
            active_user_account_options = (
                ProfileWebContext.get_active_user_account_options(
                    web_context.get_admin_event().sorted_active_user_accounts
                )
            )
        return HTMXTemplate(
            template_name='common/profile/profile_modal.html',
            context=web_context.template_context
            | {
                'data': data or {},
                'errors': errors or {},
                'active_user_account_options': active_user_account_options,
            },
            re_target='#modal-wrapper',
        )

    @get(
        path=[
            '/profile-modal/{event_uniq_id:str}',
            '/profile-modal',
        ],
        name='profile-modal',
    )
    async def htmx_profile_modal(
        self,
        request: HTMXRequest,
        locale: FromQuery[str | None] = None,
    ) -> Template:
        web_context = ProfileWebContext(request)
        self.set_locale(request, locale)
        return self._render_profile_modal(web_context)

    @post(
        path='/profile-login/{event_uniq_id:str}',
        name='profile-login',
    )
    async def htmx_profile_login(
        self,
        request: HTMXRequest,
        event_uniq_id: FromPath[str],
        data: Annotated[
            dict[str, str],
            Body(media_type=RequestEncodingType.URL_ENCODED),
        ],
    ) -> Template | ClientRedirect:
        web_context = ProfileWebContext(request)

        errors: dict[str, str] = {}
        if data is None:
            data = {}
        field: str
        admin_event: Event = web_context.get_admin_event()
        accounts: list[Account] = admin_event.sorted_active_user_accounts
        account_id: int | None = WebContext.form_data_to_int(data, field := 'account_id')
        if not account_id and len(accounts) == 1:
            account_id = accounts[0].id
        throttle_keys = login_throttle_keys(
            event_uniq_id, web_context.client.source_host, account_id
        )
        locked_for = LoginThrottle.locked_for(throttle_keys)
        if locked_for is not None:
            errors[field := 'password'] = _(
                'Too many failed attempts, please try again in {minutes} minutes.'
            ).format(minutes=max(1, round(locked_for.total_seconds() / 60)))
        elif not account_id:
            errors[field] = _('Please select the account.')
        else:
            password: str = WebContext.form_data_to_str(data, field := 'password') or ''
            try:
                account: Account = admin_event.active_user_accounts_by_id[account_id]
                pw_hash = account.password_hash
                if pw_hash is None or pw_hash == '':
                    errors[field] = _(
                        'Please ask your administrator to set a password.'
                    )
                else:
                    ph = PasswordHasher()
                    try:
                        pw_hash = account.password_hash
                        # NOTE(pascalaubry): pw_hash is None for the anonymous account
                        assert pw_hash is not None
                        # NOTE(Amaras): because of a peculiar design decision from
                        # the author of argon2-cffi, the only return value is True,
                        # all other outcomes result in an exception, and it is dangerous
                        # to change that design decision now.
                        # Therefore, if the verification does not error, then it has
                        # succeeded.
                        ph.verify(pw_hash, password)
                        # NOTE(Amaras): hashing parameters might change, either through
                        # our own choice, or when the default parameters are improved.
                        # It is thus necessary to check if a re-hashing is needed as soon
                        # as possible, and rehash the password (which we verified is correct)
                        # if parameters changed.
                        if ph.check_needs_rehash(pw_hash):
                            account.update_password(ph.hash(password))
                            # FIXME(Amaras): because there is no reference to a
                            # database inside both Account and StoredAccount,
                            # this is pretty much the only place to update it.
                            # This lack of abstraction is alright for a POC, but
                            # bad practice otherwise.
                            with EventDatabase(event_uniq_id) as event_database:
                                account.stored_account = (
                                    event_database.update_stored_account(
                                        account.stored_account
                                    )
                                )
                    except (VerifyMismatchError, VerificationError):
                        LoginThrottle.record_failure(throttle_keys)
                        errors[field] = _('Invalid password.')
                        data[field] = ''
                    except InvalidHash:
                        errors[field] = _(
                            'Something went wrong. Please ask your administrator to recreate your account.'
                        )
                    else:
                        LoginThrottle.record_success(throttle_keys)
                        SessionUserAccountId(request, admin_event).set(account.id)
                        SessionUserAccountPasswordHash(request, admin_event).set(
                            account.password_hash
                        )
                        Message.success(
                            request,
                            _('Successfully logged in as [{account}].').format(
                                account=account.full_name
                            ),
                        )
                        return ClientRedirect(admin_event_url(request, event_uniq_id))
            except KeyError:
                LoginThrottle.record_failure(throttle_keys)
                errors['account_id'] = _('Invalid account.')

        return self._render_profile_modal(
            web_context,
            data=data,
            errors=errors,
        )

    @post(
        path='/profile-logout/{event_uniq_id:str}',
        name='profile-logout',
    )
    async def htmx_profile_logout(self, request: HTMXRequest) -> ClientRedirect:
        web_context = ProfileWebContext(request)
        event = web_context.get_admin_event()
        SessionUserAccountId(request, event).unset()
        SessionUserAccountPasswordHash(request, event).unset()
        Message.success(request, _('Successfully logged out.'))
        return ClientRedirect(admin_event_url(request, event.uniq_id))
