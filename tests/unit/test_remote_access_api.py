"""Talking to the control plane.

The answers that need acting on rather than reporting are the point here: an
event held by another laptop can be taken over, a machine that has been
disowned must register again, and neither should reach the caller as an
indistinguishable failure.
"""

from typing import Any

import pytest
import requests

from common.exception import SharlyChessException
from web import remote_access_api
from web.remote_access_api import (
    EventHeldElsewhereError,
    InstallNotRecognisedError,
    NotSignedInError,
    RemoteAccessGrant,
    RemoteAccessRefusedError,
    RemoteAccessUnavailableError,
    ServerNotOursError,
    AddressBlockedError,
    AddressLimitReachedError,
    close_remote_access,
    open_remote_access,
    register_install,
    send_heartbeat,
)

REMOTE_UNIQ_ID = '0a3b0c3a-0000-4000-8000-000000000001'
INSTALL_ID = 'install_1'

GRANT = {
    'hostname': 'k7f3x9-q4m7x2.live.example.com',
    'url': 'https://k7f3x9-q4m7x2.live.example.com',
    'relayHost': 'relay.example.com',
    'relayPort': 2222,
    'relayHostKey': 'ssh-ed25519 RELAYKEY',
    'relayUsername': 'q4m7x2',
    'subdomain': 'k7f3x9',
    'instanceNonce': 'nonce-1',
}

NAME = 'timothys-mac-studio-1.home'


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str = ''):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload or '')

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    """Records what was sent, and answers with whatever the test queued."""
    recorded: list[dict[str, Any]] = []
    queued: list[FakeResponse] = []

    def post(url, headers=None, json=None, timeout=None, **_):
        recorded.append({'url': url, 'headers': headers or {}, 'body': json or {}})
        return queued.pop(0) if queued else FakeResponse(200, {'data': {}})

    monkeypatch.setattr(remote_access_api.requests, 'post', post)
    monkeypatch.setattr(remote_access_api, 'access_token', lambda: 'token-1')
    return recorded, queued


def test_registering_returns_what_the_machine_is_called(calls):
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': {'install_id': INSTALL_ID}}))

    assert register_install('ssh-ed25519 AAAA', 'Laptop') == INSTALL_ID
    assert recorded[0]['body'] == {'public_key': 'ssh-ed25519 AAAA', 'label': 'Laptop'}


def test_opening_returns_where_to_connect(calls):
    _, queued = calls
    queued.append(FakeResponse(200, {'data': GRANT}))

    grant = open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)

    assert grant == RemoteAccessGrant(
        hostname='k7f3x9-q4m7x2.live.example.com',
        url='https://k7f3x9-q4m7x2.live.example.com',
        relay_host='relay.example.com',
        relay_port=2222,
        relay_host_key='ssh-ed25519 RELAYKEY',
        relay_username='q4m7x2',
        subdomain='k7f3x9',
        instance_nonce='nonce-1',
    )


def test_the_account_is_presented_with_every_request(calls):
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': GRANT}))

    open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)

    assert recorded[0]['headers']['Authorization'] == 'Bearer token-1'


def test_nothing_about_the_events_being_served_is_sent(calls):
    """A tunnel reaches a server, so the only thing said about it is what to
    call the machine. Titles, players, pairings and results go down the tunnel
    to whoever opened the page and never through here."""
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': GRANT}))

    open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)

    assert recorded[0]['body'] == {
        'name': NAME,
        'remote_uniq_id': REMOTE_UNIQ_ID,
        'install_id': INSTALL_ID,
        'take_over': False,
    }


def test_an_event_held_elsewhere_can_be_told_apart(calls):
    _, queued = calls
    queued.append(FakeResponse(409, {'error': 'conflict'}))

    with pytest.raises(EventHeldElsewhereError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_taking_over_is_asked_for_plainly(calls):
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': GRANT}))

    open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME, take_over=True)

    assert recorded[0]['body']['take_over'] is True


