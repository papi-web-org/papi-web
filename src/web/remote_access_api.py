"""Talking to the control plane about remote access.

Four exchanges, all of them on behalf of the account signed in on this computer:
registering the computer, opening this server to the internet, saying that it is
still being served, and giving it up again.

Nothing about the events being served travels this way.  The only thing sent
about the computer is what to call it, so that its owner can tell one
computer from another in their own account; titles, players, pairings and
results go down the tunnel to whoever opened the page.

The control plane decides; this asks.  Where its answer needs acting on rather
than reporting — a server already live on another laptop, a computer that has
been disowned, an address belonging to somebody else — it is raised as
something the caller can recognise.
"""

from dataclasses import dataclass
from logging import Logger
from typing import Any

import requests

from common.exception import SharlyChessException
from common.logger import get_logger
from web.remote_access_account import (
    CONTROL_PLANE_URL,
    REQUEST_TIMEOUT,
    ControlPlaneUnreachableError,
    access_token,
)

logger: Logger = get_logger()


class NotSignedInError(SharlyChessException):
    """Nobody has signed in on this computer."""


class EventHeldElsewhereError(SharlyChessException):
    """The event is being served by another computer, which still holds the lease."""


class InstallNotRecognisedError(SharlyChessException):
    """The control plane no longer recognises this computer."""


class ServerNotOursError(SharlyChessException):
    """The address asked for was issued to another account."""


class RemoteAccessUnavailableError(SharlyChessException):
    """The control plane has no relay to offer.  Worth trying again later."""


class AddressBlockedError(SharlyChessException):
    """The URL has been taken out of service."""


class AddressRetiredError(SharlyChessException):
    """The URL was given up in favour of a fresh one."""


class AddressLimitReachedError(SharlyChessException):
    """The account already holds as many addresses as it may."""


class RemoteAccessRefusedError(SharlyChessException):
    """Refused for a reason this version does not know by name.

    Read as final rather than as something to keep trying: the control plane
    said no in terms this application cannot act on, and an computer that
    retried would say nothing to the arbiter while getting nowhere.
    """


@dataclass(frozen=True)
class RemoteAccessGrant:
    """Everything the computer needs to raise the tunnel for this server."""

    hostname: str
    url: str
    relay_host: str
    relay_port: int
    relay_host_key: str
    relay_username: str
    subdomain: str
    instance_nonce: str

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> 'RemoteAccessGrant':
        return cls(
            hostname=data['hostname'],
            url=data['url'],
            relay_host=data['relayHost'],
            relay_port=int(data['relayPort']),
            relay_host_key=data['relayHostKey'],
            relay_username=data['relayUsername'],
            subdomain=data['subdomain'],
            instance_nonce=data['instanceNonce'],
        )


def _error_code(response: requests.Response) -> str | None:
    try:
        return response.json().get('error')
    except ValueError:
        return None


def _refusal_description(response: requests.Response, code: str | None) -> str | None:
    """What to tell the arbiter about a refusal this version cannot name."""
    try:
        described = response.json().get('error_description')
    except ValueError:
        described = None
    if described:
        return str(described)
    return f'Remote access was refused [{code}].' if code else None


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    token = access_token()
    if token is None:
        raise NotSignedInError('No account is signed in on this computer.')

    try:
        response = requests.post(
            CONTROL_PLANE_URL + path,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
            json=body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise ControlPlaneUnreachableError(
            f'The control plane could not be reached: {e}'
        )

    if response.ok:
        return response.json()['data']

    # The code in the body is what is acted on; the status is only how it
    # arrived.  Everything named here is final except where it says otherwise:
    # a refusal is not something to go on asking for.
    code = _error_code(response)
    logger.debug(
        'Remote access refused: %s %s %s', response.status_code, code, response.text
    )

    if code == 'conflict' or response.status_code == 409:
        raise EventHeldElsewhereError(
            'This address is already being served by another computer.'
        )
    if code == 'unknown_install':
        raise InstallNotRecognisedError(
            'This computer has been disowned and cannot register itself again. '
            'It needs a new identity before it can be used for remote access.'
        )
    if code == 'not_owned':
        raise ServerNotOursError(
            'This address was issued to another account; sign in as that account.'
        )
    if code == 'blocked':
        raise AddressBlockedError('This address has been taken out of service.')
    if code == 'retired':
        raise AddressRetiredError(
            'This address was given up in favour of a new one.'
        )
    if code == 'limit_reached':
        raise AddressLimitReachedError(
            'This account already holds as many addresses as it may.'
        )
    if code == 'unavailable' or response.status_code == 503:
        raise RemoteAccessUnavailableError(
            'The site has no relay to offer at the moment.'
        )
    if response.status_code == 401:
        raise NotSignedInError(
            'The sign-in was refused; sign in again for remote access.'
        )
    if response.status_code >= 500:
        raise ControlPlaneUnreachableError(
            f'The control plane answered {response.status_code}.'
        )

    raise RemoteAccessRefusedError(
        _refusal_description(response, code) or 'Remote access was refused.'
    )


def register_install(public_key: str, label: str | None = None) -> str:
    """Tell the control plane about this computer, and learn what it calls it.

    Sending a key it already knows returns the same identifier, so this is also
    how a computer recovers one it has lost.
    """
    data = _post(
        '/api/v1/remote-access/installs', {'public_key': public_key, 'label': label}
    )
    return data['install_id']


def open_remote_access(
    remote_uniq_id: str,
    install_id: str,
    name: str,
    take_over: bool = False,
) -> RemoteAccessGrant:
    """Claim the address and learn where to connect.

    Taking over from a computer of the same account that has stopped answering
    keeps the hostname, so the address on any printed code goes on working.  It
    reaches no further than that account: an address belonging to another is
    refused however it is asked for.
    """
    data = _post(
        '/api/v1/remote-access/open',
        {
            'name': name,
            'remote_uniq_id': remote_uniq_id,
            'install_id': install_id,
            'take_over': take_over,
        },
    )
    return RemoteAccessGrant.from_response(data)


def send_heartbeat(remote_uniq_id: str, install_id: str, name: str | None = None) -> str:
    """Say the server is still being served, and take the next nonce.

    The name is sent only when it has changed, which it does not while the
    server runs.
    """
    body: dict[str, Any] = {
        'remote_uniq_id': remote_uniq_id,
        'install_id': install_id,
    }
    if name is not None:
        body['name'] = name
    data = _post('/api/v1/remote-access/heartbeat', body)
    return data['instance_nonce']


def close_remote_access(remote_uniq_id: str) -> None:
    """Stop serving, keeping the address for the next time this computer runs."""
    _post('/api/v1/remote-access/close', {'remote_uniq_id': remote_uniq_id})


def retire_remote_access(remote_uniq_id: str) -> None:
    """Give the address up for good, so the codes printed against it die.

    The site keeps the address reserved rather than freeing it, so nothing
    printed can ever come to point at a stranger's screens.
    """
    _post('/api/v1/remote-access/retire', {'remote_uniq_id': remote_uniq_id})
