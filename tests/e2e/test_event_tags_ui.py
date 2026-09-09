import pytest
from playwright.sync_api import Page, expect, APIRequestContext
from tests.test_config import TestUtils


EVENT_ID = 'test-event-tags-e2e'
OTHER_EVENT_ID = 'test-event-untagged-e2e'
TAG_NAME = 'Youth e2e'
SECOND_TAG_NAME = 'Blitz e2e'


@pytest.mark.e2e
class TestEventTags:
    def _open_event_config_modal(self, page: Page, event_uniq_id: str):
        page.goto(f'/event/{event_uniq_id}')
        page.get_by_test_id('nav-admin-event-config-tab-tab').click()
        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        # .modal-dialog is a Bootstrap placeholder until htmx swaps the real
        # form in; wait for the stored location so a fill can't be overwritten.
        expect(modal.get_by_test_id('location')).to_have_value('Paris')
        return modal

    def _open_tags_modal(self, page: Page, event_uniq_id: str):
        modal = self._open_event_config_modal(page, event_uniq_id)
        modal.locator('#tags-configure-button').click()
        expect(page.locator('#event-tags-modal')).to_be_visible()

    @staticmethod
    def _delete_all_tags(page: Page):
        """Empty the registry from the manager, and return the row locator."""
        rows = page.locator('#event-tags-modal .tag-row')
        while count := rows.count():
            rows.first.locator('button:has(.bi-trash-fill)').click()
            expect(rows).to_have_count(count - 1)
        return rows

    @staticmethod
    def _drag_row(page: Page, source, target):
        """Drag *source* onto *target*. Sortable.js tracks the pointer, so
        the move is played out in steps rather than jumped in one go."""
        source.hover()
        page.mouse.down()
        target_box = target.bounding_box()
        assert target_box is not None
        for ratio in (0.4, 0.7, 1.0):
            page.mouse.move(
                target_box['x'] + target_box['width'] / 2,
                target_box['y'] + target_box['height'] * (1 - ratio) / 2,
                steps=5,
            )
        page.mouse.up()

    def _create_tag(self, page: Page, name: str, color: str, add_another=False):
        page.locator('.modal-footer').get_by_role('button', name='Add').click()
        expect(page.get_by_test_id('tag-name')).to_be_visible()
        page.get_by_test_id('tag-name').fill(name)
        page.get_by_test_id('tag-color').fill(color)
        if add_another:
            page.locator('.dropdown-toggle-split').click()
            page.get_by_role('button', name='Create and add another').click()
            # Stays on an empty form rather than returning to the list.
            expect(page.get_by_test_id('tag-name')).to_have_value('')
        else:
            page.get_by_test_id('create-button').click()
            expect(page.locator('#event-tags-modal')).to_contain_text(name)

    def test_tag_an_event_then_filter_the_event_list(
        self, page: Page, api_request_context: APIRequestContext
    ):
        TestUtils.create_event(EVENT_ID, via_api_request_context=api_request_context)
        TestUtils.create_event(
            OTHER_EVENT_ID, via_api_request_context=api_request_context
        )

        # Tags are created in their own modal and land in the global registry;
        # one created from an event is selected on it.
        self._open_tags_modal(page, EVENT_ID)
        self._create_tag(page, TAG_NAME, '#123456')

        # Back restores the event modal with the tag selected.
        page.get_by_role('button', name='Back').click()
        expect(page.locator('#tags-main-container')).to_be_visible()
        # Wait for the tag to be the select's live value — that, not a rendered
        # [selected] attribute, is what the form submits, so guard on it before
        # saving or the tag can be dropped from the save.
        page.wait_for_function(
            '(name) => [...document.querySelector("#tags").selectedOptions]'
            '.some((option) => option.textContent.trim() === name)',
            arg=TAG_NAME,
        )

        page.get_by_test_id('event-form-submit-button').click()
        expect(page).to_have_url(f'/event/{EVENT_ID}/tournaments')

        # The tag survives the save and shows on the event list...
        page.goto('/current_events')
        item = page.get_by_test_id('events-item').filter(has_text=EVENT_ID)
        expect(item).to_contain_text(TAG_NAME)

        # ...and filtering on it hides the untagged event.
        page.locator('.events-tag-filter button', has_text=TAG_NAME).first.click()
        expect(
            page.get_by_test_id('events-item').filter(has_text=EVENT_ID)
        ).to_be_visible()
        expect(
            page.get_by_test_id('events-item').filter(has_text=OTHER_EVENT_ID)
        ).not_to_be_attached()

        # Clearing the filter brings the untagged event back.
        page.get_by_test_id('events-tag-filter-clear').click()
        expect(
            page.get_by_test_id('events-item').filter(has_text=OTHER_EVENT_ID)
        ).to_be_visible()

    def test_unsaved_event_edits_survive_the_tags_modal(
        self, page: Page, api_request_context: APIRequestContext
    ):
        """The tag manager is a separate modal, so the event form it was
        opened from is carried through and restored by Back."""
        modal = self._open_event_config_modal(page, EVENT_ID)
        TestUtils.fill_and_confirm(modal.get_by_test_id('location'), 'Unsaved Location')
        modal.locator('#tags-configure-button').click()
        expect(page.locator('#event-tags-modal')).to_be_visible()
        page.get_by_role('button', name='Back').click()
        expect(page.locator('#tags-main-container')).to_be_visible()
        expect(page.get_by_test_id('location')).to_have_value('Unsaved Location')

    def test_create_and_add_another_keeps_the_form_open(
        self, page: Page, api_request_context: APIRequestContext
    ):
        self._open_tags_modal(page, EVENT_ID)
        self._create_tag(page, SECOND_TAG_NAME, '#f2c94c', add_another=True)
        # The form stays open, empty, ready for the next tag.
        expect(page.get_by_test_id('tag-name')).to_have_value('')
        # ...and the split button remembers the choice.
        expect(page.get_by_test_id('add_other-button')).to_be_visible()

    def test_new_tags_go_last_and_can_be_dragged(
        self, page: Page, api_request_context: APIRequestContext
    ):
        """Tags are arranged by hand rather than sorted, so a new one lands
        at the end of the registry and dragging it moves it for good."""
        self._open_tags_modal(page, EVENT_ID)
        rows = page.locator('#event-tags-modal .tag-row')
        names = page.locator('#event-tags-modal .tag-row .badge')
        assert names.all_inner_texts() == [TAG_NAME, SECOND_TAG_NAME]

        self._drag_row(page, rows.nth(1), rows.nth(0))
        expect(rows).to_have_count(2)
        assert names.all_inner_texts() == [SECOND_TAG_NAME, TAG_NAME]

        # The order is the registry's, so it holds outside this modal.
        page.goto('/current_events')
        # Each filter badge reads "<name>\n(<count>)".
        filtered = page.locator('.events-tag-filter .badge').all_inner_texts()
        assert [name.split('\n')[0] for name in filtered] == [SECOND_TAG_NAME, TAG_NAME]

    def test_the_tag_filter_opens_the_manager(
        self, page: Page, api_request_context: APIRequestContext
    ):
        """The event lists reach the registry without going through an
        event, and closing comes back to the list."""
        page.goto('/current_events')
        page.get_by_test_id('events-tag-filter-manage').click()
        expect(page.locator('#event-tags-modal')).to_be_visible()
        # No event to go back to: the modal closes onto the list instead.
        expect(page.get_by_role('button', name='Back')).not_to_be_attached()
        page.get_by_role('button', name='Close').click()
        expect(page.locator('.events-tag-filter')).to_be_visible()
        expect(page.locator('#event-tags-modal')).not_to_be_attached()

    def test_deleting_a_tag_removes_it_from_the_events(
        self, page: Page, api_request_context: APIRequestContext
    ):
        self._open_tags_modal(page, EVENT_ID)
        tag_row = page.locator('#event-tags-modal .border').filter(has_text=TAG_NAME)
        tag_row.locator('button:has(.bi-trash-fill)').click()
        expect(page.locator('#event-tags-modal')).not_to_contain_text(TAG_NAME)

        # A delete carries the event form on, so Back still returns.
        page.get_by_role('button', name='Back').click()
        expect(page.locator('#tags-main-container')).to_be_visible()

        page.goto('/current_events')
        item = page.get_by_test_id('events-item').filter(has_text=EVENT_ID)
        expect(item).not_to_contain_text(TAG_NAME)

    def test_an_empty_registry_proposes_ready_made_sets(
        self, page: Page, api_request_context: APIRequestContext
    ):
        """With nothing defined, the manager offers sets to start from
        rather than just saying the registry is empty."""
        self._open_tags_modal(page, EVENT_ID)
        rows = self._delete_all_tags(page)

        add_button = page.get_by_role('button', name='Add the selected sets')
        expect(add_button).to_be_disabled()
        sets = page.locator('#event-tags-modal .tag-set-row')
        expect(sets).to_have_count(3)
        sets.filter(has_text='Time control').locator('input').check()
        expect(add_button).to_be_enabled()
        add_button.click()

        # The set lands whole, in the order it is proposed in.
        expect(rows).to_have_count(3)
        names = page.locator('#event-tags-modal .tag-row .badge')
        assert names.all_inner_texts() == ['Standard', 'Rapid', 'Blitz']

        # The registry is shared by the whole session: leave it as found.
        self._delete_all_tags(page)
