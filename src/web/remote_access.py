"""What a public hostname answers when asked who it is.

Whoever holds a tunnel token can point the client at whatever they like, since
it runs on their own computer. The control plane is on the internet, so it can
ask the hostname it issued whether that is still the event behind it, and take
the tunnel back when the answer changes.

One server can run several events at once, each with a hostname of its own, so
the answer is looked up by the hostname that was asked rather than being a
property of the server.

What is held is worth no more than the run of the server holding it: the
control plane hands down a fresh nonce with every heartbeat, and an event that
is not currently live has none.
"""

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RemoteIdentity:
    remote_uniq_id: str
    instance_nonce: str


_identity_by_hostname: dict[str, RemoteIdentity] = {}
_lock = Lock()


def set_remote_identity(hostname: str, remote_uniq_id: str, nonce: str) -> None:
    with _lock:
        _identity_by_hostname[hostname.casefold()] = RemoteIdentity(
            remote_uniq_id, nonce
        )


def clear_remote_identity(hostname: str) -> None:
    with _lock:
        _identity_by_hostname.pop(hostname.casefold(), None)


def remote_identity(hostname: str) -> RemoteIdentity | None:
    with _lock:
        return _identity_by_hostname.get(hostname.casefold())
