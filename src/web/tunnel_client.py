"""The client that holds the tunnel open.

The arbiter's computer has no public address, so it opens a connection outward
to the relay and the relay sends requests back down it. The transport is kept
behind an interface and the rest of the application is told only whether the
tunnel is up.

The connection is plain SSH with a reverse port forward, which is why no client
binary ships with the application: `paramiko` is already a dependency, and SSH
has done the multiplexing, keepalives and reconnection for thirty years.
"""

import selectors
import socket
import threading
import time
from abc import ABC, abstractmethod
from enum import StrEnum

import paramiko

from common.logger import get_logger

logger = get_logger()


class TunnelStatus(StrEnum):
    STOPPED = 'stopped'
    RUNNING = 'running'
    #: Open once, not connected at this moment, and coming back on its own.
    #: Distinct from FAILED because a tunnel that drops mid-tournament reopens
    #: without being asked, and calling that stopped tells the arbiter their
    #: screens have gone when they have not.
    RECONNECTING = 'reconnecting'
    FAILED = 'failed'


class RemoteTunnel(ABC):
    """Holds a tunnel open between this computer and the public hostname the
    control plane issued for an event."""

    @abstractmethod
    def start(self) -> bool:
        """Start the tunnel, returning whether it came up.  Starting one that is
        already running is a no-op."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the tunnel, waiting for it to go."""

    @property
    @abstractmethod
    def status(self) -> TunnelStatus: ...


RECONNECT_DELAYS = (1, 2, 5, 10, 30, 60)

#: Which end of a carried request a selector woke for.
FROM_RELAY = 'relay'
FROM_SERVER = 'server'


