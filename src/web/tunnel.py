"""Recognition of the requests that reached the server through the tunnel.

The tunnel client runs on the computer it exposes, so its requests arrive from
the loopback address just as the local browser's do.  The listener they arrive
on is what tells them apart, and unlike a header it cannot be forged by the
caller.
"""

from typing import Any

from common.sharly_chess_config import SharlyChessConfig

#: How long a session opened from the internet is kept.  Long enough to cover a
#: day of play without a phone holding the event for a fortnight afterwards.
REMOTE_SESSION_MAX_AGE = 8 * 60 * 60


def request_is_tunnelled(scope: Any) -> bool:
    tunnel_port: int | None = SharlyChessConfig().web_tunnel_port
    if tunnel_port is None:
        return False
    server: tuple[str, int | None] | None = scope.get('server')
    return server is not None and server[1] == tunnel_port
