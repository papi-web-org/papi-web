"""Snapshots of the event databases: naming, retention and the archive
lifecycle.

The snapshots are driven by the changes committed to an event, so what is
checked here is that a committed change asks for one, that a burst of changes
becomes a single snapshot, that the retention gives up the automatic snapshots
before the steps of the event, and that a snapshot restores both over the event
and beside it.
"""

import asyncio
import os
from datetime import datetime, timedelta
from errno import EXDEV
from pathlib import Path
from threading import Thread, get_ident
from time import sleep

import pytest
from packaging.version import Version

from common import SHARLY_CHESS_VERSION
from common.exception import DatabaseCorruptedException, SharlyChessException
from common.sharly_chess_config import SharlyChessConfig
from data.loader import ArchiveLoader, EventLoader
from data.snapshot import (
    RestoreException,
    SnapshotException,
    SnapshotFailure,
    Snapshot,
    SnapshotLoader,
    SnapshotReason,
    SnapshotRetention,
    SnapshotTournament,
    ARCHIVED_DIR_NAME,
    _restoring_event,
    archived_snapshots_dir,
    is_being_restored,
    snapshot_file,
    move_snapshots_root,
    snapshots_dir,
    snapshots_to_prune,
    write_snapshot,
)
from data.snapshot_worker import SnapshotScheduler
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredBoard,
    StoredPairing,
    StoredPlayer,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from utils import Utils
from utils.enum import Extension, Result

NOW = datetime(2026, 9, 10, 12, 0, 0)


def fake_snapshot(
    minutes_ago: int, reason: SnapshotReason, uniq_id: str = 'event'
) -> Snapshot:
    """A snapshot with no file behind it, for the selection rules alone."""
    return Snapshot(
        file=Path(f'{minutes_ago:06d}__5.0.0__{reason.value}.scs'),
        uniq_id=uniq_id,
        taken_at=NOW - timedelta(minutes=minutes_ago),
        version=Version('5.0.0'),
        reason=reason,
    )


def newest_first(snapshots: list[Snapshot]) -> list[Snapshot]:
    return sorted(snapshots, key=lambda snapshot: snapshot.taken_at, reverse=True)


def pruned_names(
    snapshots: list[Snapshot],
    keep_milestones: int = 20,
    keep_auto: int = 10,
    max_age: timedelta | None = None,
) -> set[str]:
    return {
        snapshot.file.name
        for snapshot in snapshots_to_prune(
            newest_first(snapshots), keep_milestones, keep_auto, max_age, NOW
        )
    }


@pytest.mark.unit
class TestSnapshotNaming:
    def test_file_name_round_trip(self):
        """The name of a snapshot carries when it was taken, by which version
        and why, so that listing them opens no database."""
        file = snapshot_file(Path('/snapshots/event'), SnapshotReason.BEFORE_PAIRING)
        snapshot = Snapshot.from_file(file, 'event')
        assert snapshot is not None
        assert snapshot.reason == SnapshotReason.BEFORE_PAIRING
        assert snapshot.version == SHARLY_CHESS_VERSION
        assert snapshot.uniq_id == 'event'

    def test_the_round_of_a_step_is_carried_by_the_name(self):
        """ "Before round 3 was paired" tells the arbiter which snapshot they
        are looking at, so the round rides along with the reason."""
        file = snapshot_file(Path('/snapshots/event'), SnapshotReason.BEFORE_PAIRING, 3)
        snapshot = Snapshot.from_file(file, 'event')

        assert snapshot is not None
        assert snapshot.reason == SnapshotReason.BEFORE_PAIRING
        assert snapshot.reason_round == 3
        assert snapshot.label == 'Before round 3 was paired'

    def test_a_step_taken_without_a_round_reads_without_one(self):
        """Pairing every round of a tournament at once is about no round in
        particular."""
        file = snapshot_file(Path('/snapshots/event'), SnapshotReason.BEFORE_PAIRING)
        snapshot = Snapshot.from_file(file, 'event')

        assert snapshot is not None
        assert snapshot.reason_round is None
        assert snapshot.label == 'Before the rounds were paired'

    def test_a_name_written_before_the_round_was_recorded_still_reads(self):
        snapshot = Snapshot.from_file(
            Path('20260910-120000-000000__5.0.0__before_unpairing.scs'), 'event'
        )

        assert snapshot is not None
        assert snapshot.reason == SnapshotReason.BEFORE_UNPAIRING
        assert snapshot.reason_round is None

    def test_a_name_that_does_not_follow_the_convention_is_ignored(self):
        for name in ('event.scs', 'a__b.scs', '.tmp-abcdef.scs', 'x__y__z.scs'):
            assert Snapshot.from_file(Path(name), 'event') is None

    def test_an_unknown_reason_is_kept_but_protected_no_better_than_an_automatic_one(
        self,
    ):
        """A more recent version may write a reason this one does not know: the
        snapshot is still listed, and the retention treats it as automatic
        since this version cannot tell whether it marks a step."""
        snapshot = Snapshot.from_file(
            Path('20260910-120000-000000__5.0.0__something_new.scs'), 'event'
        )
        assert snapshot is not None
        assert snapshot.reason is None
        assert snapshot.tier == SnapshotReason.AUTO.tier
        assert not snapshot.is_milestone

    def test_a_snapshot_from_a_later_version_is_not_restorable(self):
        later = Snapshot.from_file(
            Path('20260910-120000-000000__99.0.0__auto.scs'), 'event'
        )
        earlier = Snapshot.from_file(
            Path('20260910-120000-000000__1.0.0__auto.scs'), 'event'
        )
        assert later is not None and earlier is not None
        assert not later.is_restorable
        assert earlier.is_restorable


