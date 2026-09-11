import pytest

from web.login_throttle import (
    ACCOUNT_FREE_ATTEMPTS,
    HOST_FREE_ATTEMPTS,
    LoginThrottle,
    login_throttle_keys,
)

EVENT_ID = 'event-login-throttle'
HOST = '198.51.100.7'
OTHER_HOST = '198.51.100.8'
ACCOUNT_ID = 1
OTHER_ACCOUNT_ID = 2


@pytest.fixture(autouse=True)
def empty_counters():
    LoginThrottle.reset()
    yield
    LoginThrottle.reset()


def fail(times: int, host: str = HOST, account_id: int | None = ACCOUNT_ID):
    keys = login_throttle_keys(EVENT_ID, host, account_id)
    for __ in range(times):
        LoginThrottle.record_failure(keys)
    return keys


def test_the_first_failures_leave_the_account_free_to_try_again():
    keys = fail(ACCOUNT_FREE_ATTEMPTS)

    assert LoginThrottle.locked_for(keys) is None


def test_a_failure_past_the_allowance_locks_the_account_out():
    keys = fail(ACCOUNT_FREE_ATTEMPTS + 1)

    locked_for = LoginThrottle.locked_for(keys)

    assert locked_for is not None
    assert locked_for.total_seconds() > 0


def test_locking_one_account_out_leaves_the_others_alone():
    fail(ACCOUNT_FREE_ATTEMPTS + 1)

    other_keys = login_throttle_keys(EVENT_ID, OTHER_HOST, OTHER_ACCOUNT_ID)

    assert LoginThrottle.locked_for(other_keys) is None


def test_spreading_the_guesses_over_accounts_still_locks_the_caller_out():
    for account_id in range(HOST_FREE_ATTEMPTS + 1):
        fail(1, account_id=account_id)

    fresh_account_keys = login_throttle_keys(EVENT_ID, HOST, account_id=9999)

    assert LoginThrottle.locked_for(fresh_account_keys) is not None


def test_the_lockout_grows_with_every_further_failure():
    keys = fail(ACCOUNT_FREE_ATTEMPTS + 1)
    first = LoginThrottle.locked_for(keys)

    LoginThrottle.record_failure(keys)
    second = LoginThrottle.locked_for(keys)

    assert first is not None and second is not None
    assert second > first


def test_a_successful_log_in_clears_the_count():
    keys = fail(ACCOUNT_FREE_ATTEMPTS + 1)

    LoginThrottle.record_success(keys)

    assert LoginThrottle.locked_for(keys) is None
