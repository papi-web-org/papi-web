import re

import pytest
from playwright.sync_api import Page, expect, APIRequestContext
from tests.test_config import TestUtils


EVENT_ID = 'tournament-test-event'
TOURNAMENT_ID = 'test-tournament'


@pytest.mark.e2e
class TestTournamentFunctionality:
    def test_create_and_delete_tournament(
        self, page: Page, api_request_context: APIRequestContext
    ):
        TestUtils.create_event(EVENT_ID, via_api_request_context=api_request_context)
        page.goto(f'/event/{EVENT_ID}/tournaments')
        TestUtils.button_by_text(page, 'Create a tournament').click()
        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        name = 'Test Tournament'
        modal.get_by_test_id('name').fill(name)
        modal.get_by_test_id('rounds').fill('7')
        modal.get_by_role('button', name='Create', exact=True).click()

        # Redirection to Tie-breaks
        success_alert = modal.locator(f"div.alert:has-text('{name}')")
        expect(success_alert).to_be_visible()
        TestUtils.button_by_text(modal, 'Close').click()
        expect(page.get_by_role('button', name='List view')).to_have_attribute(
            'aria-pressed', 'true'
        )
        item = page.get_by_test_id('tournaments-item').filter(has_text=name)
        expect(item).to_be_visible()

        item.locator('button[hx-get*="tie-breaks-modal"]').click()
        expect(modal).to_be_visible()
        select_container = modal.locator('#tie-break-set').locator('..')
        select_container.locator('.select2-selection').click()
        page.locator('.select2-results__option[id$="swiss-sc-recommendation"]').click()
        TestUtils.button_by_text(modal, 'Apply').click()

        # The set lists the points as its leading criterion, then its
        # five tie-breaks.
        expect(modal.locator('.tie-break-row')).to_have_count(6)
        page.wait_for_function('!ignoreNextModalClose')
        TestUtils.button_by_text(modal, 'Close').click()
        expect(modal).not_to_be_visible()
        item = page.get_by_test_id('tournaments-item').filter(has_text=name)
        expect(item).to_be_visible()

        details = page.get_by_role('checkbox', name='Details')
        details.check()
        expect(item.locator('.collection-list-details')).to_have_class(
            re.compile(r'\bshow\b')
        )

        page.get_by_role('button', name='Card view').click()
        expect(page.get_by_role('button', name='Card view')).to_have_attribute(
            'aria-pressed', 'true'
        )
        item = page.get_by_test_id('tournaments-item').filter(has_text=name)
        expect(item.locator('.collection-card-details')).to_be_visible()

        button = item.locator('button[hx-get*="delete"]')
        button.click()

        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        modal.locator('#confirm-checkbox').click()
        delete_button = TestUtils.button_by_text(modal, 'Delete')
        expect(delete_button).to_be_enabled()
        delete_button.click()
        expect(page.get_by_test_id('tournaments-item')).to_have_count(0)
