"""The snapshots of an event, from the list of events.

Covers what the unit tests cannot: the panel, the confirmation the restoration
asks for, and the way back offered on an event whose file cannot be read.
"""

import os

import pytest
from playwright.sync_api import Page, expect

from common import EVENTS_DIR
from data.loader import ArchiveLoader
from data.snapshot import SnapshotReason, snapshots_dir, write_snapshot
from database.sqlite.event.event_database import EventDatabase
from tests.test_config import TestUtils
from utils.enum import Extension

EVENT_ID = 'test-snapshots-e2e'
DAMAGED_EVENT_ID = 'test-snapshots-damaged-e2e'


@pytest.mark.e2e
class TestSnapshotsPanel:
    @staticmethod
    def _event_name(uniq_id: str) -> str:
        with EventDatabase(uniq_id) as database:
            return database.load_stored_event_metadata().name

    @staticmethod
    def _set_event_name(uniq_id: str, name: str):
        with EventDatabase(uniq_id, write=True) as database:
            database.execute('UPDATE `info` SET `name` = ?', (name,))

    @staticmethod
    def _open_panel(page: Page, uniq_id: str):
        page.goto('/current_events')
        # Addressed by the button's own URL: the row shows the name of the
        # event, which these tests change to tell the states apart.
        button = page.locator(
            f'button[hx-get*="event-snapshots-modal/{uniq_id}"]'
        ).first
        expect(button).to_be_visible()
        button.click()
        modal = page.locator('#event-snapshots-modal')
        expect(modal).to_be_visible()
        return modal

    @pytest.fixture
    def event(self):
        TestUtils.create_event(EVENT_ID)
        for file in snapshots_dir(EVENT_ID).glob('*'):
            file.unlink()
        yield EVENT_ID

    def test_the_panel_lists_the_snapshots_with_their_reason(self, page: Page, event):
        write_snapshot(event, SnapshotReason.BEFORE_PAIRING, round_=3)
        write_snapshot(event, SnapshotReason.AUTO)

        modal = self._open_panel(page, event)

        expect(modal.locator('tbody tr')).to_have_count(2)
        expect(modal).to_contain_text('Before round 3 was paired')
        expect(modal).to_contain_text('Automatic')

    def test_an_event_with_no_snapshot_says_so(self, page: Page, event):
        modal = self._open_panel(page, event)
        expect(modal).to_contain_text('No backup has been taken of this event yet')

    def test_snapshot_now_takes_one(self, page: Page, event):
        modal = self._open_panel(page, event)
        expect(modal.locator('tbody tr')).to_have_count(1)

        modal.get_by_role('button', name='Back up now').click()

        modal = page.locator('#event-snapshots-modal')
        expect(modal).to_be_visible()
        expect(modal.locator('tbody tr')).to_have_count(1)
        expect(modal).to_contain_text('Automatic')

    def test_restoring_in_place_asks_first_and_rolls_the_event_back(
        self, page: Page, event
    ):
        self._set_event_name(event, 'The state to come back to')
        write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self._set_event_name(event, 'The mistake')

        modal = self._open_panel(page, event)
        modal.locator('button:has(.bi-arrow-counterclockwise)').first.click()

        confirm = page.locator('#event-snapshot-restore-modal')
        expect(confirm).to_be_visible()
        expect(confirm).to_contain_text('The event will be replaced by this backup')
        confirm.locator('#snapshot-restore-button').click()

        expect(page.locator('#event-snapshot-restore-modal')).not_to_be_visible()
        assert self._event_name(event) == 'The state to come back to'

    def test_declining_the_confirmation_leaves_the_event_alone(self, page: Page, event):
        write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self._set_event_name(event, 'Left alone')

        modal = self._open_panel(page, event)
        modal.locator('button:has(.bi-arrow-counterclockwise)').first.click()

        confirm = page.locator('#event-snapshot-restore-modal')
        expect(confirm).to_be_visible()
        confirm.get_by_role('button', name='Cancel').click()

        expect(confirm).not_to_be_visible()
        assert self._event_name(event) == 'Left alone'

    def test_restoring_as_a_copy_leaves_the_event_alone(self, page: Page, event):
        self._set_event_name(event, 'A past state')
        write_snapshot(event, SnapshotReason.BEFORE_PAIRING)
        self._set_event_name(event, 'The state now')

        modal = self._open_panel(page, event)
        modal.locator('button:has(.bi-copy)').first.click()

        expect(page.locator('body')).to_contain_text(
            'has been restored as the new event'
        )
        assert self._event_name(event) == 'The state now'
        copies = [
            file.stem for file in EVENTS_DIR.glob(f'{event}-*.{Extension.EVENT_DB}')
        ]
        assert len(copies) == 1
        assert self._event_name(copies[0]) == 'A past state'


