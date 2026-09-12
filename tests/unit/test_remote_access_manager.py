"""Whether this server is reachable over the internet.

One decision for the installation rather than one per event, because the tunnel
reaches the server and the server serves everything on it. What matters is that
the decision outlives a restart, and that nothing here can stop the server
starting.
"""

import socket

import pytest

from common.exception import SharlyChessException
from web import remote_access_manager
from web.remote_access_manager import (
    current_session,
    use_new_url,
    stopped_because,
    is_wanted,
    resume_session,
    server_identity,
    start_serving,
    stop_serving,
    url,
)


class FakeSession:
    def __init__(self, serving: bool = True):
        self.remote_uniq_id = 'server-1'
        self.is_serving = serving
        self.stopped = False
        self.stopped_because: str | None = None
        self.on_stopped = lambda: None
        self.url = 'https://k7f3x9-q4m7x2.live.example.com'
        self.grant = type('Grant', (), {'hostname': 'k7f3x9-q4m7x2.live.example.com'})()

    def stop(self) -> None:
        self.stopped = True
        self.is_serving = False


@pytest.fixture(autouse=True)
def not_serving():
    stop_serving()
    yield
    stop_serving()


@pytest.fixture
def ready(monkeypatch):
    """A signed-in machine with the feature switched on."""
    monkeypatch.setattr(
        remote_access_manager, 'experimental_features_enabled', lambda: True
    )
    monkeypatch.setattr(remote_access_manager, 'is_signed_in', lambda: True)


def opening(monkeypatch, opened: list, result=None):
    def open_session(remote_uniq_id, name, take_over=False):
        opened.append((remote_uniq_id, name, take_over))
        if isinstance(result, Exception):
            raise result
        return result or FakeSession()

    monkeypatch.setattr(remote_access_manager, 'open_session', open_session)


def test_the_identity_is_made_once_and_kept():
    first = server_identity()

    assert first
    assert server_identity() == first


def test_nothing_about_the_events_is_sent(monkeypatch, ready):
    """The events go down the tunnel, not to the control plane.

    All that is sent is what to call the machine, so that its owner can tell
    one installation from another in their own account.
    """
    opened: list = []
    opening(monkeypatch, opened)

    start_serving()

    _, name, _ = opened[0]
    assert name == socket.gethostname()


def test_serving_is_remembered_so_that_a_restart_puts_it_back(monkeypatch, ready):
    opening(monkeypatch, [])

    start_serving()

    assert is_wanted()
    assert url() == 'https://k7f3x9-q4m7x2.live.example.com'


def test_asking_twice_does_not_open_a_second_tunnel(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)

    start_serving()
    start_serving()

    assert len(opened) == 1


def test_stopping_is_remembered_too(monkeypatch, ready):
    opening(monkeypatch, [])
    start_serving()
    session = current_session()

    stop_serving()

    assert isinstance(session, FakeSession)
    assert session.stopped
    assert not is_wanted()
    assert url() is None


def test_a_server_that_was_reachable_is_put_back(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)
    remote_access_manager._remember_wanted(True)

    assert resume_session() is True
    assert len(opened) == 1


def test_a_server_that_was_not_is_left_alone(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)
    remote_access_manager._remember_wanted(False)

    assert resume_session() is False
    assert opened == []


def test_nothing_is_resumed_while_nobody_is_signed_in(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)
    remote_access_manager._remember_wanted(True)
    monkeypatch.setattr(remote_access_manager, 'is_signed_in', lambda: False)

    assert resume_session() is False
    assert opened == []


def test_nothing_is_resumed_while_the_feature_is_off(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)
    remote_access_manager._remember_wanted(True)
    monkeypatch.setattr(
        remote_access_manager, 'experimental_features_enabled', lambda: False
    )

    assert resume_session() is False
    assert opened == []


def test_a_server_that_will_not_come_back_does_not_stop_the_rest(monkeypatch, ready):
    """Everything here can fail without the venue's own network noticing."""
    opening(monkeypatch, [], result=SharlyChessException('no'))
    remote_access_manager._remember_wanted(True)

    assert resume_session() is False


