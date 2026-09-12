"""The account remote access is opened under.

Signing in happens once per machine, so what matters is that the tokens
survive, that a lapsing one is replaced before it is used, and that an account
signed out elsewhere does not leave the installation retrying for ever.
"""

from datetime import datetime, timedelta

import pytest

from common.exception import SharlyChessException
from web import remote_access_account
from web.remote_access_account import (
    ControlPlaneUnreachableError,
    RemoteAccessTokens,
    access_token,
    authorisation_url,
    complete_sign_in,
    is_signed_in,
    sign_out,
    store_tokens,
    stored_tokens,
)


def tokens(
    access: str = 'access-1', expires_in_minutes: int = 60
) -> RemoteAccessTokens:
    return RemoteAccessTokens(
        access_token=access,
        refresh_token='refresh-1',
        expires_at=datetime.now() + timedelta(minutes=expires_in_minutes),
    )


@pytest.fixture(autouse=True)
def signed_out():
    sign_out()
    yield
    sign_out()


def test_nobody_is_signed_in_to_begin_with():
    assert stored_tokens() is None
    assert not is_signed_in()
    assert access_token() is None


def test_the_account_survives_being_stored():
    store_tokens(tokens())

    kept = stored_tokens()

    assert kept is not None
    assert kept.access_token == 'access-1'
    assert kept.refresh_token == 'refresh-1'
    assert is_signed_in()


def test_a_token_with_time_left_is_used_as_it_stands(monkeypatch):
    store_tokens(tokens())
    monkeypatch.setattr(
        remote_access_account,
        '_post_token_request',
        lambda _: pytest.fail('should not have been refreshed'),
    )

    assert access_token() == 'access-1'


def test_a_token_about_to_lapse_is_replaced_before_it_is_handed_out(monkeypatch):
    store_tokens(tokens(expires_in_minutes=1))
    monkeypatch.setattr(
        remote_access_account,
        '_post_token_request',
        lambda _: RemoteAccessTokens(
            access_token='access-2',
            refresh_token='refresh-2',
            expires_at=datetime.now() + timedelta(hours=1),
        ),
    )

    assert access_token() == 'access-2'


def test_the_replacement_refresh_token_is_kept(monkeypatch):
    """A used refresh token is spent, so losing its replacement signs the machine out."""
    store_tokens(tokens(expires_in_minutes=1))
    monkeypatch.setattr(
        remote_access_account,
        '_post_token_request',
        lambda _: RemoteAccessTokens(
            access_token='access-2',
            refresh_token='refresh-2',
            expires_at=datetime.now() + timedelta(hours=1),
        ),
    )

    access_token()

    kept = stored_tokens()
    assert kept is not None
    assert kept.refresh_token == 'refresh-2'


def test_an_account_signed_out_elsewhere_is_signed_out_here(monkeypatch):
    store_tokens(tokens(expires_in_minutes=1))

    def refused(_):
        raise SharlyChessException('refused')

    monkeypatch.setattr(remote_access_account, '_post_token_request', refused)

    assert access_token() is None
    assert not is_signed_in()


def test_a_control_plane_out_of_reach_does_not_sign_the_arbiter_out(monkeypatch):
    """The renewal falls in a short window before expiry, and a venue network
    drops without warning. Spending the refresh token on an attempt that never
    left the machine would end remote access for the day."""
    store_tokens(tokens(expires_in_minutes=1))

    def unreachable(_):
        raise ControlPlaneUnreachableError('no route to host')

    monkeypatch.setattr(remote_access_account, '_post_token_request', unreachable)

    assert access_token() == 'access-1'
    assert is_signed_in()

    kept = stored_tokens()
    assert kept is not None
    assert kept.refresh_token == 'refresh-1'


def test_a_lapsed_token_that_could_not_be_renewed_is_not_read_as_signed_out(
    monkeypatch,
):
    """Answering None here would be read as nobody being signed in, and acting
    on that takes the screens off the internet over a network about to return."""
    store_tokens(tokens(expires_in_minutes=-1))

    def unreachable(_):
        raise ControlPlaneUnreachableError('no route to host')

    monkeypatch.setattr(remote_access_account, '_post_token_request', unreachable)

    with pytest.raises(ControlPlaneUnreachableError):
        access_token()

    # Still signed in: the renewal can be tried again once there is a network.
    assert is_signed_in()


def test_signing_in_remembers_the_account(monkeypatch):
    monkeypatch.setattr(
        remote_access_account, '_post_token_request', lambda _: tokens('access-new')
    )

    complete_sign_in('code', 'verifier', 'http://localhost:9000/callback')

    kept = stored_tokens()
    assert kept is not None
    assert kept.access_token == 'access-new'


def test_the_sign_in_address_asks_only_for_what_is_needed():
    url = authorisation_url(
        redirect_uri='http://192.168.1.10:9000/remote-access/callback',
        state='state-1',
        code_challenge='challenge-1',
    )

    assert '/api/oauth/authorize' in url
    assert 'scope=remote-access%3Awrite' in url
    assert 'code_challenge_method=S256' in url
    assert 'client_id=sharlychess' in url


def test_whatever_is_showing_the_account_is_told_when_it_changes(monkeypatch):
    """Signing in finishes in a browser, so nothing watching asked for this."""
    told: list[str] = []
    monkeypatch.setattr(remote_access_account, '_listeners', [])
    remote_access_account.on_account_change(lambda: told.append('changed'))

    store_tokens(tokens())
    sign_out()

    assert told == ['changed', 'changed']


def test_a_listener_that_fails_does_not_stop_the_account_changing(monkeypatch):
    def unhappy():
        raise RuntimeError('no')

    monkeypatch.setattr(remote_access_account, '_listeners', [])
    remote_access_account.on_account_change(unhappy)

    store_tokens(tokens())

    assert stored_tokens() is not None
