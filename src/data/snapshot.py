"""Snapshots of the event databases.

A snapshot is a consistent, compacted copy of an event database, written by
`VACUUM INTO` on a read-only connection: the copy holds the committed state of
the event whatever a concurrent writer is doing, and the event is never locked
for it.

Snapshots live in one directory per event, and the file name carries what the
listing and the retention need of it, so neither has to open the databases:

    <snapshots dir>/<event uniq_id>/<timestamp>__<version>__<reason>[-<round>[-<tournament>]].scs

What a snapshot *holds* is read from the snapshot itself, not from its name —
see `read_snapshot_content`.
"""

import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from errno import EACCES, ENOSPC
from pathlib import Path
from sqlite3 import connect
from threading import Lock, get_ident
from uuid import uuid4

from packaging.version import InvalidVersion, Version

from common import SHARLY_CHESS_VERSION
from common.exception import SharlyChessException
from common.i18n import _
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from utils import Utils
from utils.date_time import format_datetime
from utils.enum import Extension, Result

logger = get_logger()

#: Holds the snapshots of the events that have been deleted, under the stem of
#: their archive rather than their uniq_id: deleting an event twice archives it
#: under a suffixed name.
ARCHIVED_DIR_NAME = '.archived'

#: How long a temporary file is left alone before it counts as a leftover
#: rather than a snapshot still being written.
LEFTOVER_MIN_AGE = timedelta(hours=1)

_TIMESTAMP_FORMAT = '%Y%m%d-%H%M%S-%f'
_FIELD_SEPARATOR = '__'
_ROUND_SEPARATOR = '-'


class SnapshotReason(StrEnum):
    """Why a snapshot was taken.

    The value is a stable key written into the file name, never a translated
    string: the label is resolved when the snapshot is displayed.
    """

    AUTO = 'auto'
    BEFORE_PAIRING = 'before_pairing'
    BEFORE_UNPAIRING = 'before_unpairing'
    BEFORE_NEXT_ROUND = 'before_next_round'
    BEFORE_PLAYERS_IMPORT = 'before_players_import'
    BEFORE_PLAYERS_DISTRIBUTION = 'before_players_distribution'
    BEFORE_RESTORE = 'before_restore'
    BEFORE_UPGRADE = 'before_upgrade'

    def label(self, round_: int | None = None, tournament: str | None = None) -> str:
        """How the reason reads, naming the round and the tournament it was
        about when they are known.

        "Before round 3 of Main was paired" tells the arbiter which snapshot
        they are looking at; "before a round was paired" does not, and a round
        on its own says nothing in an event holding several tournaments. Both
        are unknown for the steps taking a whole tournament at once and for the
        snapshots taken before this was recorded.
        """
        match self:
            case SnapshotReason.AUTO:
                return _('Automatic')
            case SnapshotReason.BEFORE_PAIRING:
                if round_ and tournament:
                    return _(
                        'Before round {round} of [{tournament}] was paired'
                    ).format(round=round_, tournament=tournament)
                if round_:
                    return _('Before round {round} was paired').format(round=round_)
                if tournament:
                    return _('Before [{tournament}] was paired').format(
                        tournament=tournament
                    )
                return _('Before the rounds were paired')
            case SnapshotReason.BEFORE_UNPAIRING:
                if round_ and tournament:
                    return _(
                        'Before round {round} of [{tournament}] was unpaired'
                    ).format(round=round_, tournament=tournament)
                if round_:
                    return _('Before round {round} was unpaired').format(round=round_)
                if tournament:
                    return _('Before [{tournament}] was unpaired').format(
                        tournament=tournament
                    )
                return _('Before the tournament was unpaired')
            case SnapshotReason.BEFORE_NEXT_ROUND:
                if round_ and tournament:
                    return _('Before [{tournament}] moved to round {round}').format(
                        round=round_, tournament=tournament
                    )
                if round_:
                    return _('Before moving to round {round}').format(round=round_)
                return _('Before moving to another round')
            case SnapshotReason.BEFORE_PLAYERS_IMPORT:
                if tournament:
                    return _('Before players were imported into [{tournament}]').format(
                        tournament=tournament
                    )
                return _('Before players were imported')
            case SnapshotReason.BEFORE_PLAYERS_DISTRIBUTION:
                # Players move between the tournaments, so this belongs to none
                # of them in particular.
                return _('Before players were distributed')
            case SnapshotReason.BEFORE_RESTORE:
                return _('Before a restoration')
            case SnapshotReason.BEFORE_UPGRADE:
                return _('Before an upgrade')
            case _:
                raise ValueError(f'{self=}')

    @property
    def tier(self) -> int:
        """How well the snapshot is protected from the retention, the lower the
        better. A tier never makes room for itself by removing a lower one."""
        match self:
            case SnapshotReason.BEFORE_RESTORE | SnapshotReason.BEFORE_UPGRADE:
                return 0
            case SnapshotReason.AUTO:
                return 2
            case _:
                return 1

    @property
    def is_milestone(self) -> bool:
        """Whether the snapshot holds the state of the event just before one of
        its steps, rather than the changes an automatic snapshot happens to
        catch.

        A milestone is always taken before the step it is named after: what a
        mistaken pairing or import is undone with is the state that came
        before it, never the one it produced.
        """
        return self != SnapshotReason.AUTO


