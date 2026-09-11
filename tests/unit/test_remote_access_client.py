from typing import Any, Generator, cast

import pytest
from litestar.plugins.htmx import HTMXRequest
from litestar.types import HTTPScope

from common.network import LOCALHOST_IP
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.client import Client
from data.account import Account

LAN_PORT = 80
TUNNEL_PORT = 18080


def build_request(
    client_host: str, server_port: int, forwarded_for: str | None = None
) -> HTMXRequest:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b'x-forwarded-for', forwarded_for.encode()))
    scope: dict[str, Any] = {
        'type': 'http',
        'method': 'GET',
        'path': '/',
        'raw_path': b'/',
        'root_path': '',
        'query_string': b'',
        'scheme': 'http',
        'http_version': '1.1',
        'headers': headers,
        'client': (client_host, 54321),
        'server': (LOCALHOST_IP, server_port),
        'state': {},
    }
    return HTMXRequest(cast(HTTPScope, scope))


@pytest.fixture
def tunnel_port() -> Generator[int, None, None]:
    config = SharlyChessConfig()
    previous = config.web_tunnel_port
    config.web_tunnel_port = TUNNEL_PORT
    yield TUNNEL_PORT
    config.web_tunnel_port = previous


def test_a_request_on_the_web_listener_from_the_machine_itself_is_local(tunnel_port):
    client = Client(build_request(LOCALHOST_IP, LAN_PORT))

    assert not client.remote
    assert client.account.id == Account.ADMINISTRATOR_ID


def test_a_request_on_the_tunnel_listener_is_remote_despite_its_source_address(
    tunnel_port,
):
    client = Client(build_request(LOCALHOST_IP, tunnel_port))

    assert client.remote
    assert client.account.id == Account.ANONYMOUS_ID


def test_requests_are_never_remote_while_no_tunnel_listener_is_bound():
    config = SharlyChessConfig()
    previous = config.web_tunnel_port
    config.web_tunnel_port = None
    try:
        client = Client(build_request(LOCALHOST_IP, TUNNEL_PORT))

        assert not client.remote
        assert client.account.id == Account.ADMINISTRATOR_ID
    finally:
        config.web_tunnel_port = previous


def test_the_caller_of_a_tunnelled_request_is_named_by_the_forwarding_header(
    tunnel_port,
):
    client = Client(
        build_request(LOCALHOST_IP, tunnel_port, forwarded_for='203.0.113.7')
    )

    assert client.source_host == '203.0.113.7'


def test_a_caller_cannot_rename_itself_by_sending_its_own_forwarding_header(
    tunnel_port,
):
    """The relay appends what it saw, so only the last entry is its own."""
    client = Client(
        build_request(
            LOCALHOST_IP, tunnel_port, forwarded_for='10.0.0.1, 9.9.9.9, 203.0.113.7'
        )
    )

    assert client.source_host == '203.0.113.7'


def test_a_request_from_the_venue_network_is_named_by_the_address_it_came_from():
    config = SharlyChessConfig()
    previous = config.web_tunnel_port
    config.web_tunnel_port = TUNNEL_PORT
    try:
        client = Client(
            build_request('192.168.1.42', LAN_PORT, forwarded_for='203.0.113.7')
        )

        assert client.source_host == '192.168.1.42'
    finally:
        config.web_tunnel_port = previous
