"""The machine's identity for remote access.

The key is what the relay recognises a laptop by, so it has to outlive the
events served with it: a machine that quietly generated a new one would leave
the control plane holding an install nobody can revoke.
"""

import pytest

from web.remote_install import forget_remote_install, remote_install, set_install_id


@pytest.fixture(autouse=True)
def no_install():
    forget_remote_install()
    yield
    forget_remote_install()


def test_a_key_is_generated_the_first_time_it_is_asked_for():
    install = remote_install()

    assert install.public_key.startswith('ssh-ed25519 ')
    assert 'OPENSSH PRIVATE KEY' in install.private_key
    assert not install.is_registered


def test_the_same_key_is_given_back_afterwards():
    first = remote_install()

    second = remote_install()

    assert second.private_key == first.private_key
    assert second.public_key == first.public_key


def test_the_key_is_one_an_ssh_client_can_present():
    install = remote_install()

    key = install.signing_key()

    assert f'{key.get_name()} {key.get_base64()}' == install.public_key


def test_the_identifier_is_kept_without_disturbing_the_key():
    install = remote_install()

    registered = set_install_id('install_abc')

    assert registered.install_id == 'install_abc'
    assert registered.private_key == install.private_key
    assert remote_install().install_id == 'install_abc'
    assert remote_install().is_registered


def test_forgetting_the_identity_issues_a_new_one():
    first = remote_install()

    forget_remote_install()

    assert remote_install().private_key != first.private_key