class SnapshotFailure(StrEnum):
    """What kind of failure a snapshot met, which decides what is done about
    it: a retry, a fallback, or a message to the user."""

    #: The target is momentarily unavailable (locked, being synchronised…).
    TRANSIENT = 'transient'
    #: No room left. The retention is worth running before giving up.
    DISK_FULL = 'disk_full'
    #: The target cannot be written to at all (gone, read-only, no rights).
    PERSISTENT = 'persistent'
    #: The event database itself cannot be read: the event is damaged, which is
    #: not a snapshot problem and must not be reported as one.
    SOURCE_UNREADABLE = 'source_unreadable'


class SnapshotException(SharlyChessException):
    """Error raised when a snapshot cannot be written."""

    def __init__(self, message: str, failure: SnapshotFailure):
        super().__init__(message)
        self.failure = failure


class RestoreException(SharlyChessException):
    """Error raised when a snapshot cannot be restored."""


_restore_lock = Lock()
#: The events being restored, against the thread doing the restoring.
_restoring: dict[str, int] = {}


@contextmanager
def _restoring_event(uniq_id: str) -> Iterator[None]:
    """Holds an event while its file is being replaced.

    Restoring swaps the database file, so a write that runs while it happens
    would land in the file being replaced and be lost without a word. The
    writes of the *other* threads are refused instead, for the moment the swap
    takes.

    The thread doing the restoring keeps its own access: it has to migrate the
    event it has just put in place, and a migration opens it for writing.
    """
    thread_id = get_ident()
    with _restore_lock:
        if uniq_id in _restoring:
            raise RestoreException(f'Event [{uniq_id}] is already being restored')
        _restoring[uniq_id] = thread_id
    try:
        yield
    finally:
        with _restore_lock:
            _restoring.pop(uniq_id, None)


def is_being_restored(uniq_id: str) -> bool:
    """Whether the file of an event is being replaced right now."""
    with _restore_lock:
        return uniq_id in _restoring


def is_restored_by_another_thread(uniq_id: str) -> bool:
    """Whether another thread is replacing the file of an event, which is what
    a write has to be refused for."""
    with _restore_lock:
        restoring_thread = _restoring.get(uniq_id)
    return restoring_thread is not None and restoring_thread != get_ident()


