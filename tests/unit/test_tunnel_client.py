"""The tunnel client, driven against a real SSH server.

The forward is the whole of what this class does, so the server is a genuine
paramiko one rather than a mock: a stub would only prove the calls were made,
not that a request arriving at the relay reaches the local port.
"""

import socket
import threading
import time
from typing import Generator

import paramiko
import pytest

from web.tunnel_client import SishTunnel, TunnelStatus

USERNAME = 'install-aaaa'
SUBDOMAIN = 'paris2026'


class RelayServer(paramiko.ServerInterface):
    """Stands in for the relay: accepts one key for one user, and records the
    forward it is asked for."""

    def __init__(self, allowed_key: paramiko.PKey, allowed_user: str):
        self.allowed_key = allowed_key
        self.allowed_user = allowed_user
        self.forward_requested: tuple[str, int] | None = None
        self.forwarded = threading.Event()

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        if username == self.allowed_user and key == self.allowed_key:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return 'publickey'

    def check_port_forward_request(self, address: str, port: int) -> int:
        self.forward_requested = (address, port)
        self.forwarded.set()
        return port


class Relay:
    def __init__(self, allowed_key: paramiko.PKey, allowed_user: str = USERNAME):
        self.host_key = paramiko.ECDSAKey.generate()
        self.server = RelayServer(allowed_key, allowed_user)
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        self.transports: list[paramiko.Transport] = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        while True:
            try:
                connection, __ = self.socket.accept()
            except OSError:
                return
            transport = paramiko.Transport(connection)
            transport.add_server_key(self.host_key)
            self.transports.append(transport)
            try:
                transport.start_server(server=self.server)
            except Exception:
                pass

    def close(self) -> None:
        for transport in self.transports:
            transport.close()
        self.socket.close()


@pytest.fixture
def install_key() -> paramiko.PKey:
    return paramiko.ECDSAKey.generate()


@pytest.fixture
def relay(install_key: paramiko.PKey) -> Generator[Relay, None, None]:
    relay = Relay(install_key)
    yield relay
    relay.close()


def build_tunnel(
    relay: Relay,
    install_key: paramiko.PKey,
    username: str = USERNAME,
    host_key: paramiko.PKey | None = None,
) -> SishTunnel:
    return SishTunnel(
        local_port=1,
        relay_host='127.0.0.1',
        relay_port=relay.port,
        username=username,
        subdomain=SUBDOMAIN,
        private_key=install_key,
        relay_host_key=host_key or relay.host_key,
        connect_timeout=5,
        reconnect_delays=(0,),
    )


def test_a_tunnel_that_was_never_started_is_stopped(
    relay: Relay, install_key: paramiko.PKey
):
    assert build_tunnel(relay, install_key).status == TunnelStatus.STOPPED


def test_starting_the_tunnel_asks_the_relay_for_the_subdomain(
    relay: Relay, install_key: paramiko.PKey
):
    tunnel = build_tunnel(relay, install_key)

    assert tunnel.start()

    assert tunnel.status == TunnelStatus.RUNNING
    assert relay.server.forwarded.wait(timeout=5)
    assert relay.server.forward_requested == (SUBDOMAIN, SishTunnel.REMOTE_PORT)
    tunnel.stop()


def test_the_subdomain_travels_as_the_bind_address(
    relay: Relay, install_key: paramiko.PKey
):
    """What makes the hostname the relay issues predictable: the subdomain is
    the SSH bind address, exactly as `ssh -R name:80:…` sends it."""
    tunnel = build_tunnel(relay, install_key)
    tunnel.start()

    assert relay.server.forwarded.wait(timeout=5)
    address, __ = relay.server.forward_requested or ('', 0)

    assert address == SUBDOMAIN
    tunnel.stop()


def test_stopping_the_tunnel_closes_it(relay: Relay, install_key: paramiko.PKey):
    tunnel = build_tunnel(relay, install_key)
    tunnel.start()

    tunnel.stop()

    assert tunnel.status == TunnelStatus.STOPPED


def test_starting_a_running_tunnel_leaves_it_alone(
    relay: Relay, install_key: paramiko.PKey
):
    tunnel = build_tunnel(relay, install_key)
    tunnel.start()
    holder = tunnel._holder

    assert tunnel.start()

    assert tunnel._holder is holder
    tunnel.stop()


def test_a_key_the_relay_does_not_accept_leaves_the_tunnel_failed(
    relay: Relay, install_key: paramiko.PKey
):
    """The relay names a hostname after the user connecting, so refusing a key
    that is not the one registered for that user is what stops an install
    answering for another's hostname."""
    tunnel = build_tunnel(relay, paramiko.ECDSAKey.generate())

    assert not tunnel.start()

    assert tunnel.status == TunnelStatus.FAILED
    tunnel.stop()


def test_connecting_as_another_user_leaves_the_tunnel_failed(
    relay: Relay, install_key: paramiko.PKey
):
    tunnel = build_tunnel(relay, install_key, username='install-bbbb')

    assert not tunnel.start()

    assert tunnel.status == TunnelStatus.FAILED
    tunnel.stop()


def test_a_relay_presenting_another_host_key_is_refused(
    relay: Relay, install_key: paramiko.PKey
):
    """The admin screens travel over this connection, so a relay that cannot
    prove it is the one the control plane named is not talked to."""
    tunnel = build_tunnel(relay, install_key, host_key=paramiko.ECDSAKey.generate())

    assert not tunnel.start()

    assert tunnel.status == TunnelStatus.FAILED
    tunnel.stop()


def test_a_tunnel_that_drops_reads_as_coming_back_rather_than_as_stopped(
    relay: Relay, install_key: paramiko.PKey
):
    """A venue network drops for a minute at a time. Reported as stopped, the
    window would tell the arbiter their screens had gone off the internet while
    the tunnel was already reopening."""
    tunnel = build_tunnel(relay, install_key)
    assert tunnel.start()

    relay.close()

    deadline = time.monotonic() + 5
    while tunnel.status == TunnelStatus.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)

    assert tunnel.status == TunnelStatus.RECONNECTING
    tunnel.stop()
    assert tunnel.status == TunnelStatus.STOPPED
