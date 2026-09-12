"""The proof that a sign-in belongs to this machine.

It is worth nothing once used and nothing after a restart, which is the point:
a code arriving with a state nobody is waiting for has not been vouched for by
anything here.
"""

from datetime import datetime, timedelta

from web.controllers.remote_access_controller import _PendingExchanges


def test_the_verifier_comes_back_for_the_state_it_was_started_with():
    pending = _PendingExchanges()
    pending.start('state-1', 'verifier-1')

    assert pending.take('state-1') == 'verifier-1'


def test_a_state_nobody_is_waiting_for_yields_nothing():
    pending = _PendingExchanges()

    assert pending.take('state-unknown') is None


def test_an_exchange_can_only_be_taken_once():
    pending = _PendingExchanges()
    pending.start('state-1', 'verifier-1')

    pending.take('state-1')

    assert pending.take('state-1') is None


def test_exchanges_do_not_outlive_their_welcome():
    pending = _PendingExchanges()
    pending.start('state-1', 'verifier-1')
    pending._by_state['state-1'] = ('verifier-1', datetime.now() - timedelta(seconds=1))

    assert pending.take('state-1') is None


def test_one_abandoned_exchange_does_not_disturb_another():
    pending = _PendingExchanges()
    pending.start('state-old', 'verifier-old')
    pending._by_state['state-old'] = (
        'verifier-old',
        datetime.now() - timedelta(seconds=1),
    )
    pending.start('state-new', 'verifier-new')

    assert pending.take('state-new') == 'verifier-new'
    assert pending.take('state-old') is None