@pytest.mark.unit
class TestSnapshotDirSetting:
    def test_the_folder_is_absolute(self):
        """A path given on the command line makes the data directory relative,
        and a relative folder cannot be handed to a folder dialog nor compared
        with the folder one returns."""
        assert SharlyChessConfig().snapshot_dir.is_absolute()

    def test_the_folder_the_user_names_is_the_folder_used(self, monkeypatch):
        monkeypatch.setattr(
            SharlyChessConfig().stored_config, 'snapshot_dir', '/tmp/my-folder'
        )
        config = SharlyChessConfig()

        assert config.snapshot_dir == Path('/tmp/my-folder')
        assert not config.snapshot_dir_is_default

    def test_nothing_of_the_user_is_removed_from_their_folder(
        self, monkeypatch, tmp_path
    ):
        """The snapshots share the folder the user named, so the retention
        removes only what it wrote itself."""
        monkeypatch.setattr(
            SharlyChessConfig().stored_config, 'snapshot_dir', str(tmp_path)
        )
        theirs = tmp_path / 'Taxes'
        theirs.mkdir(parents=True)
        (theirs / 'invoice.pdf').write_bytes(b'a document of their own')
        loose = tmp_path / 'loose-note.txt'
        loose.write_bytes(b'not a snapshot either')

        SnapshotRetention.sweep()

        assert (theirs / 'invoice.pdf').is_file()
        assert theirs.is_dir()
        assert loose.is_file()

    def test_the_snapshots_of_an_unknown_event_go_but_their_neighbours_stay(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            SharlyChessConfig().stored_config, 'snapshot_dir', str(tmp_path)
        )
        orphan = tmp_path / 'an-event-that-no-longer-exists'
        orphan.mkdir(parents=True)
        snapshot = orphan / f'20260910-120000-000000__5.0.0__auto.{Extension.SNAPSHOT}'
        snapshot.write_bytes(b'backup')
        theirs = orphan / 'notes.txt'
        theirs.write_bytes(b'a file of their own, in our directory')

        SnapshotRetention.sweep()

        assert not snapshot.exists()
        assert theirs.is_file(), 'their file was taken with the snapshots'
        assert orphan.is_dir(), 'their directory was removed'

    def test_no_custom_folder_is_the_default_one(self, monkeypatch):
        monkeypatch.setattr(SharlyChessConfig().stored_config, 'snapshot_dir', None)

        assert SharlyChessConfig().snapshot_dir_is_default


@pytest.mark.unit
class TestTournamentNameLength:
    """A long name must not widen the panel, and two names differing only at
    their end have to stay tellable apart — which the end ellipsis CSS offers
    cannot do."""

    @staticmethod
    def tournament(name: str) -> SnapshotTournament:
        return SnapshotTournament(
            id=1, name=name, current_round=1, rounds=7, results=0, boards=0
        )

    def test_a_short_name_is_left_alone(self):
        tournament = self.tournament('Open A')

        assert tournament.short_name == 'Open A'
        assert not tournament.is_name_truncated

    def test_a_long_name_loses_its_middle(self):
        tournament = self.tournament('Championnat de Bretagne des Jeunes 2026 - Open A')

        short = tournament.short_name
        assert len(short) == SnapshotTournament.NAME_MAX_LENGTH
        assert tournament.is_name_truncated
        assert short.startswith('Championnat')
        assert short.endswith('Open A')
        assert '…' in short

    def test_names_differing_at_their_end_stay_different(self):
        base = 'Championnat de Bretagne des Jeunes 2026 - Open '
        first = self.tournament(base + 'A').short_name
        second = self.tournament(base + 'B').short_name

        assert first != second

    def test_truncating_to_nothing_leaves_the_name_alone(self):
        assert Utils.truncate_middle('Open A', 1) == 'Open A'
        assert Utils.truncate_middle('Open A', 0) == 'Open A'


