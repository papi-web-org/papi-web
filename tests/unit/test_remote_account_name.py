from types import SimpleNamespace
from typing import cast

from data.account import Account
from web.controllers.profile_controller import ProfileController


def account(
    account_id: int,
    first_name: str | None,
    last_name: str,
    mail: str | None = None,
) -> Account:
    full_name = f'{first_name} {last_name}' if first_name else last_name
    return cast(
        Account,
        SimpleNamespace(
            id=account_id,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            mail=mail,
        ),
    )


NOEMIE = account(1, 'Noémie', 'MÜLLER', 'noemie@example.com')
PIERRE = account(2, 'Pierre', 'DURAND')
CLAIRE = account(3, 'Claire', 'DURAND')
ACCOUNTS = [NOEMIE, PIERRE, CLAIRE]


def named(typed: str) -> int | None:
    return ProfileController._account_id_named(ACCOUNTS, typed)


def test_the_full_name_identifies_the_account():
    assert named('Noémie MÜLLER') == NOEMIE.id


def test_accents_and_capitals_do_not_have_to_be_reproduced():
    assert named('noemie muller') == NOEMIE.id


def test_the_surname_may_come_first():
    assert named('muller noemie') == NOEMIE.id


def test_doubled_spaces_are_forgiven():
    assert named('  noemie   muller ') == NOEMIE.id


def test_a_surname_alone_is_enough_when_only_one_account_bears_it():
    assert named('muller') == NOEMIE.id


def test_the_address_of_the_account_is_accepted():
    assert named('NOEMIE@example.com') == NOEMIE.id


def test_a_surname_shared_by_two_accounts_identifies_neither():
    assert named('durand') is None


def test_a_shared_surname_still_resolves_once_the_first_name_is_given():
    assert named('Claire DURAND') == CLAIRE.id


def test_an_unknown_name_identifies_nothing():
    assert named('someone else') is None


def test_nothing_typed_identifies_nothing():
    assert named('   ') is None
