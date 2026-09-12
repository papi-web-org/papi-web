"""What the tunnel costs, measured rather than guessed at.

Remote access runs inside the server process, so whatever it spends competes
with serving the venue. Two things were suspected of being the ceiling and
neither could be settled by reading the code:

- the price of one request carried over SSH rather than taken straight off the
  local network, and
- what a crowd of spectators holding connections open does to the arbiter's own
  page, given paramiko decrypts every channel on one thread.

Nothing here asserts. Timing assertions on a shared runner flake until somebody
stops reading them; these print, and the numbers are the point.

    TEST_ENV=true ./venv/bin/pytest tests/benchmarks -m benchmark -s

The relay is a real paramiko server opening real `forwarded-tcpip` channels, and
what answers is a trivial responder rather than the application: the figure
wanted is the tunnel's own overhead, and putting the real server behind it would
bury that under template rendering.
"""

import socket
import statistics
import threading
import time
from typing import Generator

import paramiko
import pytest

from web.tunnel_client import SishTunnel

USERNAME = 'install-aaaa'
SUBDOMAIN = 'paris2026'

REQUEST = b'GET / HTTP/1.1\r\nHost: paris2026.live.example.com\r\n\r\n'
BODY = b'x' * 4096
RESPONSE = (
    b'HTTP/1.1 200 OK\r\n'
    b'Content-Length: ' + str(len(BODY)).encode() + b'\r\n'
    b'\r\n' + BODY
)

#: Enough passes that one scheduling hiccup does not decide the answer.
SAMPLES = 60

#: The crowds to try. A club evening, a weekend open, and a number chosen to be
#: past anything reasonable, because what is being looked for is where it stops
#: behaving rather than whether it copes with twenty.
CROWDS = (0, 10, 50, 200)


class Responder:
    """Answers every connection with the same response, as fast as it can.

    Stands in for the local server so that what is measured is the carrying and
    not the answering.
    """

    def __init__(self) -> None:
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(512)
        self.port = self.socket.getsockname()[1]
        self.running = True
        #: The responder threads one connection each as well, and those are not
        #: the tunnel's cost, so they are counted out of the figure below.
        self.serving = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while self.running:
            try:
                connection, __ = self.socket.accept()
            except OSError:
                return
            threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            ).start()

    def _serve(self, connection: socket.socket) -> None:
        self.serving += 1
        try:
            while self.running:
                if not connection.recv(65536):
                    return
                connection.sendall(RESPONSE)
        except OSError:
            return
        finally:
            self.serving -= 1
            connection.close()

    def close(self) -> None:
        self.running = False
        self.socket.close()


class RelayServer(paramiko.ServerInterface):
    def __init__(self, allowed_key: paramiko.PKey) -> None:
        self.allowed_key = allowed_key
        self.forwarded = threading.Event()

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        return (
            paramiko.AUTH_SUCCESSFUL
            if key == self.allowed_key
            else paramiko.AUTH_FAILED
        )

    def get_allowed_auths(self, username: str) -> str:
        return 'publickey'

    def check_port_forward_request(self, address: str, port: int) -> int:
        self.forwarded.set()
        return port


class Relay:
    """A relay that can push traffic back down the tunnel it was given."""

    def __init__(self, allowed_key: paramiko.PKey) -> None:
        self.host_key = paramiko.ECDSAKey.generate()
        self.server = RelayServer(allowed_key)
        self.transport: paramiko.Transport | None = None
        self.socket = socket.socket()
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        try:
            connection, __ = self.socket.accept()
        except OSError:
            return
        transport = paramiko.Transport(connection)
        transport.add_server_key(self.host_key)
        self.transport = transport
        transport.start_server(server=self.server)

    def open_channel(self) -> paramiko.Channel:
        """One incoming request, as the relay would hand it over."""
        assert self.transport is not None
        return self.transport.open_forwarded_tcpip_channel(
            ('203.0.113.7', 51234), (SUBDOMAIN, 80)
        )

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
        self.socket.close()


@pytest.fixture
def install_key() -> paramiko.PKey:
    return paramiko.ECDSAKey.generate()


@pytest.fixture
def responder() -> Generator[Responder, None, None]:
    responder = Responder()
    yield responder
    responder.close()


@pytest.fixture
def relay(install_key: paramiko.PKey) -> Generator[Relay, None, None]:
    relay = Relay(install_key)
    yield relay
    relay.close()


@pytest.fixture
def tunnel(
    relay: Relay, install_key: paramiko.PKey, responder: Responder
) -> Generator[SishTunnel, None, None]:
    tunnel = SishTunnel(
        local_port=responder.port,
        relay_host='127.0.0.1',
        relay_port=relay.port,
        username=USERNAME,
        subdomain=SUBDOMAIN,
        private_key=install_key,
        relay_host_key=relay.host_key,
        connect_timeout=5,
    )
    assert tunnel.start(), 'the tunnel did not come up'
    assert relay.server.forwarded.wait(5)
    yield tunnel
    tunnel.stop()


def read_response(read) -> None:
    """Read one whole response, so the timing covers arrival and not despatch."""
    seen = b''
    while len(seen) < len(RESPONSE):
        chunk = read(65536)
        if not chunk:
            raise AssertionError(f'the response stopped after {len(seen)} bytes')
        seen += chunk


