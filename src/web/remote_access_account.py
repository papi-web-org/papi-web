"""The account remote access is opened under.

Signing in belongs to the computer rather than to an event.  An arbiter signs in
once on the laptop they are working from, and every event served from it is
opened under that account, so that the control plane knows whose events these
are and who may take them back.

The exchange is the authorization code flow with PKCE, the same one the site
offers first-party applications: no secret has to be kept on a computer that
anyone can open.
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger
from typing import Callable

import requests

from common.exception import SharlyChessException
from common.logger import get_logger
from database.sqlite.config.config_database import ConfigDatabase
from web.urls import build_get_url

logger: Logger = get_logger()

#: Where the control plane lives.  Overridable so that a development build can
#: be pointed at a local one.
CONTROL_PLANE_URL: str = (
    os.getenv('REMOTE_ACCESS_CONTROL_PLANE_URL') or 'https://events.sharly-chess.com'
)

#: The application is a public client: it holds no secret, and proves itself
#: with PKCE instead.
CLIENT_ID: str = 'sharlychess'

#: Opening an event to the internet is all this account is asked to do.
SCOPES: tuple[str, ...] = ('remote-access:write',)

REQUEST_TIMEOUT: int = 20


class ControlPlaneUnreachableError(SharlyChessException):
    """The control plane could not be asked, which is not the same as a refusal."""

#: Refreshed this far ahead of expiry, so that a token does not lapse between
#: being read and being used.
REFRESH_MARGIN = timedelta(minutes=2)


@dataclass(frozen=True)
class RemoteAccessTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime

    @property
    def is_fresh(self) -> bool:
        return datetime.now() + REFRESH_MARGIN < self.expires_at


def authorisation_url(redirect_uri: str, state: str, code_challenge: str) -> str:
    """Where to send the arbiter's browser to sign in."""
    return build_get_url(
        CONTROL_PLANE_URL,
        '/api/oauth/authorize',
        {
            'client_id': CLIENT_ID,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(SCOPES),
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'response_type': 'code',
        },
    )


def _tokens_from_response(data: dict) -> RemoteAccessTokens:
    return RemoteAccessTokens(
        access_token=data['access_token'],
        refresh_token=data['refresh_token'],
        expires_at=datetime.now() + timedelta(seconds=data['expires_in']),
    )


def _post_token_request(data: dict[str, str]) -> RemoteAccessTokens:
    try:
        response = requests.post(
            CONTROL_PLANE_URL + '/api/oauth/token',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data={**data, 'client_id': CLIENT_ID},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise ControlPlaneUnreachableError(
            f'The control plane could not be reached: {e}'
        )
    if response.status_code >= 500:
        # The site is having a bad minute, not disowning the account.
        raise ControlPlaneUnreachableError(
            f'The control plane answered {response.status_code}.'
        )
    if not response.ok:
        logger.debug(
            'Token request refused: %s %s', response.status_code, response.text
        )
        raise SharlyChessException('The account could not be signed in.')
    return _tokens_from_response(response.json())


#: Told when the account changes, so that whatever is showing it can say so.
#: Signing in finishes in a browser and signing out can happen on its own when
#: a sign-in lapses, so nothing watching can rely on having asked for it.
_listeners: list[Callable[[], None]] = []


def on_account_change(listener: Callable[[], None]) -> None:
    _listeners.append(listener)


def _announce_change() -> None:
    for listener in list(_listeners):
        try:
            listener()
        except Exception as e:
            # Nothing that merely wanted to know may stop the account changing.
            logger.warning('A listener could not be told of the account: %s', e)


def store_tokens(tokens: RemoteAccessTokens | None) -> None:
    with ConfigDatabase(write=True) as database:
        database.update_remote_access_tokens(
            tokens.access_token if tokens else None,
            tokens.refresh_token if tokens else None,
            tokens.expires_at.timestamp() if tokens else None,
        )
    _announce_change()


def stored_tokens() -> RemoteAccessTokens | None:
    with ConfigDatabase() as database:
        stored_config = database.load_stored_config()
    if (
        not stored_config.remote_access_token
        or not stored_config.remote_access_refresh_token
        or stored_config.remote_access_token_expires_at is None
    ):
        return None
    return RemoteAccessTokens(
        access_token=stored_config.remote_access_token,
        refresh_token=stored_config.remote_access_refresh_token,
        expires_at=datetime.fromtimestamp(stored_config.remote_access_token_expires_at),
    )


def complete_sign_in(
    code: str, code_verifier: str, redirect_uri: str
) -> RemoteAccessTokens:
    """Exchange the code the browser came back with, and remember the account."""
    tokens = _post_token_request(
        {
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': code_verifier,
            'redirect_uri': redirect_uri,
        }
    )
    store_tokens(tokens)
    return tokens


def sign_out() -> None:
    store_tokens(None)


def access_token() -> str | None:
    """A token good to use now, refreshed if it is about to lapse.

    Refresh tokens are rotated and a used one is spent, so the replacement is
    stored before it is returned.  A *refusal* means the account has been signed
    out elsewhere, and is treated as signing out here: the alternative is an
    computer that retries a token nobody will honour again.

    Being unable to ask is not a refusal.  The refresh falls in a short window
    before expiry, and a venue network drops without warning; discarding the
    refresh token because it could not be spent at that moment would end remote
    access for the day and send the arbiter back to a browser.  The token in
    hand is returned while it is still good, and the next attempt tries again.
    """
    tokens = stored_tokens()
    if tokens is None:
        return None
    if tokens.is_fresh:
        return tokens.access_token

    try:
        refreshed = _post_token_request(
            {'grant_type': 'refresh_token', 'refresh_token': tokens.refresh_token}
        )
    except ControlPlaneUnreachableError as e:
        logger.info('The sign-in could not be renewed, keeping it: %s', e)
        if datetime.now() < tokens.expires_at:
            return tokens.access_token
        # Still signed in, just not usable this minute.  Said by raising rather
        # than by answering None, which the caller is entitled to read as
        # nobody being signed in — and acting on that would take the screens
        # off the internet over a network that is about to come back.
        raise
    except SharlyChessException:
        logger.info('Remote access sign-in has lapsed and must be renewed.')
        sign_out()
        return None

    store_tokens(refreshed)
    return refreshed.access_token


def is_signed_in() -> bool:
    return stored_tokens() is not None