@pytest.mark.unit
class TestMovingTheBackupsFolder:
    """Choosing one's own folder moves the backups already taken into it."""

    @staticmethod
    def populate(root: Path) -> list[Path]:
        """A root holding one live event and one deleted one."""
        files = [
            root
            / 'event-a'
            / f'20260910-120000-000000__5.0.0__auto.{Extension.SNAPSHOT}',
            root
            / 'event-b'
            / f'20260910-130000-000000__5.0.0__auto.{Extension.SNAPSHOT}',
            root
            / ARCHIVED_DIR_NAME
            / 'deleted-event'
            / f'20260910-140000-000000__5.0.0__auto.{Extension.SNAPSHOT}',
        ]
        for file in files:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'backup')
        return files

    def relative(self, root: Path, files: list[Path]) -> set[str]:
        return {str(file.relative_to(root)) for file in files}

    def test_the_backups_are_moved_not_copied(self, tmp_path):
        source, destination = tmp_path / 'from', tmp_path / 'to'
        files = self.populate(source)

        assert move_snapshots_root(source, destination)

        moved = list(destination.glob(f'**/*.{Extension.SNAPSHOT}'))
        assert self.relative(destination, moved) == self.relative(source, files)
        assert not source.exists()

    def test_the_backups_of_the_deleted_events_come_along(self, tmp_path):
        """They sit a level deeper, under `.archived/<archive>/`."""
        source, destination = tmp_path / 'from', tmp_path / 'to'
        self.populate(source)

        assert move_snapshots_root(source, destination)

        archived = destination / ARCHIVED_DIR_NAME / 'deleted-event'
        assert len(list(archived.glob(f'*.{Extension.SNAPSHOT}'))) == 1

    def test_a_folder_already_holding_backups_keeps_them(self, tmp_path):
        """Choosing a folder used before merges into it rather than emptying
        it."""
        source, destination = tmp_path / 'from', tmp_path / 'to'
        self.populate(source)
        kept = (
            destination
            / ARCHIVED_DIR_NAME
            / 'deleted-event'
            / f'20260101-120000-000000__5.0.0__auto.{Extension.SNAPSHOT}'
        )
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_bytes(b'older backup')

        assert move_snapshots_root(source, destination)

        assert kept.is_file()
        assert len(list(kept.parent.glob(f'*.{Extension.SNAPSHOT}'))) == 2

    def test_the_backups_cross_to_another_disk(self, tmp_path, monkeypatch):
        """The folder chosen is usually on another disk — a memory stick, a
        network share — which a rename cannot reach."""
        import os

        source, destination = tmp_path / 'from', tmp_path / 'to'
        files = self.populate(source)

        def no_rename(*args, **kwargs):
            raise OSError(EXDEV, 'Invalid cross-device link')

        monkeypatch.setattr(os, 'rename', no_rename)

        assert move_snapshots_root(source, destination)

        moved = list(destination.glob(f'**/*.{Extension.SNAPSHOT}'))
        assert self.relative(destination, moved) == self.relative(source, files)


@pytest.mark.unit
class TestLeftoverTemporaryFiles:
    """The retention runs on its own thread, so it meets the temporary file of
    a snapshot being written at that moment. By name it cannot be told from a
    leftover, and removing it makes the snapshot fail as it is renamed."""

    EVENT_ID = 'test-snapshots-leftovers'

    @pytest.fixture
    def directory(self):
        TestUtils.create_event(self.EVENT_ID)
        directory = snapshots_dir(self.EVENT_ID)
        directory.mkdir(parents=True, exist_ok=True)
        yield directory

    @staticmethod
    def temporary_file(directory: Path, age: timedelta) -> Path:
        file = directory / f'.tmp-{age.total_seconds():.0f}.{Extension.SNAPSHOT}'
        file.write_bytes(b'half a snapshot')
        written_at = (datetime.now() - age).timestamp()
        os.utime(file, (written_at, written_at))
        return file

    def test_a_temporary_file_being_written_is_left_alone(self, directory):
        in_flight = self.temporary_file(directory, timedelta(seconds=1))

        SnapshotRetention.sweep()

        assert in_flight.is_file(), 'the snapshot being written was interrupted'

    def test_a_temporary_file_left_behind_is_removed(self, directory):
        leftover = self.temporary_file(directory, timedelta(days=2))

        SnapshotRetention.sweep()

        assert not leftover.exists()

    def test_a_snapshot_survives_a_sweep_running_beside_it(self, directory):
        """The failure seen on the build machine: the sweep removed the
        temporary file between `VACUUM INTO` and the rename."""
        sweeps = [Thread(target=SnapshotRetention.sweep) for _ in range(4)]
        for sweep in sweeps:
            sweep.start()
        try:
            snapshot = write_snapshot(self.EVENT_ID, SnapshotReason.BEFORE_PAIRING)
        finally:
            for sweep in sweeps:
                sweep.join()

        assert snapshot.file.is_file()