def test_whatever_is_showing_this_is_told_when_it_changes(monkeypatch, ready):
    """The server puts itself back on the internet as it starts, unasked."""
    told: list[str] = []
    opening(monkeypatch, [])
    monkeypatch.setattr(remote_access_manager, '_listeners', [])
    remote_access_manager.on_remote_access_change(lambda: told.append('changed'))

    start_serving()
    stop_serving()

    assert told == ['changed', 'changed']


def test_a_listener_that_fails_does_not_stop_the_server_being_served(
    monkeypatch, ready
):
    def unhappy():
        raise RuntimeError('no')

    opening(monkeypatch, [])
    monkeypatch.setattr(remote_access_manager, '_listeners', [])
    remote_access_manager.on_remote_access_change(unhappy)

    start_serving()

    assert url() is not None


def test_a_session_that_lost_its_lease_is_not_still_offered(monkeypatch, ready):
    """It stopped itself, so the window must not go on saying the server is on
    the internet, nor answer a fresh request to turn it on with the dead one."""
    session = FakeSession()
    opening(monkeypatch, [], result=session)
    start_serving()

    session.is_serving = False

    assert current_session() is None
    assert url() is None


def test_turning_it_on_again_after_a_lost_lease_opens_a_new_session(
    monkeypatch, ready
):
    first = FakeSession()
    opening(monkeypatch, [], result=first)
    start_serving()
    first.is_serving = False

    second = FakeSession()
    opened: list = []
    opening(monkeypatch, opened, result=second)

    assert start_serving() is second
    assert len(opened) == 1


def test_taking_over_is_passed_on_to_the_control_plane(monkeypatch, ready):
    opened: list = []
    opening(monkeypatch, opened)

    start_serving(take_over=True)

    assert opened[0][2] is True


def test_why_a_session_ended_outlives_it(monkeypatch, ready):
    """The arbiter is doing something else when a refusal arrives, and reads
    about it in the window minutes later — by which time the session has gone."""
    session = FakeSession()
    opening(monkeypatch, [], result=session)
    start_serving()

    session.stopped_because = 'This address has been taken out of service.'
    session.on_stopped()

    assert stopped_because() == 'This address has been taken out of service.'


def test_turning_it_on_again_clears_what_went_wrong_last_time(monkeypatch, ready):
    session = FakeSession()
    opening(monkeypatch, [], result=session)
    start_serving()
    session.stopped_because = 'something went wrong'
    session.on_stopped()
    session.is_serving = False

    opening(monkeypatch, [], result=FakeSession())
    start_serving()

    assert stopped_because() is None



def test_taking_a_new_address_forgets_the_old_identity(monkeypatch, ready):
    """The identifier is what decides which address this computer asks for, so
    forgetting it is what actually takes effect."""
    retired: list[str] = []
    monkeypatch.setattr(
        remote_access_manager, 'retire_remote_access', retired.append
    )
    opening(monkeypatch, [])
    start_serving()
    old = server_identity()

    use_new_url()

    assert retired == [old]
    assert server_identity() != old
    assert not is_wanted()


def test_a_site_that_cannot_be_told_does_not_stop_the_change(monkeypatch, ready):
    """The address left behind is reserved for ever either way, and an arbiter
    between tournaments should not be held up by the network."""
    def refuse(_):
        raise SharlyChessException('could not be reached')

    monkeypatch.setattr(remote_access_manager, 'retire_remote_access', refuse)
    opening(monkeypatch, [])
    start_serving()
    old = server_identity()

    use_new_url()

    assert server_identity() != old


def test_taking_a_new_address_stops_serving_the_old_one(monkeypatch, ready):
    monkeypatch.setattr(remote_access_manager, 'retire_remote_access', lambda _: None)
    session = FakeSession()
    opening(monkeypatch, [], result=session)
    start_serving()

    use_new_url()

    assert session.stopped
    assert url() is None
