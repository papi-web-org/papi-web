"""Serving this server to the internet.

The session has to keep three things in step: the grant, the tunnel, and what
the hostname answers when the control plane asks who is behind it. What is
checked here is that they never disagree — including when the lease is taken
away while the server is being served.
"""

import threading
from dataclasses import replace

import pytest

from common.exception import SharlyChessException
from common.sharly_chess_config import SharlyChessConfig
from web import remote_access_session
from web.remote_access import remote_identity
from web.remote_access_account import ControlPlaneUnreachableError
from web.remote_access_api import (
    EventHeldElsewhereError,
    NotSignedInError,
    RemoteAccessGrant,
    RemoteAccessRefusedError,
    RemoteAccessUnavailableError,
)
from web.remote_access_session import RemoteAccessSession, open_session, relay_host_key
from web.tunnel_client import RemoteTunnel, TunnelStatus

REMOTE_UNIQ_ID = '0a3b0c3a-0000-4000-8000-000000000001'
INSTALL_ID = 'install_1'
HOSTNAME = 'k7f3x9-q4m7x2.live.example.com'
RELAY_KEY = (
    'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDHWth4G7tjHlSDTebbBHKdFqW5UqFdxJTDd9Ger1Qxb'
)

NAME = 'timothys-mac-studio-1.home'

GRANT = RemoteAccessGrant(
    hostname=HOSTNAME,
    url=f'https://{HOSTNAME}',
    relay_host='relay.example.com',
    relay_port=2222,
    relay_host_key=RELAY_KEY,
    relay_username='q4m7x2',
    subdomain='k7f3x9',
    instance_nonce='nonce-1',
)


class FakeTunnel(RemoteTunnel):
    """Stands in for the tunnel: records what it was asked to carry."""

    def __init__(self, starts: bool = True, **kwargs):
        self.kwargs = kwargs
        self.starts = starts
        self.stopped = False
        self._status = TunnelStatus.STOPPED

    def start(self) -> bool:
        self._status = TunnelStatus.RUNNING if self.starts else TunnelStatus.FAILED
        return self.starts

    def stop(self) -> None:
        self.stopped = True
        self._status = TunnelStatus.STOPPED

    @property
    def status(self) -> TunnelStatus:
        return self._status


@pytest.fixture
def control_plane(monkeypatch):
    """The control plane, answering as told and recording what it was asked."""
    calls: dict[str, list] = {'open': [], 'heartbeat': [], 'close': []}

    def opened(*args, **kwargs):
        calls['open'].append((args, kwargs))
        return GRANT

    def renewed(*args):
        calls['heartbeat'].append(args)
        return 'nonce-2'

    def closed(*args):
        calls['close'].append(args)

    monkeypatch.setattr(SharlyChessConfig(), 'web_tunnel_port', 18080, raising=False)
    monkeypatch.setattr(remote_access_session, 'install_id', lambda: INSTALL_ID)
    monkeypatch.setattr(remote_access_session, 'open_remote_access', opened)
    monkeypatch.setattr(remote_access_session, 'send_heartbeat', renewed)
    monkeypatch.setattr(remote_access_session, 'close_remote_access', closed)
    return calls


@pytest.fixture(autouse=True)
def forget_hostname():
    yield
    from web.remote_access import clear_remote_identity

    clear_remote_identity(HOSTNAME)


def test_the_relay_key_is_read_so_that_it_can_be_checked():
    key = relay_host_key(RELAY_KEY)

    assert key is not None
    assert key.get_name() == 'ssh-ed25519'


def test_a_key_that_cannot_be_read_is_not_silently_accepted_as_valid():
    assert relay_host_key('not a key') is None


def test_the_hostname_answers_before_the_tunnel_carries_anything(control_plane):
    """The control plane checks the hostname, so the answer has to be ready first."""
    ready: list[bool] = []

    def tunnel_factory(**kwargs):
        ready.append(remote_identity(HOSTNAME) is not None)
        return FakeTunnel(**kwargs)

    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=tunnel_factory)
    session.stop()

    assert ready == [True]


def test_the_tunnel_is_told_where_the_relay_is(control_plane):
    made: list[FakeTunnel] = []

    def tunnel_factory(**kwargs):
        tunnel = FakeTunnel(**kwargs)
        made.append(tunnel)
        return tunnel

    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=tunnel_factory)
    session.stop()

    assert made[0].kwargs['relay_host'] == 'relay.example.com'
    assert made[0].kwargs['relay_port'] == 2222
    assert made[0].kwargs['username'] == 'q4m7x2'
    assert made[0].kwargs['subdomain'] == 'k7f3x9'
    assert made[0].kwargs['local_port'] == 18080