@pytest.mark.unit
class TestRetentionTiers:
    def test_automatic_snapshots_are_given_up_before_a_pairing(self):
        """Entering fifty results after pairing a round gives up the older
        result snapshots, never the pairing."""
        paired = fake_snapshot(60, SnapshotReason.BEFORE_PAIRING)
        autos = [fake_snapshot(50 - index, SnapshotReason.AUTO) for index in range(50)]
        pruned = pruned_names([paired] + autos, keep_auto=10)
        assert paired.file.name not in pruned
        # The ten most recent automatic snapshots are kept, plus the most
        # recent snapshot of the event, which is never given up.
        assert len(pruned) == 39
        assert autos[0].file.name in pruned

    def test_a_step_that_did_not_happen_gives_up_nothing(self):
        """A step is snapshotted before it is known to be possible, so its
        snapshot must not stand for the automatic ones that came before: a
        pairing the engine refuses would otherwise take an hour of result
        snapshots with it."""
        paired = fake_snapshot(60, SnapshotReason.BEFORE_PAIRING)
        recent = [fake_snapshot(index, SnapshotReason.AUTO) for index in (1, 2, 3)]
        older = [fake_snapshot(120 + index, SnapshotReason.AUTO) for index in range(5)]

        pruned = pruned_names([paired] + recent + older, keep_auto=10)

        assert pruned == set()

    def test_a_restoration_and_an_upgrade_are_never_given_up_by_the_count(self):
        before_restore = fake_snapshot(500, SnapshotReason.BEFORE_RESTORE)
        before_upgrade = fake_snapshot(600, SnapshotReason.BEFORE_UPGRADE)
        milestones = [
            fake_snapshot(index, SnapshotReason.BEFORE_UNPAIRING)
            for index in range(1, 30)
        ]
        pruned = pruned_names(
            [before_restore, before_upgrade] + milestones, keep_milestones=5
        )
        assert before_restore.file.name not in pruned
        assert before_upgrade.file.name not in pruned
        assert len(pruned) == 23

    def test_the_most_recent_snapshot_is_never_given_up(self):
        """Whatever the settings say, the snapshot that would be restored
        stays."""
        lonely = [fake_snapshot(100000, SnapshotReason.AUTO)]
        assert (
            pruned_names(
                lonely, keep_milestones=0, keep_auto=0, max_age=timedelta(days=1)
            )
            == set()
        )

    def test_an_event_left_alone_keeps_its_last_steps(self):
        old_autos = [
            fake_snapshot(60 * 24 * 200 + index, SnapshotReason.AUTO)
            for index in range(4)
        ]
        old_milestone = fake_snapshot(60 * 24 * 200, SnapshotReason.BEFORE_PAIRING)
        recent = fake_snapshot(1, SnapshotReason.AUTO)
        snapshots = old_autos + [old_milestone, recent]
        pruned = pruned_names(snapshots, max_age=timedelta(days=90))
        assert all(snapshot.file.name in pruned for snapshot in old_autos)
        assert old_milestone.file.name not in pruned


@pytest.mark.unit
class TestChangesDriveTheSnapshots:
    EVENT_ID = 'test-snapshots-trigger'

    @pytest.fixture
    def event(self, monkeypatch):
        # The debounce is what a burst of changes is collapsed by; shortened so
        # the test does not wait on the real one.
        monkeypatch.setattr('data.snapshot_worker.IDLE_SECONDS', 0.2)
        monkeypatch.setattr('data.snapshot_worker.MAX_LATENCY_SECONDS', 60.0)
        TestUtils.create_event(self.EVENT_ID)
        # Creating the event writes to it, which asks for a snapshot of its
        # own: the worker is stopped, which cancels what is pending and waits
        # for what is running, before the directory is emptied.
        SnapshotScheduler.stop()
        for file in snapshots_dir(self.EVENT_ID).glob('*'):
            file.unlink()
        SnapshotScheduler.start()
        yield self.EVENT_ID
        SnapshotScheduler.stop()

    @staticmethod
    def settle():
        from time import sleep

        sleep(1.0)

    def count(self) -> int:
        return len(SnapshotLoader.snapshots(self.EVENT_ID))

    def rename_event(self, name: str):
        with EventDatabase(self.EVENT_ID, write=True) as database:
            database.execute('UPDATE `info` SET `name` = ?', (name,))

    def test_reading_an_event_asks_for_nothing(self, event):
        with EventDatabase(event) as database:
            database.load_stored_event_metadata()
        self.settle()
        assert self.count() == 0

    def test_opening_for_writing_without_changing_anything_asks_for_nothing(
        self, event
    ):
        """An event opened for writing and left untouched is not worth a copy:
        the changes of the connection are counted, not the intent."""
        with EventDatabase(event, write=True) as database:
            database.load_stored_event_metadata()
        self.settle()
        assert self.count() == 0

    def test_a_committed_change_is_snapshotted(self, event):
        self.rename_event('Changed once')
        self.settle()
        assert self.count() == 1

    def test_a_burst_of_changes_becomes_a_single_snapshot(self, event):
        from time import sleep

        for index in range(10):
            self.rename_event(f'Change {index}')
            sleep(0.02)
        self.settle()
        assert self.count() == 1

    def test_changing_a_copy_of_the_event_asks_for_nothing(self, event, tmp_path):
        """The uploads and the exports work on a copy in a temporary
        directory, which is not the event and has no snapshots."""
        import shutil

        copy = tmp_path / f'{event}.sce'
        shutil.copy(EventDatabase.event_database_path(event), copy)
        with EventDatabase(file_path=copy, write=True) as database:
            database.execute('UPDATE `info` SET `name` = ?', ('Changed in a copy',))
        self.settle()
        assert self.count() == 0

    def test_a_step_of_the_event_is_snapshotted_before_it_happens(self, event):
        SnapshotScheduler.snapshot_before(event, SnapshotReason.BEFORE_PAIRING)
        snapshots = SnapshotLoader.snapshots(event)
        assert len(snapshots) == 1
        assert snapshots[0].reason == SnapshotReason.BEFORE_PAIRING


