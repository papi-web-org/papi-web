"""Scheduling of the event snapshots.

Snapshots are driven by the changes, never by a clock: committing a change to
an event asks for a snapshot, and an event nothing writes to is never read nor
copied. A burst of changes — entering the results of a round one by one — is
debounced into a single snapshot once the data entry pauses, with a cap so that
uninterrupted entry still gets snapshotted.

All the copying happens on one worker thread: writing an event must never wait
for its snapshot, and the destination may be a slow one (a memory stick, a
network share, a synchronised folder).
"""

import asyncio
import atexit
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from queue import Queue
from threading import Event, Lock, Thread, Timer, local

from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.snapshot import (
    Snapshot,
    SnapshotException,
    SnapshotFailure,
    SnapshotReason,
    SnapshotRetention,
    write_snapshot,
)

logger = get_logger()

#: How long the changes to an event must pause before it is snapshotted.
IDLE_SECONDS = 15.0
#: How long an event that never stops changing waits for its snapshot.
MAX_LATENCY_SECONDS = 120.0
#: How many times a snapshot that met a momentary problem is retried.
TRANSIENT_RETRIES = 3
#: How long the worker waits between those retries.
RETRY_SECONDS = 2.0


@dataclass
class SnapshotStatus:
    """What is known about the snapshots of one event, as the panel shows it."""

    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure: SnapshotFailure | None = None
    last_failure_message: str | None = None
    consecutive_failures: int = 0

    @property
    def last_success_str(self) -> str:
        from utils.date_time import format_datetime

        return format_datetime(self.last_success_at) if self.last_success_at else ''

    @property
    def is_failing(self) -> bool:
        """Whether the last attempt failed. A momentary problem is only
        reported once it has happened enough times to not be one."""
        if self.last_failure is None:
            return False
        if self.last_failure == SnapshotFailure.TRANSIENT:
            return self.consecutive_failures >= TRANSIENT_RETRIES
        return True


@dataclass
class _PendingChange:
    """An event that changed and is waiting to be snapshotted."""

    first_changed_at: datetime
    timer: Timer | None = None


@dataclass
class _State:
    lock: Lock = field(default_factory=Lock)
    pending: dict[str, _PendingChange] = field(default_factory=dict)
    statuses: dict[str, SnapshotStatus] = field(default_factory=dict)
    queue: Queue[tuple[str, SnapshotReason, int | None, int | None] | None] = field(
        default_factory=Queue
    )
    worker: Thread | None = None
    #: Set while the worker is being stopped, so that a retry waiting between
    #: two attempts gives up at once rather than holding the shutdown.
    stopping: Event = field(default_factory=Event)


_state = _State()

#: The events this thread is working on without wanting them snapshotted.
_suppressed = local()


@contextmanager
def suppress_snapshots(uniq_id: str) -> Iterator[None]:
    """Keeps the changes this thread commits to an event from asking for a
    snapshot.

    An upgrade commits at every step, through instances of the database it
    builds itself, so suppressing the whole run is what keeps a migration from
    filling the directory with copies of an event halfway through it.
    """
    events: dict[str, int] = getattr(_suppressed, 'events', None) or {}
    _suppressed.events = events
    events[uniq_id] = events.get(uniq_id, 0) + 1
    try:
        yield
    finally:
        events[uniq_id] -= 1
        if not events[uniq_id]:
            del events[uniq_id]


def _is_suppressed(uniq_id: str) -> bool:
    return uniq_id in (getattr(_suppressed, 'events', None) or {})


