"""What this computer is known by to the relay that carries remote access.

The key pair belongs to the computer rather than to any event: it is what lets a
laptop be recognised, and a lost one disowned, without disturbing the events it
served.  The private half is generated here and never leaves the computer.

The identifier is what the control plane calls this computer, and is obtained by
sending it the public half.
"""

from dataclasses import dataclass
from io import StringIO

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from database.sqlite.config.config_database import ConfigDatabase


@dataclass(frozen=True)
class RemoteInstall:
    """The computer's identity for remote access."""

    private_key: str
    public_key: str
    #: None until the control plane has been told about the public half.
    install_id: str | None

    @property
    def is_registered(self) -> bool:
        return self.install_id is not None

    def signing_key(self) -> paramiko.PKey:
        """The key in the form the SSH client wants it."""
        return paramiko.Ed25519Key.from_private_key(StringIO(self.private_key))


def _generate_key_pair() -> tuple[str, str]:
    """A new key, written the way OpenSSH writes one.

    Ed25519 because the relay accepts it, it is short enough to send about
    without ceremony, and there is no key size to choose badly.
    """
    private_key = Ed25519PrivateKey.generate()
    private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    return private, public


def remote_install() -> RemoteInstall:
    """The computer's identity, given one the first time it is asked for.

    The key outlives the events it serves, so it is generated once and kept:
    generating a new one would leave the control plane holding a computer nobody
    can revoke, and would lose the leases this one holds.
    """
    with ConfigDatabase() as database:
        stored_config = database.load_stored_config()

    if (
        stored_config.remote_install_private_key
        and stored_config.remote_install_public_key
    ):
        return RemoteInstall(
            private_key=stored_config.remote_install_private_key,
            public_key=stored_config.remote_install_public_key,
            install_id=stored_config.remote_install_id,
        )

    private_key, public_key = _generate_key_pair()
    with ConfigDatabase(write=True) as database:
        database.update_remote_install(private_key, public_key, None)
    return RemoteInstall(
        private_key=private_key, public_key=public_key, install_id=None
    )


def set_install_id(install_id: str) -> RemoteInstall:
    """Records what the control plane calls this computer."""
    install = remote_install()
    with ConfigDatabase(write=True) as database:
        database.update_remote_install(
            install.private_key, install.public_key, install_id
        )
    return RemoteInstall(
        private_key=install.private_key,
        public_key=install.public_key,
        install_id=install_id,
    )


def forget_remote_install() -> None:
    """Discards the identity, so that the next use registers a new computer."""
    with ConfigDatabase(write=True) as database:
        database.update_remote_install(None, None, None)