@pytest.mark.unit
class TestSnapshotContent:
    """What a snapshot holds is read from the snapshot itself, so that the
    listing shows what restoring it would give back."""

    EVENT_ID = 'test-snapshots-content'

    @pytest.fixture
    def event(self):
        TestUtils.create_event(self.EVENT_ID)
        TestUtils.create_tournament(self.EVENT_ID, 'Main', overrides={'rounds': 5})
        TestUtils.create_tournament(self.EVENT_ID, 'Junior', overrides={'rounds': 4})
        yield self.EVENT_ID

    def test_every_tournament_of_the_event_is_listed(self, event):
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)

        tournaments = snapshot.tournaments

        assert tournaments is not None
        assert [tournament.name for tournament in tournaments] == ['Junior', 'Main']
        assert [tournament.rounds for tournament in tournaments] == [4, 5]

    def test_a_tournament_that_has_not_started_says_so(self, event):
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)

        tournaments = snapshot.tournaments

        assert tournaments is not None
        assert all(
            tournament.current_round is None and not tournament.has_results
            for tournament in tournaments
        )

    def test_the_content_is_read_from_the_snapshot_not_from_the_event(self, event):
        """The event moving on does not change what a snapshot holds."""
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        before = snapshot.tournaments
        assert before is not None

        with EventDatabase(event, write=True) as database:
            stored_tournament = next(
                stored
                for stored in database.load_stored_tournaments()
                if stored.name == 'Main'
            )
            assert stored_tournament.id is not None
            database.set_tournament_current_round(stored_tournament.id, 3)

        assert snapshot.tournaments == before
        later = write_snapshot(event, SnapshotReason.AUTO).tournaments
        assert later is not None
        assert next(t for t in later if t.name == 'Main').current_round == 3

    def test_a_paired_round_is_reported_even_when_no_round_was_set_by_hand(self, event):
        """`tournament.current_round` is null until the arbiter sets it, and
        the pairing system fills it in from the pairings: the state has to be
        asked of the event, or a tournament in its first round reads as not
        started."""
        with EventDatabase(event, write=True) as database:
            stored_tournament = next(
                stored
                for stored in database.load_stored_tournaments()
                if stored.name == 'Main'
            )
            assert stored_tournament.id is not None
            assert stored_tournament.current_round is None
            tournament_id = stored_tournament.id
            player_ids = [
                database.add_stored_player(
                    StoredPlayer(
                        id=None,
                        last_name=f'PLAYER{index}',
                        first_name='Test',
                        ratings={1: {'standard': 2000}},
                    )
                )
                for index in range(2)
            ]
            for player_id in player_ids:
                database.add_stored_tournament_player(
                    StoredTournamentPlayer(
                        tournament_id=tournament_id, player_id=player_id
                    )
                )
            board_id = database.add_stored_board(
                StoredBoard(
                    id=None,
                    white_player_id=player_ids[0],
                    black_player_id=player_ids[1],
                    index=1,
                )
            )
            for player_id, opponent_id in (
                (player_ids[0], player_ids[1]),
                (player_ids[1], player_ids[0]),
            ):
                database.add_stored_pairing(
                    StoredPairing(
                        tournament_id=tournament_id,
                        player_id=player_id,
                        round_=1,
                        result=Result.NO_RESULT,
                        board_id=board_id,
                    )
                )
                assert opponent_id

        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)

        tournaments = snapshot.tournaments
        assert tournaments is not None
        main = next(t for t in tournaments if t.name == 'Main')
        assert main.current_round == 1
        assert (main.results, main.boards) == (0, 1)

    def test_the_label_names_the_tournament_the_step_was_about(self, event):
        """A round on its own says nothing in an event holding several
        tournaments, and the name is the one it had in that snapshot."""
        with EventDatabase(event) as database:
            stored_tournament = next(
                stored
                for stored in database.load_stored_tournaments()
                if stored.name == 'Main'
            )
        assert stored_tournament.id is not None

        snapshot = write_snapshot(
            event,
            SnapshotReason.BEFORE_PAIRING,
            round_=3,
            tournament_id=stored_tournament.id,
        )

        assert snapshot.reason_round == 3
        assert snapshot.reason_tournament == 'Main'
        assert snapshot.label == 'Before round 3 of [Main] was paired'

    def test_a_step_about_a_whole_tournament_names_it_without_a_round(self, event):
        with EventDatabase(event) as database:
            stored_tournament = next(
                stored
                for stored in database.load_stored_tournaments()
                if stored.name == 'Junior'
            )
        assert stored_tournament.id is not None

        snapshot = write_snapshot(
            event,
            SnapshotReason.BEFORE_UNPAIRING,
            tournament_id=stored_tournament.id,
        )

        assert snapshot.reason_round is None
        assert snapshot.label == 'Before [Junior] was unpaired'

    def test_distributing_the_players_names_no_tournament(self, event):
        """The players move between the tournaments, so the step belongs to
        none of them."""
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PLAYERS_DISTRIBUTION)

        assert snapshot.reason_tournament is None
        assert snapshot.reason_round is None
        assert snapshot.label == 'Before players were distributed'
        assert snapshot.is_milestone

    def test_a_tournament_the_snapshot_does_not_hold_is_not_named(self, event):
        snapshot = write_snapshot(
            event, SnapshotReason.BEFORE_PAIRING, round_=2, tournament_id=9999
        )

        assert snapshot.reason_tournament is None
        assert snapshot.label == 'Before round 2 was paired'

    def test_a_snapshot_that_cannot_be_read_reports_no_state(self, event, tmp_path):
        unreadable = (
            tmp_path / f'20260910-120000-000000__5.0.0__auto.{Extension.SNAPSHOT}'
        )
        unreadable.write_bytes(b'not a database at all')
        snapshot = Snapshot.from_file(unreadable, event)
        assert snapshot is not None

        assert snapshot.tournaments is None