@dataclass(frozen=True)
class Snapshot:
    """A snapshot of an event database."""

    file: Path
    uniq_id: str
    taken_at: datetime
    version: Version
    #: None when the file name holds a reason this version does not know, which
    #: a more recent version of the application wrote.
    reason: SnapshotReason | None
    #: The round the step the snapshot precedes was about, when there is one.
    reason_round: int | None = None
    #: The tournament that step was about, when there is one. The id, resolved
    #: to a name from the snapshot's own content, so that it is the name the
    #: tournament had then and it can be read from a damaged event.
    reason_tournament_id: int | None = None

    @classmethod
    def from_file(cls, file: Path, uniq_id: str) -> 'Snapshot | None':
        """Reads a snapshot from its file name, None if the name does not
        follow the convention."""
        fields = file.stem.split(_FIELD_SEPARATOR)
        if len(fields) != 3:
            return None
        timestamp, version, reason = fields
        try:
            taken_at = datetime.strptime(timestamp, _TIMESTAMP_FORMAT)
            parsed_version = Version(version)
        except (ValueError, InvalidVersion):
            return None
        # What the step was about rides along with the reason, as
        # `before_pairing-3-7`: the round, then the tournament. The reasons
        # themselves never hold a dash, and a name written before either was
        # recorded simply carries fewer of them.
        reason_name, *details = reason.split(_ROUND_SEPARATOR)
        try:
            parsed_reason: SnapshotReason | None = SnapshotReason(reason_name)
        except ValueError:
            parsed_reason = None
        # The details are positional, so a step about a whole tournament holds
        # a zero where the round would be. Zero means unknown either way.
        numbers = [int(detail) if detail.isdigit() else 0 for detail in details]
        reason_round = (numbers[0] or None) if numbers else None
        reason_tournament_id = (numbers[1] or None) if len(numbers) > 1 else None
        return cls(
            file,
            uniq_id,
            taken_at,
            parsed_version,
            parsed_reason,
            reason_round,
            reason_tournament_id,
        )

    @property
    def size(self) -> int:
        """Zero once the file is gone: the retention runs on its own thread and
        may have removed it between the listing and here."""
        try:
            return self.file.stat().st_size
        except OSError:
            return 0

    @property
    def taken_at_str(self) -> str:
        return format_datetime(self.taken_at)

    @property
    def tournaments(self) -> 'list[SnapshotTournament] | None':
        """The state of each tournament the snapshot holds, None when it could
        not be read.

        Restoring gives back the whole event, so what is worth showing is every
        tournament in it, not only the one whose change brought the snapshot
        about.
        """
        return read_snapshot_content(self.file)

    @property
    def tier(self) -> int:
        # An unknown reason is protected no better than an automatic snapshot:
        # the tiers exist to keep the steps of the event, and this version
        # cannot tell whether the snapshot marks one.
        return self.reason.tier if self.reason else SnapshotReason.AUTO.tier

    @property
    def is_milestone(self) -> bool:
        return self.reason.is_milestone if self.reason else False

    @property
    def reason_tournament(self) -> str | None:
        """The name the tournament the step was about had in this snapshot."""
        if self.reason_tournament_id is None:
            return None
        return next(
            (
                tournament.name
                for tournament in self.tournaments or []
                if tournament.id == self.reason_tournament_id
            ),
            None,
        )

    @property
    def label(self) -> str:
        if not self.reason:
            return _('Unknown')
        return self.reason.label(self.reason_round, self.reason_tournament)

    @property
    def is_restorable(self) -> bool:
        """Whether the snapshot can be restored into this version.

        A snapshot from an older version is migrated when it is restored, but
        one from a more recent version holds a schema this version does not
        know and could not be read back.
        """
        return self.version <= SHARLY_CHESS_VERSION

    def restore_in_place(self) -> 'Snapshot | None':
        """Replaces the event with this snapshot, keeping its uniq_id, and
        returns the snapshot taken of the state that was replaced.

        The uniq_id is what the screens, the input pages and the plugin
        configurations all point at, so a rollback keeps it: restoring under
        another one would leave a correct event nothing refers to.

        The state being replaced is snapshotted first, which is both what makes
        the rollback reversible and what the failure of a migration is undone
        with. Returns None when there was nothing left to snapshot, the event
        being damaged.
        """
        from data.loader import EventLoader
        from data.snapshot_worker import SnapshotScheduler
        from database.sqlite.event.event_database import EventDatabase

        if not self.is_restorable:
            raise RestoreException(
                f'Snapshot [{self.file.name}] was taken by version '
                f'{self.version}, more recent than this one '
                f'({SHARLY_CHESS_VERSION}), and cannot be restored.'
            )

        event_file = EventDatabase.event_database_path(self.uniq_id)
        with _restoring_event(self.uniq_id):
            replaced: Snapshot | None = None
            if event_file.is_file():
                try:
                    replaced = SnapshotScheduler.snapshot_now(
                        self.uniq_id, SnapshotReason.BEFORE_RESTORE
                    )
                except SnapshotException as e:
                    if e.failure != SnapshotFailure.SOURCE_UNREADABLE:
                        # Without a snapshot of what is about to be replaced
                        # there is no way back, so the restoration does not
                        # start. A damaged event is the exception: there is
                        # nothing to keep, and restoring is the way out.
                        raise RestoreException(
                            'The current state of the event could not be saved, '
                            f'so it has not been replaced: {e}'
                        ) from e
                    logger.warning(
                        'Event [%s] could not be snapshotted before being restored: %s',
                        self.uniq_id,
                        e,
                    )
            self._replace_event_file(event_file)
            EventLoader.unload_event(self.uniq_id)
            try:
                EventLoader.check_event_database(self.uniq_id)
            except SharlyChessException as e:
                logger.exception(
                    'Restoring event [%s] from [%s] failed',
                    self.uniq_id,
                    self.file.name,
                )
                if replaced:
                    replaced._replace_event_file(event_file)
                    EventLoader.unload_event(self.uniq_id)
                raise RestoreException(
                    f'Snapshot [{self.file.name}] could not be restored: {e}'
                ) from e
            EventLoader().load_event(self.uniq_id)
        logger.info(
            'Event [%s] restored from snapshot [%s]', self.uniq_id, self.file.name
        )
        self._publish_event_restored()
        return replaced

    def restore_as_copy(self) -> str:
        """Restores the snapshot as a new event and returns its uniq_id.

        Leaves the event alone, for looking at a past state rather than
        rolling back to it.
        """
        from data.loader import EventLoader
        from database.sqlite.event.event_database import EventDatabase

        if not self.is_restorable:
            raise RestoreException(
                f'Snapshot [{self.file.name}] was taken by version '
                f'{self.version}, more recent than this one '
                f'({SHARLY_CHESS_VERSION}), and cannot be restored.'
            )

        uniq_id = EventLoader().get_unused_event_uniq_id(self.uniq_id)
        file = EventDatabase.event_database_path(uniq_id)
        shutil.copy(self.file, file)
        try:
            EventLoader.check_event_database(uniq_id)
        except SharlyChessException as e:
            file.unlink(missing_ok=True)
            raise RestoreException(
                f'Snapshot [{self.file.name}] could not be restored: {e}'
            ) from e
        logger.info('Snapshot [%s] restored as event [%s]', self.file.name, uniq_id)
        return uniq_id

    def _replace_event_file(self, event_file: Path):
        """Puts this snapshot in place of the event's database file.

        The copy is written beside the event and renamed onto it, so that the
        file the rest of the application opens is either the whole of the old
        one or the whole of the new one.
        """
        temp_file = event_file.parent / f'.restoring-{uuid4().hex}.{Extension.EVENT_DB}'
        try:
            shutil.copy(self.file, temp_file)
            temp_file.replace(event_file)
        except OSError as e:
            temp_file.unlink(missing_ok=True)
            raise RestoreException(
                f'Snapshot [{self.file.name}] could not be put in place: {e}'
            ) from e

    def _publish_event_restored(self):
        from web.channels import channels_plugin

        # A restoration can happen before the channels plugin is initialized.
        if not channels_plugin or channels_plugin._pub_queue is None:
            return
        # The screens and the input pages listen for the results of the event
        # changing, which a restoration does wholesale.
        channels_plugin.publish(
            {
                'event': f'new-user-results|{self.uniq_id}',
                'data': '',
            },
            ['ws'],
        )