class SishTunnel(RemoteTunnel):
    """A reverse SSH forward to the relay.

    The relay names the hostname after the user it is connected as, and refuses
    a key that is not the one the control plane registered for that user, so an
    install cannot answer for another's hostname."""

    #: The port the forward is requested on.  The relay routes by the Host
    #: header rather than by port, so this is the same for every install.
    REMOTE_PORT = 80

    #: Seconds between keepalives.  Venue routers drop idle connections, and a
    #: tunnel that has silently died looks exactly like one that is working.
    KEEPALIVE = 30

    #: How long a channel may sit with neither side saying anything.  Screens
    #: hold a stream open between updates, so this matches the relay's own idle
    #: timeout rather than undercutting it: a shorter one here would tear down
    #: connections the relay was deliberately configured to keep.
    CHANNEL_TIMEOUT = 10 * 60

    #: How long to wait for the local server to accept the forwarded request.
    #: It is on this computer, so it either answers at once or is not there.
    LOCAL_CONNECT_TIMEOUT = 10

    def __init__(
        self,
        local_port: int,
        relay_host: str,
        relay_port: int,
        username: str,
        subdomain: str,
        private_key: paramiko.PKey,
        relay_host_key: paramiko.PKey,
        connect_timeout: int = 15,
        reconnect_delays: tuple[int, ...] = RECONNECT_DELAYS,
    ):
        self.local_port = local_port
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.username = username
        self.subdomain = subdomain
        self.private_key = private_key
        self.relay_host_key = relay_host_key
        self.connect_timeout = connect_timeout
        self.reconnect_delays = reconnect_delays
        self._client: paramiko.SSHClient | None = None
        self._holder: threading.Thread | None = None
        self._wanted = threading.Event()
        self._connected = threading.Event()
        # Set once the first attempt has been made, so that starting can report
        # a refusal straight away rather than waiting out a timeout.
        self._attempted = threading.Event()
        self._failed = False
        # Whether the forward has been up at least once during this run, which
        # is what separates a tunnel reopening from one that never opened.
        self._was_connected = False

    # ---------------------------------------------------------------------
    # Forwarding
    # ---------------------------------------------------------------------

    def _pipe(self, channel: paramiko.Channel) -> None:
        """Carry one request between the relay and the local server."""
        try:
            local = socket.create_connection(
                ('127.0.0.1', self.local_port), timeout=self.LOCAL_CONNECT_TIMEOUT
            )
        except OSError:
            logger.exception('A tunnelled request could not reach the local server.')
            channel.close()
            return
        # A selector rather than select(), which cannot be given a file
        # descriptor numbered at or above FD_SETSIZE. Each carried request costs
        # three of them, so a few hundred spectators at once is enough to push
        # new ones past 1024 — and select() answers that by raising, which took
        # the connection down instead of slowing it.
        with selectors.DefaultSelector() as selector:
            # Told apart by what they were registered with rather than by
            # comparing the objects back, which says nothing about their type.
            selector.register(channel, selectors.EVENT_READ, data=FROM_RELAY)
            selector.register(local, selectors.EVENT_READ, data=FROM_SERVER)
            try:
                while True:
                    ready = selector.select(self.CHANNEL_TIMEOUT)
                    if not ready:
                        break
                    for key, __ in ready:
                        if key.data == FROM_RELAY:
                            carried = channel.recv(16384)
                            if not carried:
                                return
                            local.sendall(carried)
                        else:
                            answered = local.recv(16384)
                            if not answered:
                                return
                            channel.sendall(answered)
            except OSError:
                pass
            finally:
                channel.close()
                local.close()

    def _on_channel(self, channel: paramiko.Channel, *__) -> None:
        threading.Thread(target=self._pipe, args=(channel,), daemon=True).start()

    # ---------------------------------------------------------------------
    # Connection
    # ---------------------------------------------------------------------

    def _connect(self) -> paramiko.SSHClient:
        """Open the connection, to the relay and to nothing else.

        The key the control plane named is the only one accepted. Anything else
        answering on that address is refused rather than learned: the screens
        that take a password travel down this connection, so a relay that cannot
        prove who it is would be in a position to read them.
        """
        client = paramiko.SSHClient()
        client.get_host_keys().add(
            f'[{self.relay_host}]:{self.relay_port}',
            self.relay_host_key.get_name(),
            self.relay_host_key,
        )
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            self.relay_host,
            port=self.relay_port,
            username=self.username,
            pkey=self.private_key,
            look_for_keys=False,
            allow_agent=False,
            timeout=self.connect_timeout,
        )
        transport = client.get_transport()
        assert transport is not None
        transport.set_keepalive(self.KEEPALIVE)
        transport.request_port_forward(
            self.subdomain, self.REMOTE_PORT, self._on_channel
        )
        return client

    def _hold_open(self) -> None:
        """Keep the forward up for as long as it is wanted.

        A tournament outlives any one connection: venue WiFi drops, laptops
        sleep, relays restart.  Coming back on its own is the difference
        between a brief gap and an arbiter who cannot enter a result."""
        attempt = 0
        while self._wanted.is_set():
            try:
                # Held locally as well as on the instance: stopping clears the
                # instance from another thread, and this one is still using it.
                client = self._connect()
                self._client = client
            except Exception:
                logger.exception('The tunnel could not be opened.')
                self._failed = True
                self._connected.clear()
                self._attempted.set()
                delay = self.reconnect_delays[
                    min(attempt, len(self.reconnect_delays) - 1)
                ]
                attempt += 1
                if self._wanted.wait(delay):
                    continue
                break
            attempt = 0
            self._failed = False
            self._was_connected = True
            self._connected.set()
            self._attempted.set()
            logger.info('Tunnel open for [%s].', self.subdomain)
            transport = client.get_transport()
            while self._wanted.is_set() and transport is not None:
                if not transport.is_active():
                    break
                time.sleep(1)
            self._connected.clear()
            self._close_client()
            if self._wanted.is_set():
                logger.warning('The tunnel dropped, reopening.')

    def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.exception('The tunnel did not close cleanly.')

    # ---------------------------------------------------------------------
    # RemoteTunnel
    # ---------------------------------------------------------------------

    def start(self) -> bool:
        if self._wanted.is_set():
            return self.status == TunnelStatus.RUNNING
        self._failed = False
        self._was_connected = False
        self._attempted.clear()
        self._wanted.set()
        self._holder = threading.Thread(target=self._hold_open, daemon=True)
        self._holder.start()
        # The caller wants to know whether it came up, not merely that it was
        # asked for.  Waiting on the attempt rather than on success means a
        # refusal is reported at once, while the holder keeps retrying in case
        # the relay is merely out of reach for the moment.
        self._attempted.wait(timeout=self.connect_timeout + 5)
        return self.status == TunnelStatus.RUNNING

    def stop(self) -> None:
        if not self._wanted.is_set():
            return
        self._wanted.clear()
        self._close_client()
        holder, self._holder = self._holder, None
        if holder is not None:
            holder.join(timeout=5)
        self._connected.clear()
        self._attempted.clear()
        # Cleared after the holder has gone, not before: an attempt already
        # under way records its failure on the way out, and a tunnel nobody
        # wants any more is stopped rather than broken.
        self._failed = False
        logger.info('Tunnel closed for [%s].', self.subdomain)

    @property
    def status(self) -> TunnelStatus:
        if self._connected.is_set():
            return TunnelStatus.RUNNING
        if self._wanted.is_set() and self._was_connected:
            return TunnelStatus.RECONNECTING
        if self._failed:
            return TunnelStatus.FAILED
        return TunnelStatus.STOPPED