@pytest.mark.e2e
class TestSnapshotState:
    """What each snapshot holds, which is what restoring it gives back."""

    FEW_ID = 'test-snapshots-few-e2e'
    MANY_ID = 'test-snapshots-many-e2e'

    def test_a_few_tournaments_are_listed_on_the_row(self, page: Page):
        TestUtils.create_event(self.FEW_ID)
        TestUtils.create_tournament(self.FEW_ID, 'Main', overrides={'rounds': 5})
        TestUtils.create_tournament(self.FEW_ID, 'Junior', overrides={'rounds': 4})
        write_snapshot(self.FEW_ID, SnapshotReason.BEFORE_PAIRING)

        modal = TestSnapshotsPanel._open_panel(page, self.FEW_ID)

        row = modal.locator('tbody tr').first
        expect(row).to_contain_text('Main')
        expect(row).to_contain_text('Junior')
        expect(row).to_contain_text('not started')

    def test_many_tournaments_are_folded_behind_an_expander(self, page: Page):
        TestUtils.create_event(self.MANY_ID)
        for index in range(4):
            TestUtils.create_tournament(
                self.MANY_ID, f'Tournament {index}', overrides={'rounds': 3}
            )
        write_snapshot(self.MANY_ID, SnapshotReason.BEFORE_PAIRING)

        modal = TestSnapshotsPanel._open_panel(page, self.MANY_ID)

        row = modal.locator('tbody tr').first
        expect(row).to_contain_text('4 tournaments')
        detail = row.locator('.collapse')
        expect(detail).not_to_be_visible()

        row.locator('button[data-bs-toggle="collapse"]').click()

        expect(detail).to_be_visible()
        expect(detail).to_contain_text('Tournament 0')
        expect(detail).to_contain_text('Tournament 3')


@pytest.mark.e2e
class TestDamagedEventRecovery:
    def test_an_event_that_cannot_be_read_offers_its_snapshots(self, page: Page):
        """The page of a damaged event cannot be reached, so the way back is
        offered where the event is listed."""
        TestUtils.create_event(DAMAGED_EVENT_ID)
        with EventDatabase(DAMAGED_EVENT_ID, write=True) as database:
            database.execute('UPDATE `info` SET `name` = ?', ('Before the damage',))
        write_snapshot(DAMAGED_EVENT_ID, SnapshotReason.BEFORE_PAIRING)
        EventDatabase.event_database_path(DAMAGED_EVENT_ID).write_bytes(
            b'not a database any more'
        )

        page.goto('/current_events')
        button = page.locator(
            f'button[hx-get*="event-snapshots-modal/{DAMAGED_EVENT_ID}"]'
        ).first
        expect(button).to_be_visible()
        button.click()
        modal = page.locator('#event-snapshots-modal')
        expect(modal).to_be_visible()
        expect(modal).to_contain_text('This event could not be opened')

        modal.locator('button:has(.bi-arrow-counterclockwise)').first.click()
        confirm = page.locator('#event-snapshot-restore-modal')
        expect(confirm).to_be_visible()
        # Nothing can be kept of a state that cannot be read.
        expect(confirm).to_contain_text('there is nothing to keep')
        confirm.locator('#snapshot-restore-button').click()

        expect(page.locator('#event-snapshot-restore-modal')).not_to_be_visible()
        with EventDatabase(DAMAGED_EVENT_ID) as database:
            assert database.load_stored_event_metadata().name == 'Before the damage'

    def test_an_event_that_cannot_be_read_can_be_archived(self, page: Page):
        """Without this the only thing to do with a damaged event is restore
        it, leaving a row that cannot be got rid of."""
        uniq_id = 'test-snapshots-damaged-archive-e2e'
        TestUtils.create_event(uniq_id)
        EventDatabase.event_database_path(uniq_id).write_bytes(
            b'not a database any more'
        )

        page.goto('/current_events')
        item = page.get_by_test_id('events-item').filter(has_text=uniq_id)
        expect(item).to_be_visible()
        item.locator('button[hx-get*="event-damaged-delete-modal"]').first.click()

        modal = page.locator('#delete-modal')
        expect(modal).to_be_visible()
        expect(modal).to_contain_text('This event could not be read')
        modal.locator('#archive').check()
        modal.locator('#delete-button').click()

        # The message only renders when the list came back: an error page
        # would satisfy the assertions below just as well.
        expect(page.locator('body')).to_contain_text('the database has been archived')
        expect(page.get_by_test_id('events-item')).not_to_have_count(0)
        expect(
            page.get_by_test_id('events-item').filter(has_text=uniq_id)
        ).not_to_be_attached()
        assert not EventDatabase.event_database_path(uniq_id).is_file()
        assert ArchiveLoader.get_archive(uniq_id) is not None


@pytest.mark.e2e
class TestAFailingBackupIsSeen:
    """A backup fails on the worker thread, long after the request that caused
    it, so the event page has to say so by itself."""

    EVENT_ID = 'test-snapshots-failing-e2e'

    def test_the_event_page_warns_that_the_backups_stopped(self, page: Page):
        TestUtils.create_event(self.EVENT_ID)
        directory = snapshots_dir(self.EVENT_ID)
        directory.mkdir(parents=True, exist_ok=True)
        # A folder that cannot be written to: a memory stick pulled out, a
        # share gone, rights changed.
        os.chmod(directory, 0o500)
        try:
            page.goto('/current_events')
            page.locator(
                f'button[hx-get*="event-snapshots-modal/{self.EVENT_ID}"]'
            ).first.click()
            modal = page.locator('#event-snapshots-modal')
            expect(modal).to_be_visible()
            modal.get_by_role('button', name='Back up now').click()

            # The panel says so, and so does the event page from then on.
            expect(page.locator('body')).to_contain_text('failed')
            page.goto(f'/event/{self.EVENT_ID}')
            warning = page.locator('#backup-message').get_by_text(
                'This event is no longer being backed up'
            )
            expect(warning).to_have_count(1)
            # One warning, not one per page shown.
            page.goto(f'/event/{self.EVENT_ID}/tournaments')
            expect(warning).to_have_count(1)
        finally:
            os.chmod(directory, 0o700)
