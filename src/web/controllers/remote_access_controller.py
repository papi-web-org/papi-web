"""Signing this machine in to the account remote access is opened under.

The browser is sent to the control plane to sign in and comes back here with a
code, which is exchanged for the tokens kept on this machine.  The address it
comes back to is this server's own, reached the same way the arbiter reached
it, so a laptop on a venue network needs nothing opened or forwarded.

The proof that the exchange belongs to this machine is kept in memory only: it
is worth nothing once used, and an installation that is restarted mid-sign-in
should start again rather than honour something it cannot vouch for.
"""

from datetime import datetime, timedelta
from typing import Annotated
from logging import Logger
from threading import Lock

from gettext import gettext as _

from litestar import get
from litestar.params import FromQuery, QueryParameter
from litestar.response import Redirect
from litestar_htmx import HTMXRequest

from common import experimental_features_enabled
from common.exception import SharlyChessException
from common.logger import get_logger
from data.access_levels.actions import AuthAction
from web.controllers.base_controller import BaseController
from web.guards import ActionGuard
from web.messages import Message
from web.remote_access_account import (
    authorisation_url,
    complete_sign_in,
    sign_out,
)
from web.urls import build_internal_get_url, index_url
from web.utils import PKCEUtils

logger: Logger = get_logger()

#: Long enough for someone to sign in, short enough that an abandoned attempt
#: does not sit around waiting to be used.
EXCHANGE_EXPIRATION = timedelta(minutes=10)


class _PendingExchanges:
    """The proofs of sign-ins under way, which outlive nothing."""

    def __init__(self) -> None:
        self._by_state: dict[str, tuple[str, datetime]] = {}
        self._lock = Lock()

    def start(self, state: str, code_verifier: str) -> None:
        with self._lock:
            self._discard_expired()
            self._by_state[state] = (
                code_verifier,
                datetime.now() + EXCHANGE_EXPIRATION,
            )

    def take(self, state: str) -> str | None:
        """The verifier for this exchange, which can only be taken once."""
        with self._lock:
            self._discard_expired()
            pending = self._by_state.pop(state, None)
        return pending[0] if pending else None

    def _discard_expired(self) -> None:
        now = datetime.now()
        for state, (_verifier, expires_at) in list(self._by_state.items()):
            if expires_at <= now:
                del self._by_state[state]


class RemoteAccessController(BaseController):
    _pending = _PendingExchanges()

    @staticmethod
    def _callback_url(request: HTMXRequest) -> str:
        return build_internal_get_url(request, 'remote-access-callback')

    @get(
        path='/remote-access/sign-in',
        name='remote-access-sign-in',
        guard=[ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)],
    )
    async def remote_access_sign_in(self, request: HTMXRequest) -> Redirect:
        # Reached by ordinary navigation from the application window, so the
        # answer has to be a redirect a browser will follow rather than one
        # addressed to a page that asked for it.
        if not experimental_features_enabled():
            Message.error(request, _('Remote access is not available.'))
            return Redirect(index_url(request))

        state = PKCEUtils.generate_state()
        code_verifier = PKCEUtils.generate_code_verifier()
        self._pending.start(state, code_verifier)
        logger.info('Remote access sign-in started')
        return Redirect(
            authorisation_url(
                redirect_uri=self._callback_url(request),
                state=state,
                code_challenge=PKCEUtils.generate_code_challenge(code_verifier),
            )
        )

    @get(path='/remote-access/callback', name='remote-access-callback')
    async def htmx_remote_access_callback(
        self,
        request: HTMXRequest,
        code: FromQuery[str | None] = None,
        error: FromQuery[str | None] = None,
        # Named for the parameter it carries rather than after it: `state` is
        # Litestar's own, and a handler that takes it is asking for the
        # application state instead.
        oauth_state: Annotated[str | None, QueryParameter(name='state')] = None,
    ) -> Redirect:
        # The browser arrives here by ordinary navigation from the control
        # plane, so the answer is a real redirect rather than one addressed to
        # the page that started this.
        if error:
            logger.info('Remote access sign-in refused: %s', error)
            Message.error(request, _('The sign-in was refused.'))
        elif not code or not oauth_state:
            Message.error(request, _('The sign-in did not complete.'))
        elif (code_verifier := self._pending.take(oauth_state)) is None:
            # Either this has been used already, or the server was restarted
            # while the arbiter was signing in.
            Message.error(request, _('The sign-in took too long, please try again.'))
        else:
            try:
                complete_sign_in(code, code_verifier, self._callback_url(request))
                logger.info('Remote access signed in')
                Message.success(request, _('Signed in for remote access.'))
            except SharlyChessException as e:
                logger.error('Remote access sign-in failed: %s', e)
                Message.error(
                    request,
                    _('The sign-in could not be completed, consult the logs.'),
                )
        return Redirect(index_url(request))

    @get(
        path='/remote-access/sign-out',
        name='remote-access-sign-out',
        guard=[ActionGuard(AuthAction.MANAGE_APPLICATION_SETTINGS)],
    )
    async def remote_access_sign_out(self, request: HTMXRequest) -> Redirect:
        sign_out()
        logger.info('Remote access signed out')
        Message.success(request, _('Signed out of remote access.'))
        return Redirect(index_url(request))