@dataclass(frozen=True)
class SnapshotTournament:
    """The state one tournament was in when a snapshot was taken."""

    id: int | None
    name: str
    current_round: int | None
    rounds: int
    #: Boards of the current round holding a result, out of the boards paired.
    results: int
    boards: int

    #: Longest name shown in the state of a snapshot; beyond it the middle is
    #: taken out, and the whole name stays available as a tooltip.
    NAME_MAX_LENGTH = 28

    @property
    def has_results(self) -> bool:
        return self.boards > 0

    @property
    def short_name(self) -> str:
        return Utils.truncate_middle(self.name, self.NAME_MAX_LENGTH)

    @property
    def is_name_truncated(self) -> bool:
        return self.short_name != self.name


#: The state read out of the snapshots, by file. A snapshot file is written
#: once and never modified, so what is read from it can be kept for as long as
#: the application runs.
_content_cache: dict[Path, 'list[SnapshotTournament] | None'] = {}
_content_lock = Lock()


def read_snapshot_content(file: Path) -> list[SnapshotTournament] | None:
    """The tournaments a snapshot holds, None when it could not be read.

    Read from the snapshot itself rather than kept beside it: a snapshot is a
    whole event database, so what is listed is what restoring it would give
    back, and the two cannot come to disagree.

    A snapshot taken by an older version holds an older schema, which this
    version may not be able to read. That is reported as None — no state rather
    than a wrong one.
    """
    with _content_lock:
        if file in _content_cache:
            return _content_cache[file]
    content = _read_snapshot_content(file)
    with _content_lock:
        _content_cache[file] = content
    return content


def _read_snapshot_content(file: Path) -> list[SnapshotTournament] | None:
    """Reads the state through the event itself rather than off its rows.

    The round a tournament is on is not simply the `current_round` column: it
    is null until the arbiter sets it by hand, and the pairing system fills it
    in — from the last paired round, or for a round-robin from the last round
    with played results. Reading the column alone reports a tournament in its
    third round as not started, and reproducing the fall-back in SQL would
    drift from the systems that decide it, so the state is asked of the event.
    Loading one costs a few milliseconds, which the cache pays once.
    """
    from data.event import Event
    from database.sqlite.event.event_database import EventDatabase

    try:
        with EventDatabase(file_path=file) as database:
            stored_event = database.load_stored_event()
        event = Event(stored_event)
        tournaments: list[SnapshotTournament] = []
        for tournament in sorted(event.tournaments, key=lambda t: t.name):
            current_round = tournament.current_round
            boards = tournament.get_round_boards(current_round) if current_round else []
            # A board with a hole on either side is a forfeit, not a result
            # still to come — the same count the pairings screen shows.
            pending = [
                board
                for board in boards
                if board.result == Result.NO_RESULT
                and board.stored_board.white_player_id is not None
                and board.stored_board.black_player_id is not None
            ]
            tournaments.append(
                SnapshotTournament(
                    id=tournament.id,
                    name=tournament.name,
                    current_round=current_round or None,
                    rounds=tournament.rounds,
                    results=len(boards) - len(pending),
                    boards=len(boards),
                )
            )
        return tournaments
    except (sqlite3.Error, SharlyChessException, KeyError, TypeError) as e:
        logger.debug('Snapshot [%s] could not be read: %s', file.name, e)
        return None


