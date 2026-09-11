"""Throttling of the account log-in attempts.

Password guessing used to be limited by having to reach the server, which meant
standing in the venue.  Once the server is reachable over the internet that no
longer holds, and the cost of an attempt has to be charged explicitly.

Attempts are counted in memory: the counters are worth no more than the run of
the server that holds them, and a restart clearing them is an acceptable trade
for keeping the event database out of the log-in path.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from common.logger import get_logger

logger = get_logger()

#: Failures allowed on one account before the next one starts locking it out.
ACCOUNT_FREE_ATTEMPTS = 4

#: Failures allowed from one caller.  Mobile networks put many phones behind a
#: single address, so this has room for several arbiters fumbling at once while
#: still bounding what one caller can try.
HOST_FREE_ATTEMPTS = 20

#: How long the first lockout lasts, doubling with every further failure.
FIRST_LOCKOUT = timedelta(seconds=60)

MAX_LOCKOUT = timedelta(minutes=15)

#: How long a key is kept after its last failure.
FORGET_AFTER = timedelta(hours=1)


@dataclass(frozen=True)
class ThrottleKey:
    key: str
    free_attempts: int


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: datetime | None = None
    last_failure_at: datetime = field(default_factory=datetime.now)


class LoginThrottle:
    _attempts_by_key: dict[str, _Attempts] = {}
    _lock: Lock = Lock()

    @classmethod
    def locked_for(cls, keys: list[ThrottleKey]) -> timedelta | None:
        """The time left before the most locked-out of the keys accepts an
        attempt again, or None when they all do."""
        now = datetime.now()
        remaining: timedelta | None = None
        with cls._lock:
            cls._forget_old(now)
            for throttle_key in keys:
                attempts = cls._attempts_by_key.get(throttle_key.key)
                if attempts is None or attempts.locked_until is None:
                    continue
                if attempts.locked_until <= now:
                    continue
                key_remaining = attempts.locked_until - now
                if remaining is None or key_remaining > remaining:
                    remaining = key_remaining
        return remaining

    @classmethod
    def record_failure(cls, keys: list[ThrottleKey]):
        now = datetime.now()
        with cls._lock:
            for throttle_key in keys:
                attempts = cls._attempts_by_key.setdefault(
                    throttle_key.key, _Attempts()
                )
                attempts.failures += 1
                attempts.last_failure_at = now
                over = attempts.failures - throttle_key.free_attempts
                if over > 0:
                    lockout = min(FIRST_LOCKOUT * 2 ** (over - 1), MAX_LOCKOUT)
                    attempts.locked_until = now + lockout
                    logger.info(
                        'Log-in locked out for [%s] for %s after %d failures.',
                        throttle_key.key,
                        lockout,
                        attempts.failures,
                    )

    @classmethod
    def record_success(cls, keys: list[ThrottleKey]):
        with cls._lock:
            for throttle_key in keys:
                cls._attempts_by_key.pop(throttle_key.key, None)

    @classmethod
    def _forget_old(cls, now: datetime):
        for key, attempts in list(cls._attempts_by_key.items()):
            if now - attempts.last_failure_at > FORGET_AFTER:
                del cls._attempts_by_key[key]

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._attempts_by_key.clear()


def login_throttle_keys(
    event_uniq_id: str, source_host: str, account_id: int | None
) -> list[ThrottleKey]:
    """The keys an attempt is counted against: the account being tried, so that
    guessing one password does not lock the others out, and the caller, so that
    spreading the guesses over every account of the event does not escape the
    count."""
    keys = [
        ThrottleKey(f'host:{event_uniq_id}:{source_host}', HOST_FREE_ATTEMPTS),
    ]
    if account_id is not None:
        keys.append(
            ThrottleKey(f'account:{event_uniq_id}:{account_id}', ACCOUNT_FREE_ATTEMPTS)
        )
    return keys