@pytest.mark.unit
class TestTheCopyStaysOffTheEventLoop:
    """A step of the event is snapshotted before it happens, from a request
    handler, so the copy must not run on the loop: it would stop every other
    request, screen and websocket for as long as it takes.

    Driven through a loop of its own on a thread of its own rather than as an
    async test: the end-to-end tests leave a loop of session scope running, and
    starting a second runner inside a running loop raises.
    """

    EVENT_ID = 'test-snapshots-off-loop'

    @pytest.fixture
    def event(self):
        TestUtils.create_event(self.EVENT_ID)
        yield self.EVENT_ID

    @staticmethod
    def slow_write(recorded: list[int], seconds: float):
        """Stands in for the copy, recording the thread it ran on."""

        def write(uniq_id, reason, round_=None, tournament_id=None):
            recorded.append(get_ident())
            sleep(seconds)
            return fake_snapshot(0, reason, uniq_id)

        return write

    @staticmethod
    def run_in_its_own_loop(main) -> dict:
        outcome: dict = {}

        def run():
            async def wrapped():
                outcome['loop_thread'] = get_ident()
                return await main()

            outcome['result'] = asyncio.run(wrapped())

        thread = Thread(target=run)
        thread.start()
        thread.join()
        return outcome

    def test_the_copy_runs_on_another_thread(self, event, monkeypatch):
        recorded: list[int] = []
        monkeypatch.setattr(
            'data.snapshot_worker.write_snapshot', self.slow_write(recorded, 0)
        )

        outcome = self.run_in_its_own_loop(
            lambda: SnapshotScheduler.snapshot_before_async(
                event, SnapshotReason.BEFORE_PAIRING
            )
        )

        assert recorded, 'the copy did not run'
        assert recorded[0] != outcome['loop_thread']

    def test_the_loop_keeps_running_while_the_copy_is_written(self, event, monkeypatch):
        recorded: list[int] = []
        monkeypatch.setattr(
            'data.snapshot_worker.write_snapshot', self.slow_write(recorded, 0.3)
        )

        async def snapshot_while_ticking() -> int:
            ticks = 0

            async def tick():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.01)
                    ticks += 1

            ticker = asyncio.ensure_future(tick())
            try:
                await SnapshotScheduler.snapshot_before_async(
                    event, SnapshotReason.BEFORE_PAIRING
                )
            finally:
                ticker.cancel()
            return ticks

        outcome = self.run_in_its_own_loop(snapshot_while_ticking)

        # On the loop, the 0.3 s copy would have starved the ticker entirely.
        assert outcome['result'] > 5, (
            f'the loop was blocked ({outcome["result"]} ticks)'
        )