class SnapshotScheduler:
    """Turns the changes committed to the events into snapshots."""

    @classmethod
    def start(cls):
        """Starts the worker thread. Does nothing if it is already running."""
        with _state.lock:
            if _state.worker is not None:
                return
            worker = Thread(target=cls._work, name='snapshot-worker', daemon=True)
            _state.stopping.clear()
            _state.worker = worker
            worker.start()
        atexit.register(cls.stop)
        logger.debug('Snapshot worker started')
        Thread(target=cls._sweep, name='snapshot-sweep', daemon=True).start()

    @staticmethod
    def _sweep():
        """Applies the retention over all the events, off the starting path."""
        try:
            SnapshotRetention.sweep()
        except Exception:
            logger.exception('The retention of the snapshots failed')

    @classmethod
    def stop(cls):
        """Stops the worker thread, letting it finish what it is writing."""
        _state.stopping.set()
        with _state.lock:
            worker = _state.worker
            _state.worker = None
            for pending in _state.pending.values():
                if pending.timer:
                    pending.timer.cancel()
            _state.pending.clear()
        if worker is None:
            return
        _state.queue.put(None)
        worker.join(timeout=10)

    @classmethod
    def notify_changed(cls, uniq_id: str):
        """Asks for a snapshot of an event that has just been written to.

        Called after every committed change, so it must stay cheap and must
        never raise: the caller has finished writing the event and there is
        nothing it could do about a snapshot that cannot be scheduled.
        """
        try:
            if not SharlyChessConfig().snapshot_enabled or _is_suppressed(uniq_id):
                return
            cls.start()
            now = datetime.now()
            with _state.lock:
                pending = _state.pending.get(uniq_id)
                if pending is None:
                    pending = _PendingChange(first_changed_at=now)
                    _state.pending[uniq_id] = pending
                elif pending.timer:
                    pending.timer.cancel()
                    pending.timer = None
                waited = (now - pending.first_changed_at).total_seconds()
                if waited >= MAX_LATENCY_SECONDS:
                    # The changes have not paused long enough to snapshot, and
                    # waiting for them to is now leaving too much unprotected.
                    del _state.pending[uniq_id]
                    _state.queue.put((uniq_id, SnapshotReason.AUTO, None, None))
                    return
                timer = Timer(IDLE_SECONDS, cls._on_idle, args=(uniq_id,))
                timer.daemon = True
                pending.timer = timer
                timer.start()
        except Exception as e:
            logger.exception('Snapshot of event [%s] could not be asked for', uniq_id)
            logger.debug('%s', e)

    @classmethod
    def force(
        cls,
        uniq_id: str,
        reason: SnapshotReason,
        round_: int | None = None,
        tournament_id: int | None = None,
    ):
        """Asks for a snapshot of an event now, without waiting for the changes
        to pause. Returns as soon as it is queued."""
        try:
            if not SharlyChessConfig().snapshot_enabled:
                return
            cls.start()
            cls._cancel_pending(uniq_id)
            _state.queue.put((uniq_id, reason, round_, tournament_id))
        except Exception:
            logger.exception('Snapshot of event [%s] could not be asked for', uniq_id)

    @classmethod
    def snapshot_now(
        cls,
        uniq_id: str,
        reason: SnapshotReason,
        round_: int | None = None,
        tournament_id: int | None = None,
    ) -> Snapshot:
        """Snapshots an event and waits for it, raising a `SnapshotException`
        when it fails.

        For the callers that cannot carry on without the snapshot: taking one
        before restoring another, and the button the user presses to check the
        snapshots work.
        """
        cls._cancel_pending(uniq_id)
        try:
            snapshot = write_snapshot(uniq_id, reason, round_, tournament_id)
        except SnapshotException as e:
            cls._record_failure(uniq_id, e)
            raise
        cls._record_success(uniq_id)
        return snapshot

    @classmethod
    def snapshot_before(
        cls,
        uniq_id: str,
        reason: SnapshotReason,
        round_: int | None = None,
        tournament_id: int | None = None,
    ):
        """Snapshots the state of an event before one of the steps of the event
        changes it, and waits for it.

        Waiting is the point: the snapshot has to hold the state as it is
        *before* the step, which a queued one could not promise. A snapshot
        that fails is logged and no more: the arbiter is pairing a round, and
        that is not to be held up by a copy that cannot be written.
        """
        if not SharlyChessConfig().snapshot_enabled:
            return
        try:
            cls.snapshot_now(uniq_id, reason, round_, tournament_id)
        except SnapshotException as e:
            logger.warning('No snapshot taken of event [%s]: %s', uniq_id, e)
            cls._report(uniq_id, e)

    @classmethod
    async def snapshot_before_async(
        cls,
        uniq_id: str,
        reason: SnapshotReason,
        round_: int | None = None,
        tournament_id: int | None = None,
    ):
        """`snapshot_before` for the request handlers.

        The copy still finishes before the step it precedes, but it runs on a
        thread: the handlers are coroutines, and copying a database on the
        event loop stops every other request, screen and websocket for as long
        as it takes — which on a memory stick or a network share is not a
        matter of milliseconds.
        """
        await asyncio.to_thread(
            cls.snapshot_before, uniq_id, reason, round_, tournament_id
        )

    @classmethod
    def forget_statuses(cls):
        """Forgets what has failed so far.

        Called when the backups are turned off: what failed while they were on
        says nothing about what will happen when they are turned back on, and
        leaving it behind would warn about a backup nobody is waiting for.
        """
        with _state.lock:
            _state.statuses.clear()

    @classmethod
    def status(cls, uniq_id: str) -> SnapshotStatus:
        """What is known about the snapshots of an event."""
        with _state.lock:
            status = _state.statuses.get(uniq_id)
            return status if status else SnapshotStatus()

    @classmethod
    def _cancel_pending(cls, uniq_id: str):
        with _state.lock:
            pending = _state.pending.pop(uniq_id, None)
        if pending and pending.timer:
            pending.timer.cancel()

    @classmethod
    def _on_idle(cls, uniq_id: str):
        """Called by the debounce timer once the changes to an event paused."""
        with _state.lock:
            if _state.pending.pop(uniq_id, None) is None:
                return
        _state.queue.put((uniq_id, SnapshotReason.AUTO, None, None))

    @classmethod
    def _work(cls):
        while True:
            item = _state.queue.get()
            if item is None:
                return
            uniq_id, reason, round_, tournament_id = item
            try:
                cls._write(uniq_id, reason, round_, tournament_id)
            except Exception:
                # The worker outlives whatever one snapshot manages to do.
                logger.exception('Snapshot of event [%s] failed', uniq_id)

    @classmethod
    def _write(
        cls,
        uniq_id: str,
        reason: SnapshotReason,
        round_: int | None,
        tournament_id: int | None,
    ):
        for attempt in range(1, TRANSIENT_RETRIES + 1):
            try:
                write_snapshot(uniq_id, reason, round_, tournament_id)
                cls._record_success(uniq_id)
                cls._apply_retention(uniq_id)
                return
            except SnapshotException as e:
                cls._record_failure(uniq_id, e)
                is_last_attempt = attempt == TRANSIENT_RETRIES
                if e.failure == SnapshotFailure.TRANSIENT and not is_last_attempt:
                    logger.debug('Snapshot of event [%s] retried after: %s', uniq_id, e)
                    if _state.stopping.wait(RETRY_SECONDS):
                        return
                    continue
                if e.failure == SnapshotFailure.DISK_FULL and not is_last_attempt:
                    # Making room is exactly what the retention is for, and it
                    # is worth one more attempt before telling the user.
                    logger.info(
                        'No room left for the snapshot of event [%s], '
                        'applying the retention',
                        uniq_id,
                    )
                    SnapshotRetention.sweep()
                    continue
                cls._report(uniq_id, e)
                return

    @classmethod
    def _apply_retention(cls, uniq_id: str):
        try:
            SnapshotRetention.apply_to_event(uniq_id)
        except Exception:
            # A snapshot that has been written is worth keeping even when the
            # older ones cannot be cleaned up.
            logger.exception('The retention of event [%s] failed', uniq_id)

    @classmethod
    def _record_success(cls, uniq_id: str):
        with _state.lock:
            status = _state.statuses.setdefault(uniq_id, SnapshotStatus())
            status.last_success_at = datetime.now()
            status.last_failure = None
            status.last_failure_at = None
            status.last_failure_message = None
            status.consecutive_failures = 0

    @classmethod
    def _record_failure(cls, uniq_id: str, exception: SnapshotException):
        with _state.lock:
            status = _state.statuses.setdefault(uniq_id, SnapshotStatus())
            status.last_failure_at = datetime.now()
            status.last_failure = exception.failure
            status.last_failure_message = f'{exception}'
            status.consecutive_failures += 1

    @classmethod
    def _report(cls, uniq_id: str, exception: SnapshotException):
        """Tells the user about a failed snapshot, unless it is a momentary
        problem that has not happened enough times to be worth a message."""
        status = cls.status(uniq_id)
        if not status.is_failing:
            return
        logger.error(
            'Snapshot of event [%s] failed (%s): %s',
            uniq_id,
            exception.failure,
            exception,
        )
        cls.publish_snapshot_failed(uniq_id)

    @staticmethod
    def publish_snapshot_failed(uniq_id: str):
        from web.channels import channels_plugin

        # A snapshot can be written before the channels plugin is initialized.
        if channels_plugin and channels_plugin._pub_queue is not None:
            channels_plugin.publish(
                {
                    'event': f'snapshot-failed|{uniq_id}',
                    'data': '',
                },
                ['ws'],
            )
