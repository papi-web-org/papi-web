"""Binding the loopback listener that carries tunnelled requests.

Which listener a request arrived on is what distinguishes a telephone on the
internet from the arbiter's own browser, so the port has to be recorded as the
listener is bound.
"""

import socket
from typing import Generator

import pytest

from common.network import LOCALHOST_IP
from common.sharly_chess_config import SharlyChessConfig
from web.server_engine import ServerEngine

bind_tunnel_socket = ServerEngine._ServerEngine__bind_tunnel_socket  # type: ignore[attr-defined]


@pytest.fixture
def config() -> Generator[SharlyChessConfig, None, None]:
    sc_config = SharlyChessConfig()
    candidates = SharlyChessConfig.web_tunnel_ports
    port = sc_config.web_tunnel_port
    yield sc_config
    SharlyChessConfig.web_tunnel_ports = candidates
    sc_config.web_tunnel_port = port


def test_port_is_asked_of_the_system_when_none_is_configured(config):
    SharlyChessConfig.web_tunnel_ports = []
    config.web_tunnel_port = None

    sock = bind_tunnel_socket()

    try:
        assert sock is not None
        assert config.web_tunnel_port == sock.getsockname()[1]
        assert config.web_tunnel_port > 0
    finally:
        if sock:
            sock.close()


def test_listener_is_reachable_only_from_this_machine(config):
    SharlyChessConfig.web_tunnel_ports = []

    sock = bind_tunnel_socket()

    try:
        assert sock is not None
        assert sock.getsockname()[0] == LOCALHOST_IP
    finally:
        if sock:
            sock.close()


def test_a_configured_port_is_used_as_it_stands(config):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOCALHOST_IP, 0))
        free_port = probe.getsockname()[1]
    SharlyChessConfig.web_tunnel_ports = [free_port]

    sock = bind_tunnel_socket()

    try:
        assert sock is not None
        assert config.web_tunnel_port == free_port
    finally:
        if sock:
            sock.close()


def test_the_next_port_is_tried_when_one_is_taken(config):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind((LOCALHOST_IP, 0))
        taken_port = taken.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((LOCALHOST_IP, 0))
            free_port = probe.getsockname()[1]
        SharlyChessConfig.web_tunnel_ports = [taken_port, free_port]

        sock = bind_tunnel_socket()

        try:
            assert sock is not None
            assert config.web_tunnel_port == free_port
        finally:
            if sock:
                sock.close()


def test_the_server_still_starts_when_no_port_can_be_had(config):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind((LOCALHOST_IP, 0))
        SharlyChessConfig.web_tunnel_ports = [taken.getsockname()[1]]
        config.web_tunnel_port = None

        assert bind_tunnel_socket() is None
        assert config.web_tunnel_port is None