def holds_snapshots(directory: Path) -> bool:
    """Whether a directory holds snapshots, at any depth.

    The snapshots share the folder the user named with whatever else they keep
    there, so this is what tells our directories from theirs.
    """
    return any(directory.glob(f'**/*.{Extension.SNAPSHOT}'))


def snapshots_dir(uniq_id: str) -> Path:
    """The directory holding the snapshots of an event."""
    return SharlyChessConfig().snapshot_dir / uniq_id


def archived_snapshots_dir(archive_stem: str) -> Path:
    """The directory holding the snapshots of a deleted event, named after its
    archive."""
    return SharlyChessConfig().snapshot_dir / ARCHIVED_DIR_NAME / archive_stem


def archive_snapshots(uniq_id: str, archive_stem: str):
    """Follows a deleted event: its snapshots are set aside under the name of
    its archive.

    Deleting an event archives it and it can be brought back, so its snapshots
    are kept as well — deleting an event by mistake and restoring it is the
    very moment they are wanted.
    """
    _move_snapshots(snapshots_dir(uniq_id), archived_snapshots_dir(archive_stem))


def move_snapshots_root(source: Path, destination: Path) -> bool:
    """Moves every snapshot to a new folder, when the setting changes.

    Returns whether they made it: a folder that cannot be moved out of is not
    worth refusing the new one for, the snapshots taken from then on go to it
    either way.
    """
    if not source.is_dir() or source == destination:
        return True
    if not _move_snapshots(source, destination):
        return False
    logger.info('Snapshots moved from [%s] to [%s]', source, destination)
    return True


def rename_snapshots(uniq_id: str, new_uniq_id: str):
    """Follows a renamed event: its snapshots are listed under its uniq_id, so
    they move with it."""
    _move_snapshots(snapshots_dir(uniq_id), snapshots_dir(new_uniq_id))


def restore_archived_snapshots(archive_stem: str, uniq_id: str):
    """Follows an event brought back from its archive: its snapshots come back
    with it, under the uniq_id it has been given."""
    _move_snapshots(archived_snapshots_dir(archive_stem), snapshots_dir(uniq_id))


def delete_archived_snapshots(archive_stem: str):
    """Gives up the snapshots of an event whose archive has been deleted for
    good. The only place snapshots are removed for anything but the retention."""
    directory = archived_snapshots_dir(archive_stem)
    if not directory.is_dir():
        return
    shutil.rmtree(directory, ignore_errors=True)
    logger.info('Snapshots of the archive [%s] deleted', archive_stem)


def _move_snapshots(source: Path, destination: Path) -> bool:
    """Moves everything under `source` into `destination`, and says whether it
    made it.

    `shutil.move` rather than a rename: the folder the user chooses is very
    often on another disk — that is the point of choosing one — and a rename
    cannot cross filesystems, where this falls back to copying.

    The walk goes all the way down, and a directory is only removed once it
    holds nothing: the snapshots of the deleted events sit two levels deep,
    under `.archived/<archive>/`.

    Only the snapshots move, and only the directories holding them are walked:
    the folder is the user's, and what else they keep in it stays where it is.
    """
    if not source.is_dir():
        return True
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for entry in sorted(source.iterdir()):
            target = destination / entry.name
            if entry.is_dir():
                if holds_snapshots(entry) and not _move_snapshots(entry, target):
                    return False
            elif entry.suffix == f'.{Extension.SNAPSHOT}':
                shutil.move(entry, target)
        if not any(source.iterdir()):
            source.rmdir()
    except OSError as e:
        logger.warning(
            'Snapshots could not be moved from [%s] to [%s]: %s',
            source,
            destination,
            e,
        )
        return False
    logger.debug('Snapshots moved from [%s] to [%s]', source, destination)
    return True


def snapshot_file(
    directory: Path,
    reason: SnapshotReason,
    round_: int | None = None,
    tournament_id: int | None = None,
) -> Path:
    """The file a snapshot taken now for `reason` is written to."""
    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    reason_field = reason.value
    if tournament_id:
        # Positional, so the round keeps its place even when it is unknown.
        reason_field = (
            f'{reason_field}{_ROUND_SEPARATOR}{round_ or 0}'
            f'{_ROUND_SEPARATOR}{tournament_id}'
        )
    elif round_:
        reason_field = f'{reason_field}{_ROUND_SEPARATOR}{round_}'
    return directory / _FIELD_SEPARATOR.join(
        (
            timestamp,
            f'{SHARLY_CHESS_VERSION}',
            f'{reason_field}.{Extension.SNAPSHOT}',
        )
    )