def test_the_hostname_answers_with_what_the_grant_issued(control_plane):
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    identity = remote_identity(HOSTNAME)

    assert identity is not None
    assert identity.remote_uniq_id == REMOTE_UNIQ_ID
    assert identity.instance_nonce == 'nonce-1'
    session.stop()


def test_a_tunnel_that_will_not_open_leaves_nothing_behind(control_plane):
    with pytest.raises(SharlyChessException):
        open_session(
            REMOTE_UNIQ_ID,
            NAME,
            tunnel_factory=lambda **kwargs: FakeTunnel(starts=False, **kwargs),
        )

    assert remote_identity(HOSTNAME) is None
    assert control_plane['close'] == [(REMOTE_UNIQ_ID,)]


def test_stopping_takes_the_event_off_the_internet(control_plane):
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    tunnel = session.tunnel
    assert isinstance(tunnel, FakeTunnel)

    session.stop()

    assert tunnel.stopped
    assert remote_identity(HOSTNAME) is None
    assert control_plane['close'] == [(REMOTE_UNIQ_ID,)]


def test_the_nonce_is_replaced_as_the_lease_is_renewed(control_plane):
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    assert session._renew() is True

    identity = remote_identity(HOSTNAME)
    assert identity is not None
    assert identity.instance_nonce == 'nonce-2'
    session.stop()


def test_a_lease_lost_to_another_machine_ends_the_session(monkeypatch, control_plane):
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    def taken(*_a):
        raise EventHeldElsewhereError('held elsewhere')

    monkeypatch.setattr(remote_access_session, 'send_heartbeat', taken)

    assert session._renew() is False


def test_a_control_plane_out_of_reach_does_not_take_the_event_off_the_air(
    monkeypatch, control_plane
):
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    def unreachable(*_a):
        raise ControlPlaneUnreachableError('could not be reached')

    monkeypatch.setattr(remote_access_session, 'send_heartbeat', unreachable)

    assert session._renew() is True
    assert session.is_serving
    session.stop()


def test_a_relay_the_site_cannot_offer_for_a_moment_is_waited_through(
    monkeypatch, control_plane
):
    """Said to be worth trying again, and the lease outlives several tries."""
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    def no_relay(*_a):
        raise RemoteAccessUnavailableError('no relay')

    monkeypatch.setattr(remote_access_session, 'send_heartbeat', no_relay)

    assert session._renew() is True
    session.stop()


def test_a_refusal_this_version_cannot_name_is_still_final(monkeypatch, control_plane):
    """Going on asking would say nothing to the arbiter while getting nowhere,
    and would hold an address the control plane is about to give away."""
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    def refused(*_a):
        raise RemoteAccessRefusedError('the address is in a state unknown here')

    monkeypatch.setattr(remote_access_session, 'send_heartbeat', refused)

    assert session._renew() is False
    assert session.stopped_because == 'the address is in a state unknown here'


def test_a_session_that_lost_its_lease_does_not_ask_to_close_it(control_plane):
    session = RemoteAccessSession(
        remote_uniq_id=REMOTE_UNIQ_ID,
        grant=GRANT,
        tunnel=FakeTunnel(),
        name=NAME,
        install_id=INSTALL_ID,
        _stopping=threading.Event(),
    )

    session.stop(release=False)

    assert control_plane['close'] == []


def test_a_sign_in_that_has_ended_stops_the_session(monkeypatch, control_plane):
    """The heartbeat cannot be sent again under this account, so serving on
    would hold an address the control plane is about to give away — and show
    the arbiter a URL that has stopped working."""
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    def signed_out(*_a, **_k):
        raise NotSignedInError('the account was refused')

    monkeypatch.setattr(remote_access_session, 'send_heartbeat', signed_out)

    assert session._renew() is False


def test_whatever_is_showing_the_session_is_told_when_it_stops_itself(control_plane):
    told: list[bool] = []
    session = open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)
    session.on_stopped = lambda: told.append(True)

    session.stop(release=False)

    assert told == [True]


def test_a_relay_that_cannot_be_identified_is_not_connected_to(
    monkeypatch, control_plane
):
    """The screens that take a password travel down this connection, so a key
    that cannot be read is a reason to stay off the internet, not to trust
    whatever answers."""
    monkeypatch.setattr(
        remote_access_session,
        'open_remote_access',
        lambda *a, **k: replace(GRANT, relay_host_key='not a key'),
    )

    with pytest.raises(SharlyChessException, match='could not be identified'):
        open_session(REMOTE_UNIQ_ID, NAME, tunnel_factory=FakeTunnel)

    assert remote_identity(HOSTNAME) is None
    assert control_plane['close'] == [(REMOTE_UNIQ_ID,)]