@pytest.mark.unit
class TestTurningTheBackupsOff:
    EVENT_ID = 'test-snapshots-turned-off'

    def test_what_failed_is_forgotten(self, monkeypatch, tmp_path):
        """Turning the backups off must not leave a warning behind about a
        backup nobody is waiting for any more."""
        TestUtils.create_event(self.EVENT_ID)
        monkeypatch.setattr(
            SharlyChessConfig().stored_config, 'snapshot_dir', str(tmp_path / 'gone')
        )
        monkeypatch.setattr(
            'data.snapshot.write_snapshot',
            lambda *args, **kwargs: (_ for _ in ()).throw(
                SnapshotException('nowhere to write', SnapshotFailure.PERSISTENT)
            ),
        )
        monkeypatch.setattr(
            'data.snapshot_worker.write_snapshot',
            lambda *args, **kwargs: (_ for _ in ()).throw(
                SnapshotException('nowhere to write', SnapshotFailure.PERSISTENT)
            ),
        )
        with pytest.raises(SnapshotException):
            SnapshotScheduler.snapshot_now(self.EVENT_ID, SnapshotReason.AUTO)
        assert SnapshotScheduler.status(self.EVENT_ID).is_failing

        SnapshotScheduler.forget_statuses()

        assert not SnapshotScheduler.status(self.EVENT_ID).is_failing

    def test_nothing_is_backed_up_while_they_are_off(self, monkeypatch):
        """The switch is what the whole feature hangs off: a change committed
        while it is off asks for nothing."""
        monkeypatch.setattr('data.snapshot_worker.IDLE_SECONDS', 0.2)
        monkeypatch.setattr('data.snapshot_worker.MAX_LATENCY_SECONDS', 60.0)
        TestUtils.create_event(self.EVENT_ID)
        SnapshotScheduler.stop()
        for file in snapshots_dir(self.EVENT_ID).glob('*'):
            file.unlink()
        SnapshotScheduler.start()
        monkeypatch.setattr(
            SharlyChessConfig().stored_config, 'snapshot_enabled', False
        )
        try:
            with EventDatabase(self.EVENT_ID, write=True) as database:
                database.execute(
                    'UPDATE `info` SET `name` = ?', ('Changed with the switch off',)
                )
            sleep(1.0)

            assert not SnapshotLoader.snapshots(self.EVENT_ID)
        finally:
            SnapshotScheduler.stop()


@pytest.mark.unit
class TestRestore:
    EVENT_ID = 'test-snapshots-restore'

    @pytest.fixture
    def event(self):
        TestUtils.create_event(self.EVENT_ID)
        for file in snapshots_dir(self.EVENT_ID).glob('*'):
            file.unlink()
        yield self.EVENT_ID

    def event_name(self, uniq_id: str) -> str:
        with EventDatabase(uniq_id) as database:
            return database.load_stored_event_metadata().name

    def rename_event(self, uniq_id: str, name: str):
        with EventDatabase(uniq_id, write=True) as database:
            database.execute('UPDATE `info` SET `name` = ?', (name,))

    def test_restoring_in_place_keeps_the_uniq_id(self, event):
        """The screens, the input pages and the plugin configurations all point
        at the uniq_id, so a rollback keeps it."""
        self.rename_event(event, 'The state to come back to')
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self.rename_event(event, 'The mistake')

        snapshot.restore_in_place()

        assert self.event_name(event) == 'The state to come back to'
        assert EventDatabase.event_database_path(event).is_file()

    def test_restoring_is_itself_undoable(self, event):
        """The state being replaced is snapshotted first, which is what makes a
        restoration reversible."""
        self.rename_event(event, 'Before')
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self.rename_event(event, 'After')

        replaced = snapshot.restore_in_place()

        assert replaced is not None
        assert replaced.reason == SnapshotReason.BEFORE_RESTORE
        replaced.restore_in_place()
        assert self.event_name(event) == 'After'

    def test_restoring_as_a_copy_leaves_the_event_alone(self, event):
        self.rename_event(event, 'A past state')
        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self.rename_event(event, 'The state now')

        copy_uniq_id = snapshot.restore_as_copy()

        assert copy_uniq_id != event
        assert self.event_name(copy_uniq_id) == 'A past state'
        assert self.event_name(event) == 'The state now'

    def test_a_snapshot_from_a_later_version_is_refused(self, event):
        import shutil

        snapshot = write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        later_file = snapshot.file.parent / snapshot.file.name.replace(
            f'{snapshot.version}', '99.0.0'
        )
        shutil.copy(snapshot.file, later_file)
        later = Snapshot.from_file(later_file, event)
        assert later is not None

        with pytest.raises(RestoreException):
            later.restore_in_place()

    def test_a_write_from_another_thread_during_the_swap_is_refused(self, event):
        """Restoring replaces the database file, so a write that ran while it
        happened would land in the file on its way out."""
        from threading import Thread

        refused: list[bool] = []

        def write_from_another_thread():
            try:
                with EventDatabase(event, write=True) as database:
                    database.execute('UPDATE `info` SET `name` = ?', ('Lost',))
                refused.append(False)
            except SharlyChessException:
                refused.append(True)

        with _restoring_event(event):
            assert is_being_restored(event)
            thread = Thread(target=write_from_another_thread)
            thread.start()
            thread.join()
            with EventDatabase(event) as database:
                assert database.load_stored_event_metadata().name
        assert refused == [True]
        assert not is_being_restored(event)

    def test_the_restoring_thread_keeps_its_own_access(self, event):
        """It has to migrate the event it has just put in place, and a
        migration opens it for writing."""
        with _restoring_event(event):
            with EventDatabase(event, write=True) as database:
                database.execute('UPDATE `info` SET `name` = ?', ('Migrated',))

        with EventDatabase(event) as database:
            assert database.load_stored_event_metadata().name == 'Migrated'