def _source_failure(error: Exception) -> SnapshotFailure:
    """Classifies a failure met while reading the event database."""
    if isinstance(error, sqlite3.OperationalError):
        # `unable to open database file` also lands here when the file is gone,
        # which the caller checks for before opening it.
        return SnapshotFailure.TRANSIENT
    if isinstance(error, sqlite3.DatabaseError):
        return SnapshotFailure.SOURCE_UNREADABLE
    return SnapshotFailure.PERSISTENT


def _target_failure(error: Exception) -> SnapshotFailure:
    """Classifies a failure met while writing the snapshot."""
    if isinstance(error, OSError) and not isinstance(error, sqlite3.Error):
        if error.errno == ENOSPC:
            return SnapshotFailure.DISK_FULL
        if error.errno == EACCES or isinstance(error, PermissionError):
            # A file synchronisation client holding the file for a moment is
            # the usual cause, and it is worth retrying.
            return SnapshotFailure.TRANSIENT
        return SnapshotFailure.PERSISTENT
    message = f'{error}'.lower()
    if 'full' in message:
        return SnapshotFailure.DISK_FULL
    if 'locked' in message or 'busy' in message:
        return SnapshotFailure.TRANSIENT
    if isinstance(error, sqlite3.OperationalError):
        # `unable to open database file`, `attempt to write a readonly
        # database`, `disk I/O error`: the target is not usable as it is.
        return SnapshotFailure.PERSISTENT
    if isinstance(error, sqlite3.DatabaseError):
        # `VACUUM INTO` reads the whole source, so a database error raised
        # while it runs is the source being damaged, not the target.
        return SnapshotFailure.SOURCE_UNREADABLE
    return SnapshotFailure.PERSISTENT