def time_through_tunnel(relay: Relay, samples: int) -> list[float]:
    """One connection, reused, as a browser keeping its connection alive does."""
    channel = relay.open_channel()
    try:
        timings = []
        for __ in range(samples):
            started = time.perf_counter()
            channel.sendall(REQUEST)
            read_response(channel.recv)
            timings.append((time.perf_counter() - started) * 1000)
        return timings
    finally:
        channel.close()


def time_direct(responder: Responder, samples: int) -> list[float]:
    """The same exchange without the tunnel, which is the figure to beat."""
    connection = socket.create_connection(('127.0.0.1', responder.port))
    try:
        timings = []
        for __ in range(samples):
            started = time.perf_counter()
            connection.sendall(REQUEST)
            read_response(connection.recv)
            timings.append((time.perf_counter() - started) * 1000)
        return timings
    finally:
        connection.close()


def report(name: str, timings: list[float]) -> None:
    ordered = sorted(timings)
    print(
        f'{name:<34}'
        f'median {statistics.median(ordered):7.2f} ms   '
        f'p95 {ordered[int(len(ordered) * 0.95) - 1]:7.2f} ms   '
        f'worst {ordered[-1]:7.2f} ms'
    )


@pytest.mark.benchmark
def test_what_one_request_costs_carried_over_the_tunnel(relay, responder, tunnel):
    """The price of the SSH hop, with nothing else going on.

    Whatever this is, every remote viewer pays it on every request, and no
    amount of tuning elsewhere gets it back.
    """
    print()
    report('straight to the responder', time_direct(responder, SAMPLES))
    report('through the tunnel', time_through_tunnel(relay, SAMPLES))


@pytest.mark.benchmark
def test_what_a_crowd_holding_connections_does_to_everyone_else(
    relay, responder, tunnel
):
    """The question that matters: spectators hold connections open for live
    updates, and paramiko decrypts every one of them on a single thread. This
    says at what size that starts to show.
    """
    print()
    for crowd in CROWDS:
        held = [relay.open_channel() for __ in range(crowd)]
        try:
            # Held open and silent, which is what a screen between updates is.
            report(f'{crowd:>3} connections held', time_through_tunnel(relay, SAMPLES))
        finally:
            for channel in held:
                channel.close()
            # Let the client side notice, so the next round starts from rest.
            time.sleep(0.5)


@pytest.mark.benchmark
def test_what_a_crowd_being_served_does_to_everyone_else(relay, responder, tunnel):
    """The same crowd, but talking rather than waiting.

    Every byte of it is decrypted on the one transport thread, so this is where
    that thread is expected to saturate, and the figure to compare against the
    silent crowd above.
    """
    print()
    for crowd in (10, 50):
        stopping = threading.Event()
        chatter = [
            threading.Thread(
                target=_chatter, args=(relay.open_channel(), stopping), daemon=True
            )
            for __ in range(crowd)
        ]
        for thread in chatter:
            thread.start()
        try:
            report(f'{crowd:>3} connections busy', time_through_tunnel(relay, SAMPLES))
        finally:
            stopping.set()
            for thread in chatter:
                thread.join(timeout=2)
            time.sleep(0.5)


def _chatter(channel: paramiko.Channel, stopping: threading.Event) -> None:
    try:
        while not stopping.is_set():
            channel.sendall(REQUEST)
            read_response(channel.recv)
    except Exception:
        return
    finally:
        channel.close()


@pytest.mark.benchmark
def test_what_a_crowd_costs_in_threads(relay, responder, tunnel):
    """One thread per connection, so this says what the cost of a crowd is in
    the thing the current design spends: threads on the arbiter's laptop.
    """
    print()
    before = threading.active_count()
    held = [relay.open_channel() for __ in range(CROWDS[-1])]
    # The client starts a thread per channel as it accepts them.
    time.sleep(2)
    during = threading.active_count() - responder.serving
    for channel in held:
        channel.close()
    time.sleep(2)
    after = threading.active_count() - responder.serving
    print(
        f'threads: {before} at rest, {during} with {CROWDS[-1]} connections '
        f'({during - before} more), {after} once they had gone'
    )


#: Doubling until something gives, rather than a guess at what is reasonable.
RAMP = (100, 200, 400, 800, 1600, 3200)


@pytest.mark.benchmark
def test_where_holding_connections_open_stops_working(relay, responder, tunnel):
    """How many silent connections this can hold before it stops coping.

    Screens hold a connection and say nothing between updates, so this is the
    shape a crowd of spectators actually has, and the number worth knowing
    before a big open rather than during one.
    """
    print()
    held: list[paramiko.Channel] = []
    try:
        for target in RAMP:
            started = time.perf_counter()
            try:
                while len(held) < target:
                    held.append(relay.open_channel())
            except Exception as e:
                print(f'{target:>5} connections: refused at {len(held)} — {e!r}')
                break
            opening = (time.perf_counter() - started) * 1000
            try:
                timings = time_through_tunnel(relay, 20)
            except Exception as e:
                print(f'{target:>5} connections: held, but unusable — {e!r}')
                break
            print(
                f'{target:>5} connections held   '
                f'median {statistics.median(timings):7.2f} ms   '
                f'threads {threading.active_count() - responder.serving:>5}   '
                f'opening the last batch took {opening:8.0f} ms'
            )
    finally:
        for channel in held:
            channel.close()