@pytest.mark.unit
class TestADamagedEventIsListedNotRaised:
    """A page carrying the uniq_id of a damaged event must answer, not fail:
    the way back to its backups is on those pages."""

    INTACT_HEADER_ID = 'test-snapshots-half-corrupt'
    NOT_A_DATABASE_ID = 'test-snapshots-not-a-database'

    def test_a_file_that_is_not_a_database_is_reported_as_corrupted(self):
        TestUtils.create_event(self.NOT_A_DATABASE_ID)
        EventDatabase.event_database_path(self.NOT_A_DATABASE_ID).write_bytes(
            b'not a database any more'
        )
        EventLoader.unload_event(self.NOT_A_DATABASE_ID)

        with pytest.raises(DatabaseCorruptedException):
            EventLoader.check_event_database(self.NOT_A_DATABASE_ID)
        assert self.NOT_A_DATABASE_ID in EventLoader.damaged_event_ids()

    def test_a_file_whose_header_survives_is_reported_as_corrupted_too(self):
        """SQLite only complains about a page when that page is read, so a
        file with a sound header and sound metadata still raises later —
        'database disk image is malformed' — and that has to be caught
        wherever the file is read, not only where its status is checked."""
        TestUtils.create_event(self.INTACT_HEADER_ID)
        file = EventDatabase.event_database_path(self.INTACT_HEADER_ID)
        content = bytearray(file.read_bytes())
        # One page, past the ones the status is read from, so that the file
        # passes every check and only fails when its rows are read.
        for offset in range(8192, min(len(content), 12288)):
            content[offset] = (content[offset] + 137) % 256
        file.write_bytes(bytes(content))
        EventLoader.unload_event(self.INTACT_HEADER_ID)

        assert content[:15] == bytearray(b'SQLite format 3'), 'the header was lost'
        with pytest.raises(DatabaseCorruptedException):
            EventLoader.check_event_database(self.INTACT_HEADER_ID)
        assert self.INTACT_HEADER_ID in EventLoader.damaged_event_ids()

    def test_listing_the_events_survives_a_damaged_one(self):
        """`inaccessible_events_metadata` is reached from every admin page."""
        TestUtils.create_event(self.NOT_A_DATABASE_ID)
        EventDatabase.event_database_path(self.NOT_A_DATABASE_ID).write_bytes(
            b'not a database any more'
        )
        EventLoader.unload_event(self.NOT_A_DATABASE_ID)

        listed = EventLoader.inaccessible_events_metadata()

        assert self.NOT_A_DATABASE_ID in {metadata.uniq_id for metadata in listed}
        assert all(not metadata.accessible for metadata in listed)


@pytest.mark.unit
class TestArchiveLifecycle:
    EVENT_ID = 'test-snapshots-archive'

    def test_snapshots_follow_the_event_through_the_archive(self):
        """Deleting an event archives it and it can be brought back, so its
        snapshots are set aside rather than given up."""
        TestUtils.create_event(self.EVENT_ID)
        write_snapshot(self.EVENT_ID, SnapshotReason.BEFORE_PAIRING)
        snapshot_count = len(SnapshotLoader.snapshots(self.EVENT_ID))
        assert snapshot_count

        with EventDatabase(self.EVENT_ID, write=True) as database:
            archive_file = database.delete()
        archive_stem = archive_file.stem

        assert not snapshots_dir(self.EVENT_ID).is_dir()
        assert len(list(archived_snapshots_dir(archive_stem).glob('*.scs'))) == (
            snapshot_count
        )

        archive = ArchiveLoader.get_archive(archive_stem)
        assert archive is not None
        restored_uniq_id = archive.restore()
        assert restored_uniq_id is not None

        assert len(SnapshotLoader.snapshots(restored_uniq_id)) == snapshot_count
        assert not archived_snapshots_dir(archive_stem).is_dir()

    def test_snapshots_follow_a_renamed_event(self):
        uniq_id = 'test-snapshots-rename'
        renamed = 'test-snapshots-renamed'
        TestUtils.create_event(uniq_id)
        write_snapshot(uniq_id, SnapshotReason.BEFORE_PAIRING)
        snapshot_count = len(SnapshotLoader.snapshots(uniq_id))

        with EventDatabase(uniq_id, write=True) as database:
            database.rename(renamed)

        assert len(SnapshotLoader.snapshots(renamed)) == snapshot_count
        assert not snapshots_dir(uniq_id).is_dir()
        EventLoader.unload_event(renamed)