def write_snapshot(
    uniq_id: str,
    reason: SnapshotReason,
    round_: int | None = None,
    tournament_id: int | None = None,
) -> Snapshot:
    """Writes a snapshot of the event `uniq_id` and returns it.

    Raises a `SnapshotException` carrying the kind of failure met.
    """
    from database.sqlite.event.event_database import EventDatabase

    source = EventDatabase.event_database_path(uniq_id)
    if not source.is_file():
        raise SnapshotException(
            f'Event database [{source}] does not exist',
            SnapshotFailure.SOURCE_UNREADABLE,
        )

    directory = snapshots_dir(uniq_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SnapshotException(
            f'Snapshot directory [{directory}] is not usable: {e}',
            _target_failure(e),
        ) from e

    try:
        database = connect(f'file:{source}?mode=ro', uri=True)
    except sqlite3.Error as e:
        raise SnapshotException(
            f'Event database [{source}] could not be read: {e}',
            _source_failure(e),
        ) from e

    # `VACUUM INTO` refuses to write over a file that exists, and the target
    # must sit in the destination directory for the rename below to stay on one
    # filesystem.
    temp_file = directory / f'.tmp-{uuid4().hex}.{Extension.SNAPSHOT}'
    try:
        database.execute('PRAGMA busy_timeout=5000')
        database.execute('VACUUM INTO ?', (f'{temp_file}',))
    except (sqlite3.Error, OSError) as e:
        temp_file.unlink(missing_ok=True)
        raise SnapshotException(
            f'Snapshot of event [{uniq_id}] failed: {e}',
            _target_failure(e),
        ) from e
    finally:
        database.close()

    file = snapshot_file(directory, reason, round_, tournament_id)
    try:
        temp_file.replace(file)
    except OSError as e:
        temp_file.unlink(missing_ok=True)
        raise SnapshotException(
            f'Snapshot of event [{uniq_id}] could not be renamed to [{file}]: {e}',
            _target_failure(e),
        ) from e

    snapshot = Snapshot.from_file(file, uniq_id)
    assert snapshot is not None
    logger.info(
        'Snapshot of event [%s] written to [%s] (%s bytes)',
        uniq_id,
        file.name,
        snapshot.size,
    )
    return snapshot


def snapshots_to_prune(
    snapshots: list[Snapshot],
    keep_milestones: int,
    keep_auto: int,
    max_age: timedelta | None = None,
    now: datetime | None = None,
) -> list[Snapshot]:
    """Which of the snapshots of one event the retention gives up.

    `snapshots` comes in with the most recent first, as the loader lists them.

    The reasons are ranked, and a snapshot never makes room for itself by
    giving up a better ranked one: pairing a round and then entering fifty
    results gives up the older result snapshots, never the pairing.

    The automatic snapshots are counted over the whole event rather than since
    its last step. Counting them per step would give up everything preceding a
    step, and a step is snapshotted *before* it is known to be possible — a
    pairing the engine then refuses would take an hour of result snapshots
    with it.
    """
    now = now or datetime.now()
    if len(snapshots) <= 1:
        # The most recent snapshot of an event is the one that would be
        # restored, and it is kept whatever the settings say.
        return []
    newest, older = snapshots[0], snapshots[1:]
    pruned: list[Snapshot] = []

    milestones_kept = 0
    autos_kept = 0
    for snapshot in older:
        if snapshot.tier == 0:
            continue
        if snapshot.tier == 1:
            milestones_kept += 1
            if milestones_kept > keep_milestones:
                pruned.append(snapshot)
            continue
        autos_kept += 1
        if autos_kept > keep_auto:
            pruned.append(snapshot)

    if max_age is not None:
        # An event nobody has touched for a long time keeps its last steps and
        # nothing else.
        kept_milestones = [
            snapshot
            for snapshot in snapshots
            if snapshot.tier <= 1 and snapshot not in pruned
        ][:2]
        for snapshot in older:
            if snapshot in pruned or snapshot in kept_milestones:
                continue
            if now - snapshot.taken_at > max_age:
                pruned.append(snapshot)

    assert newest not in pruned
    return pruned


class SnapshotLoader:
    """Lists the snapshots of the events."""

    @staticmethod
    def snapshots(uniq_id: str) -> list[Snapshot]:
        """The snapshots of an event, the most recent first."""
        directory = snapshots_dir(uniq_id)
        if not directory.is_dir():
            return []
        snapshots: list[Snapshot] = []
        for file in directory.glob(f'*.{Extension.SNAPSHOT}'):
            if snapshot := Snapshot.from_file(file, uniq_id):
                snapshots.append(snapshot)
        return sorted(snapshots, key=lambda snapshot: snapshot.taken_at, reverse=True)

    @classmethod
    def snapshot(cls, uniq_id: str, name: str) -> Snapshot | None:
        """A snapshot of an event by file name, None if it does not exist."""
        directory = snapshots_dir(uniq_id)
        file = (directory / name).resolve()
        # `name` reaches this from a URL: a snapshot is only ever looked up in
        # the directory of its own event.
        if file.parent != directory.resolve() or not file.is_file():
            return None
        return Snapshot.from_file(file, uniq_id)

    @staticmethod
    def last_snapshot_at(uniq_id: str) -> datetime | None:
        """When the event was last snapshotted, None if it never was."""
        snapshots = SnapshotLoader.snapshots(uniq_id)
        return snapshots[0].taken_at if snapshots else None

    @staticmethod
    def snapshotted_event_ids() -> list[str]:
        """The events a snapshot directory exists for, deleted ones aside.

        A directory holding no snapshot is none of our business: the folder
        belongs to the user and may hold anything else.
        """
        root = SharlyChessConfig().snapshot_dir
        if not root.is_dir():
            return []
        return sorted(
            directory.name
            for directory in root.iterdir()
            if directory.is_dir()
            and directory.name != ARCHIVED_DIR_NAME
            and holds_snapshots(directory)
        )

    @staticmethod
    def archived_snapshot_directories() -> list[Path]:
        """The directories holding the snapshots of the deleted events."""
        root = SharlyChessConfig().snapshot_dir / ARCHIVED_DIR_NAME
        if not root.is_dir():
            return []
        return sorted(
            directory
            for directory in root.iterdir()
            if directory.is_dir() and holds_snapshots(directory)
        )

    @staticmethod
    def snapshots_in(directory: Path, uniq_id: str) -> list[Snapshot]:
        """The snapshots held in a directory, the most recent first."""
        if not directory.is_dir():
            return []
        snapshots: list[Snapshot] = []
        for file in directory.glob(f'*.{Extension.SNAPSHOT}'):
            if snapshot := Snapshot.from_file(file, uniq_id):
                snapshots.append(snapshot)
        return sorted(snapshots, key=lambda snapshot: snapshot.taken_at, reverse=True)


class SnapshotRetention:
    """Keeps the size of the snapshot directory in hand.

    Snapshots are driven by the changes and are on by default, so what they
    take up grows out of sight of the user: what follows is not optional.
    """

    @classmethod
    def apply_to_event(cls, uniq_id: str):
        """Applies the retention to one event, after it has been snapshotted."""
        config = SharlyChessConfig()
        cls._prune(
            snapshots_to_prune(
                SnapshotLoader.snapshots(uniq_id),
                keep_milestones=config.snapshot_keep_milestones,
                keep_auto=config.snapshot_keep_auto,
            )
        )

    @classmethod
    def sweep(cls):
        """Applies everything the retention covers, over all the events.

        Run at startup: what it takes care of beyond the per-event retention —
        the age, the leftovers, the total size — is not worth doing on every
        snapshot.
        """
        config = SharlyChessConfig()
        max_age = timedelta(days=config.snapshot_max_age_days)
        for uniq_id in SnapshotLoader.snapshotted_event_ids():
            cls._prune(
                snapshots_to_prune(
                    SnapshotLoader.snapshots(uniq_id),
                    keep_milestones=config.snapshot_keep_milestones,
                    keep_auto=config.snapshot_keep_auto,
                    max_age=max_age,
                )
            )
        for directory in SnapshotLoader.archived_snapshot_directories():
            cls._prune(
                snapshots_to_prune(
                    SnapshotLoader.snapshots_in(directory, directory.name),
                    keep_milestones=config.snapshot_keep_milestones,
                    keep_auto=config.snapshot_keep_auto,
                    max_age=max_age,
                )
            )
        cls._remove_leftovers()
        cls._remove_orphans()
        cls._enforce_total_size()

    @classmethod
    def _prune(cls, snapshots: list[Snapshot]):
        for snapshot in snapshots:
            try:
                snapshot.file.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(
                    'Snapshot [%s] could not be removed: %s', snapshot.file, e
                )
                continue
            with _content_lock:
                _content_cache.pop(snapshot.file, None)
            logger.debug('Snapshot [%s] removed by the retention', snapshot.file.name)

    @classmethod
    def _remove_leftovers(cls):
        """Removes the temporary files a snapshot interrupted halfway leaves.

        Only the ones old enough to be leftovers: a snapshot being written at
        this moment has a temporary file of its own, indistinguishable from a
        leftover by name, and removing it makes the snapshot fail as it is
        renamed into place. This runs on its own thread, so that is not a
        remote possibility.
        """
        root = SharlyChessConfig().snapshot_dir
        if not root.is_dir():
            return
        oldest_in_use = datetime.now() - LEFTOVER_MIN_AGE
        for file in root.glob(f'*/.tmp-*.{Extension.SNAPSHOT}'):
            try:
                written_at = datetime.fromtimestamp(file.stat().st_mtime)
            except OSError:
                continue
            if written_at > oldest_in_use:
                continue
            file.unlink(missing_ok=True)
            logger.debug('Leftover snapshot file [%s] removed', file.name)

    @classmethod
    def _remove_orphans(cls):
        """Removes the snapshots of the events that are neither there nor
        archived: their files have been taken away by hand."""
        from data.loader import ArchiveLoader
        from database.sqlite.event.event_database import EventDatabase

        for uniq_id in SnapshotLoader.snapshotted_event_ids():
            if EventDatabase.event_database_path(uniq_id).is_file():
                continue
            if ArchiveLoader.get_archive(uniq_id):
                continue
            directory = snapshots_dir(uniq_id)
            cls._prune(SnapshotLoader.snapshots(uniq_id))
            try:
                directory.rmdir()
            except OSError:
                # Whatever else is in there is the user's, and stays.
                pass
            logger.info(
                'Snapshots of the unknown event [%s] removed (%s)', uniq_id, directory
            )

    @classmethod
    def _enforce_total_size(cls):
        """Brings the whole snapshot directory back under the size allowed,
        giving up the least well ranked and oldest snapshots first."""
        max_total_bytes = SharlyChessConfig().snapshot_max_total_mb * 1024 * 1024
        snapshots: list[Snapshot] = []
        newest_by_event: set[Path] = set()
        listings = [
            SnapshotLoader.snapshots(uniq_id)
            for uniq_id in SnapshotLoader.snapshotted_event_ids()
        ] + [
            # The deleted events count towards the size as well.
            SnapshotLoader.snapshots_in(directory, directory.name)
            for directory in SnapshotLoader.archived_snapshot_directories()
        ]
        for event_snapshots in listings:
            if event_snapshots:
                newest_by_event.add(event_snapshots[0].file)
            snapshots.extend(event_snapshots)
        total = sum(snapshot.size for snapshot in snapshots)
        if total <= max_total_bytes:
            return
        logger.info(
            'Snapshots take up %s bytes for %s allowed, applying the retention',
            total,
            max_total_bytes,
        )
        # The worst ranked first, and the oldest of those first: what is given
        # up is the automatic snapshots of the events left alone the longest.
        candidates = sorted(
            (
                snapshot
                for snapshot in snapshots
                if snapshot.file not in newest_by_event
            ),
            key=lambda snapshot: (-snapshot.tier, snapshot.taken_at),
        )
        for snapshot in candidates:
            if total <= max_total_bytes:
                return
            size = snapshot.size
            cls._prune([snapshot])
            total -= size
