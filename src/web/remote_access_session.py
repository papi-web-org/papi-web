"""Serving this server to the internet, for as long as it is wanted.

A session ties together the three things that have to agree: the grant the
control plane issued, the tunnel held open to the relay, and the answer this
server gives when the hostname is asked who it is.

It also keeps saying that the server is still being served.  A lease that stops
being renewed is released, which is what lets another computer take the address
over when a laptop is closed mid-tournament — so a session that is *told* it
may no longer serve stops serving rather than holding a hostname the control
plane has given away.  Being unable to ask is not being told: the lease outlives
several heartbeats, and a venue network that drops for a minute must not take
the screens off the air.
"""

import threading
from dataclasses import dataclass
from logging import Logger
from typing import Callable

import paramiko

from common.exception import SharlyChessException
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from web.remote_access import clear_remote_identity, set_remote_identity
from web.remote_access_account import ControlPlaneUnreachableError
from web.remote_access_api import (
    RemoteAccessGrant,
    RemoteAccessUnavailableError,
    close_remote_access,
    open_remote_access,
    register_install,
    send_heartbeat,
)
from web.remote_install import remote_install, set_install_id
from web.tunnel_client import RemoteTunnel, SishTunnel, TunnelStatus

logger: Logger = get_logger()

#: Comfortably inside the lease, so that one missed heartbeat is survivable.
HEARTBEAT_INTERVAL = 60


def relay_host_key(authorized_key: str) -> paramiko.PKey | None:
    """The relay's key, as the tunnel wants it, or None if it cannot be read.

    Checked against what answers, so that the administration screens cannot be
    served through somebody else's relay.
    """
    try:
        entry = paramiko.hostkeys.HostKeyEntry.from_line(f'relay {authorized_key}')
    except Exception:
        entry = None
    if entry is None:
        logger.error('The relay host key could not be read: %r', authorized_key)
        return None
    return entry.key


def install_id() -> str:
    """What the control plane calls this computer, registering it if need be."""
    install = remote_install()
    if install.install_id:
        return install.install_id
    identifier = register_install(install.public_key)
    set_install_id(identifier)
    return identifier


@dataclass
class RemoteAccessSession:
    """One event, served to the internet."""

    remote_uniq_id: str
    grant: RemoteAccessGrant
    tunnel: RemoteTunnel
    name: str
    install_id: str
    #: Told when the session stops, including when it stops itself because the
    #: lease was taken away or the sign-in ended.  Nothing watching can rely on
    #: having asked for it.
    on_stopped: Callable[[], None] | None = None
    #: Why the session ended, when it ended itself rather than being asked to.
    stopped_because: str | None = None
    _stopping: threading.Event = None  # type: ignore[assignment]
    _heartbeat: threading.Thread | None = None

    @property
    def url(self) -> str:
        return self.grant.url

    @property
    def is_serving(self) -> bool:
        """Whether this session is the one answering for the hostname.

        A tunnel between drops still is: it holds the lease, it is coming back
        on its own, and opening a second session alongside it would ask the
        control plane to hand the address to a computer that already has it.
        """
        return self.tunnel.status in (
            TunnelStatus.RUNNING,
            TunnelStatus.RECONNECTING,
        )

    def _renew(self) -> bool:
        """Say the server is still here, and answer with the nonce that proves it.

        A refusal is final.  Only the two things that mend themselves are worth
        waiting through: a control plane out of reach, and one that has no relay
        to offer for the moment.  Anything else the control plane says is
        something it will go on saying, so the session ends and the arbiter is
        told, rather than the heartbeat failing quietly until the lease lapses
        and the address stops working with nothing said.
        """
        try:
            nonce = send_heartbeat(self.remote_uniq_id, self.install_id)
        except (ControlPlaneUnreachableError, RemoteAccessUnavailableError) as e:
            # The lease outlives several heartbeats, so this costs nothing.
            logger.info('Remote access heartbeat deferred: %s', e)
            return True
        except SharlyChessException as e:
            logger.warning(
                'Remote access for [%s] withdrawn: %s', self.grant.hostname, e
            )
            self.stopped_because = str(e)
            return False
        set_remote_identity(self.grant.hostname, self.remote_uniq_id, nonce)
        return True

    def _beat(self) -> None:
        while not self._stopping.wait(HEARTBEAT_INTERVAL):
            if not self._renew():
                self.stop(release=False)
                return

    def stop(self, release: bool = True) -> None:
        """Take the event off the internet, keeping its hostname for next time."""
        self._stopping.set()
        self.tunnel.stop()
        clear_remote_identity(self.grant.hostname)
        if release:
            try:
                close_remote_access(self.remote_uniq_id)
            except SharlyChessException as e:
                # The lease is released by the control plane in any case once
                # the heartbeats stop.
                logger.info('Remote access could not be closed cleanly: %s', e)
        logger.info('Remote access for [%s] stopped', self.grant.hostname)
        if self.on_stopped is not None:
            try:
                self.on_stopped()
            except Exception as e:
                logger.warning('A listener could not be told of the stop: %s', e)


def open_session(
    remote_uniq_id: str,
    name: str,
    take_over: bool = False,
    tunnel_factory=None,
) -> RemoteAccessSession:
    """Put this server on the internet.

    The grant is asked for first: there is no point raising a tunnel to a
    hostname this computer is not entitled to serve.
    """
    tunnel_port = SharlyChessConfig().web_tunnel_port
    if tunnel_port is None:
        raise SharlyChessException('This server has no listener for remote access.')

    identifier = install_id()
    grant = open_remote_access(remote_uniq_id, identifier, name, take_over=take_over)

    host_key = relay_host_key(grant.relay_host_key)
    if host_key is None:
        # Connecting anyway would mean trusting whatever answers on the relay's
        # address, and the screens that take a password travel down this
        # connection. Being unreachable from the internet is the lesser harm,
        # and the local network is serving them either way.
        try:
            close_remote_access(remote_uniq_id)
        except SharlyChessException:
            pass
        raise SharlyChessException(
            'The relay could not be identified, so it was not connected to.'
        )

    # The hostname must answer with the nonce before anything can reach it, or
    # the control plane's first check finds an event it cannot recognise and
    # takes the tunnel back.
    set_remote_identity(grant.hostname, remote_uniq_id, grant.instance_nonce)

    make_tunnel = tunnel_factory or SishTunnel
    tunnel = make_tunnel(
        local_port=tunnel_port,
        relay_host=grant.relay_host,
        relay_port=grant.relay_port,
        username=grant.relay_username,
        subdomain=grant.subdomain,
        private_key=remote_install().signing_key(),
        relay_host_key=host_key,
    )

    if not tunnel.start():
        # The client goes on retrying of its own accord, which is right while a
        # session owns it and wrong once nobody does: the lease is about to be
        # given back, and a forward that reopened afterwards would answer for a
        # hostname this computer no longer holds.
        tunnel.stop()
        clear_remote_identity(grant.hostname)
        try:
            close_remote_access(remote_uniq_id)
        except SharlyChessException:
            pass
        raise SharlyChessException('The tunnel to the relay could not be opened.')

    session = RemoteAccessSession(
        remote_uniq_id=remote_uniq_id,
        grant=grant,
        tunnel=tunnel,
        name=name,
        install_id=identifier,
        _stopping=threading.Event(),
    )
    session._heartbeat = threading.Thread(
        target=session._beat, name=f'remote-access-{grant.subdomain}', daemon=True
    )
    session._heartbeat.start()
    logger.info('Remote access for [%s] open at %s', remote_uniq_id, grant.url)
    return session
