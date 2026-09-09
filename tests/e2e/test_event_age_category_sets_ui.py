import pytest
from playwright.sync_api import Page, expect, APIRequestContext
from tests.test_config import TestUtils


EVENT_ID = 'test-event-category-sets-e2e'
SET_NAME = 'Veterans e2e'


@pytest.mark.e2e
class TestEventAgeCategorySets:
    def _open_event_config_modal(self, page: Page, event_uniq_id: str):
        page.goto(f'/event/{event_uniq_id}')
        page.get_by_test_id('nav-admin-event-config-tab-tab').click()
        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        # .modal-dialog is a Bootstrap placeholder until htmx swaps the real
        # form in; wait for the stored location so a fill can't be overwritten.
        expect(modal.get_by_test_id('location')).to_have_value('Paris')
        return modal

    def _open_sets_modal(self, page: Page, modal):
        modal.get_by_role('button', name='Age categories').click()
        modal.locator('#age-category-sets-configure-button').click()
        expect(page.locator('#event-age-category-sets-modal')).to_be_visible()

    def test_create_and_delete_a_set_keeping_the_event_form(
        self, page: Page, api_request_context: APIRequestContext
    ):
        TestUtils.create_event(EVENT_ID, via_api_request_context=api_request_context)
        modal = self._open_event_config_modal(page, EVENT_ID)
        TestUtils.fill_and_confirm(modal.get_by_test_id('location'), 'Unsaved Location')
        self._open_sets_modal(page, modal)

        page.get_by_role('button', name='Add').click()
        page.get_by_test_id('category-set-name').fill(SET_NAME)
        page.locator('#category-set-categories').select_option(
            ['50+', '65+'], force=True
        )
        sets_modal = page.locator('#event-age-category-sets-modal')
        sets_modal.get_by_role('button', name='Create').click()
        expect(sets_modal).to_contain_text(SET_NAME)

        set_row = sets_modal.locator('.border').filter(has_text=SET_NAME)
        set_row.locator('button:has(.bi-trash-fill)').click()
        expect(sets_modal).not_to_contain_text(SET_NAME)

        # A delete carries the event form on, so Back restores it unsaved.
        page.get_by_role('button', name='Back').click()
        expect(page.locator('#age-categories-main-container')).to_be_visible()
        expect(page.get_by_test_id('location')).to_have_value('Unsaved Location')