def test_a_disowned_machine_can_be_told_apart(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'unknown_install'}))

    with pytest.raises(InstallNotRecognisedError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_refusal_for_some_other_reason_is_not_read_as_a_disowned_machine(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'insufficient_scope'}))

    with pytest.raises(SharlyChessException):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_control_plane_offering_no_remote_access_can_be_told_apart(calls):
    _, queued = calls
    queued.append(FakeResponse(503, {'error': 'unavailable'}))

    with pytest.raises(RemoteAccessUnavailableError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_refused_account_is_reported_as_not_signed_in(calls):
    _, queued = calls
    queued.append(FakeResponse(401, {'error': 'invalid_token'}))

    with pytest.raises(NotSignedInError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_nothing_is_sent_while_nobody_is_signed_in(monkeypatch):
    monkeypatch.setattr(remote_access_api, 'access_token', lambda: None)
    monkeypatch.setattr(
        remote_access_api.requests,
        'post',
        lambda *a, **k: pytest.fail('should not have asked'),
    )

    with pytest.raises(NotSignedInError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_control_plane_that_cannot_be_reached_says_so(calls, monkeypatch):
    def refuse(*_a, **_k):
        raise requests.ConnectionError('no route to host')

    monkeypatch.setattr(remote_access_api.requests, 'post', refuse)

    with pytest.raises(SharlyChessException, match='could not be reached'):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_the_heartbeat_returns_the_nonce_to_answer_with(calls):
    _, queued = calls
    queued.append(FakeResponse(200, {'data': {'instance_nonce': 'nonce-2'}}))

    assert send_heartbeat(REMOTE_UNIQ_ID, INSTALL_ID) == 'nonce-2'


def test_the_heartbeat_leaves_the_name_out_unless_it_has_changed(calls):
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': {'instance_nonce': 'nonce-2'}}))

    send_heartbeat(REMOTE_UNIQ_ID, INSTALL_ID)

    assert 'name' not in recorded[0]['body']


def test_an_address_issued_to_another_account_can_be_told_apart(calls):
    """Retrying will never work, so it is not reported as a held lease."""
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'not_owned'}))

    with pytest.raises(ServerNotOursError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_closing_names_only_the_event(calls):
    recorded, queued = calls
    queued.append(FakeResponse(200, {'data': {'closed': True}}))

    close_remote_access(REMOTE_UNIQ_ID)

    assert recorded[0]['body'] == {'remote_uniq_id': REMOTE_UNIQ_ID}


def test_an_address_taken_out_of_service_can_be_told_apart(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'blocked'}))

    with pytest.raises(AddressBlockedError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_an_account_holding_all_the_addresses_it_may_can_be_told_apart(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'limit_reached'}))

    with pytest.raises(AddressLimitReachedError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_refusal_this_version_cannot_name_carries_what_it_was_told(calls):
    """Enough for the arbiter to act on, without this version having to know
    every reason the site may one day refuse."""
    _, queued = calls
    queued.append(
        FakeResponse(
            403,
            {
                'error': 'something_new',
                'error_description': 'The address is in quarantine.',
            },
        )
    )

    with pytest.raises(RemoteAccessRefusedError, match='quarantine'):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_refusal_with_nothing_said_still_names_its_code(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'something_new'}))

    with pytest.raises(RemoteAccessRefusedError, match='something_new'):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_conflict_is_read_from_the_code_rather_than_from_the_status(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'conflict'}))

    with pytest.raises(EventHeldElsewhereError):
        open_remote_access(REMOTE_UNIQ_ID, INSTALL_ID, NAME)


def test_a_disowned_machine_is_told_it_cannot_register_itself_again(calls):
    _, queued = calls
    queued.append(FakeResponse(403, {'error': 'unknown_install'}))

    with pytest.raises(InstallNotRecognisedError, match='cannot register itself again'):
        register_install('ssh-ed25519 AAAA')
