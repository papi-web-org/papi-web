"""Whether this server is reachable over the internet.

The tunnel reaches the server, and the server serves every event on it, so this
is one decision for the computer rather than one per event: an address
named after a single event was never only that event's.

The identity the address is issued against is written the first time remote
access is turned on and kept afterwards, so that the address is the same every
time this server is reachable.
"""

import socket
import threading
from logging import Logger
from typing import Callable
from uuid import uuid4

from common import experimental_features_enabled
from common.exception import SharlyChessException
from common.logger import get_logger
from database.sqlite.config.config_database import ConfigDatabase
from web.remote_access_account import is_signed_in
from web.remote_access_api import retire_remote_access
from web.remote_access_session import RemoteAccessSession, open_session

logger: Logger = get_logger()

_session: RemoteAccessSession | None = None
_lock = threading.Lock()

#: Why the server stopped being reachable, when it stopped on its own. Kept
#: after the session has gone: the arbiter finds out by looking at the window,
#: which may be minutes later.
_stopped_because: str | None = None

#: Told when this server starts or stops being reachable, so that whatever is
#: showing it can say so. It happens on its own at startup and when a lease is
#: lost, so nothing watching can rely on having asked for it.
_listeners: list[Callable[[], None]] = []


def on_remote_access_change(listener: Callable[[], None]) -> None:
    _listeners.append(listener)


def _announce_change() -> None:
    for listener in list(_listeners):
        try:
            listener()
        except Exception as e:
            # Nothing that merely wanted to know may stop an event being served.
            logger.warning('A listener could not be told of remote access: %s', e)


def server_identity() -> str:
    """The identity the address is issued against, made on first use."""
    with ConfigDatabase() as database:
        stored_config = database.load_stored_config()
    if stored_config.remote_uniq_id:
        return stored_config.remote_uniq_id
    remote_uniq_id = str(uuid4())
    with ConfigDatabase(write=True) as database:
        database.update_remote_access(stored_config.remote_access, remote_uniq_id)
    return remote_uniq_id


def is_wanted() -> bool:
    """Whether the arbiter has asked for this server to be reachable."""
    with ConfigDatabase() as database:
        return database.load_stored_config().remote_access


def _remember_wanted(wanted: bool) -> None:
    with ConfigDatabase(write=True) as database:
        stored_config = database.load_stored_config()
        database.update_remote_access(wanted, stored_config.remote_uniq_id)


def _server_name() -> str:
    """What the control plane is told about this computer.

    Only enough to tell one computer from another in the arbiter's own account.
    Nothing about the events being served travels this way: they go down the
    tunnel to whoever opened the page.
    """
    return socket.gethostname()


def current_session() -> RemoteAccessSession | None:
    """The session serving this server, if one still is.

    A session whose lease was taken away stops itself, and holding on to it
    afterwards would have the window offering to turn off something that is
    already off, and the next request to turn it on quietly answered with the
    session that stopped.
    """
    global _session
    with _lock:
        if _session is not None and not _session.is_serving:
            _session = None
        return _session


def url() -> str | None:
    """Where this server can be reached from the internet, if it can be."""
    session = current_session()
    return session.url if session else None


def stopped_because() -> str | None:
    """Why the server stopped being reachable without being asked to."""
    return _stopped_because


def _session_stopped(session: RemoteAccessSession) -> None:
    global _stopped_because
    _stopped_because = session.stopped_because
    _announce_change()


def start_serving(take_over: bool = False) -> RemoteAccessSession:
    """Put this server on the internet, or hand back the session already doing so."""
    global _session, _stopped_because
    serving = current_session()
    if serving is not None:
        return serving

    session = open_session(server_identity(), _server_name(), take_over=take_over)
    # A session that is refused stops itself, and the window has to hear about
    # that, and why, the same way it hears about being asked to stop.
    session.on_stopped = lambda: _session_stopped(session)
    with _lock:
        _session = session
    _stopped_because = None
    _remember_wanted(True)
    _announce_change()
    return session


def stop_serving(remember: bool = True) -> None:
    """Take this server off the internet, keeping its address for next time."""
    global _session
    with _lock:
        session, _session = _session, None
    if session is not None:
        session.stop()
    if remember:
        _remember_wanted(False)
    if session is not None or remember:
        _announce_change()


def use_new_url() -> None:
    """Give this computer's URL up and take a fresh one.

    For the tournament after this one: the codes printed for the last are meant
    to stop reaching anything rather than to go on reaching whatever is served
    next from the same laptop.

    Serving stops first, because the URL being given up is the one currently
    being served. The site is told before the identifier is forgotten — once it
    is gone there is nothing left here to name the URL by — but being unable to
    tell it does not stop the change: the identifier is what decides which URL
    this computer asks for, so forgetting it is what actually takes effect, and
    a URL left behind is reserved for ever either way.
    """
    stop_serving(remember=False)

    identity = server_identity()
    try:
        retire_remote_access(identity)
    except SharlyChessException as e:
        logger.warning('The old address could not be given up cleanly: %s', e)

    global _stopped_because
    with ConfigDatabase(write=True) as database:
        database.update_remote_access(False, None)
    _stopped_because = None
    logger.info('Remote access address [%s] given up', identity)
    _announce_change()


def resume_session() -> bool:
    """Put the server back on the internet if it was there before a restart.

    Every reason it cannot be is a reason to leave it alone and say so, never
    to prevent the server starting: the local network is what the venue is
    actually running on.
    """
    if not experimental_features_enabled() or not is_wanted() or not is_signed_in():
        return False
    try:
        start_serving()
    except SharlyChessException as e:
        logger.warning('Remote access could not be resumed: %s', e)
        return False
    logger.info('Remote access resumed at %s', url())
    return True


def resume_session_in_background() -> None:
    """Resume without holding up the local network, which needs none of this."""
    threading.Thread(
        target=resume_session, name='remote-access-resume', daemon=True
    ).start()


def stop_all_sessions() -> None:
    """Give the lease up on the way out, so another computer can take over."""
    stop_serving(remember=False)
