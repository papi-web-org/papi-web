import re

from database.sqlite.event.event_store import StoredScreen
import pytest
from playwright.sync_api import APIRequestContext, Page, expect
from tests.e2e.access_levels.base_access_level_test import (
    BaseAccessLevelTest,
    DisplayMode,
)
from tests.e2e.access_levels.conftest import PUBLIC_EVENT_ID
from tests.e2e.access_levels.conftest import TOURNAMENT_ID
from tests.test_config import ScreenType, TestUtils


PUBLIC_ROTATOR_SCREEN_NAME = 'Anonymous Rotator Screen'
PUBLIC_ROTATOR_NAME = 'Anonymous Rotator'
ASSIGNED_DISPLAY_CONTROLLER_NAME = 'Anonymous Assigned Display Controller'
UNASSIGNED_DISPLAY_CONTROLLER_NAME = 'Anonymous Unassigned Display Controller'
PUBLIC_IMAGE_SCREEN_NAME = 'Anonymous Image Screen'
PUBLIC_INPUT_FAMILY_UNIQ_ID = 'anonymous-input-family'
TINY_IMAGE_DATA_URI = 'data:image/gif;base64,R0lGODlhAQABAAAAACw='


@pytest.mark.e2e
class TestAnonymousAccessLevel(BaseAccessLevelTest):
    def get_access_levels(self):
        return []

    @pytest.fixture()
    def public_rotator(self, api_request_context: APIRequestContext):
        stored_screen = TestUtils.create_screen(
            api_request_context,
            PUBLIC_EVENT_ID,
            PUBLIC_ROTATOR_SCREEN_NAME,
            ScreenType.RESULTS,
            {'public': True},
        )
        rotator_id = TestUtils.create_rotator(
            api_request_context,
            PUBLIC_EVENT_ID,
            PUBLIC_ROTATOR_NAME,
            screen_ids=[stored_screen.id],
        )
        yield rotator_id
        TestUtils.delete_rotator(api_request_context, PUBLIC_EVENT_ID, rotator_id)
        TestUtils.delete_screen(api_request_context, PUBLIC_EVENT_ID, stored_screen.id)

    @pytest.fixture()
    def display_controllers(
        self,
        api_request_context: APIRequestContext,
        public_input_screen: StoredScreen,
    ):
        assigned_controller = TestUtils.create_display_controller(
            api_request_context,
            PUBLIC_EVENT_ID,
            ASSIGNED_DISPLAY_CONTROLLER_NAME,
            screen_uniq_id=public_input_screen.uniq_id,
        )
        unassigned_controller = TestUtils.create_display_controller(
            api_request_context,
            PUBLIC_EVENT_ID,
            UNASSIGNED_DISPLAY_CONTROLLER_NAME,
        )
        yield assigned_controller, unassigned_controller
        assert assigned_controller.id is not None
        assert unassigned_controller.id is not None
        TestUtils.delete_display_controller(
            api_request_context,
            PUBLIC_EVENT_ID,
            assigned_controller.id,
        )
        TestUtils.delete_display_controller(
            api_request_context,
            PUBLIC_EVENT_ID,
            unassigned_controller.id,
        )

    @pytest.fixture()
    def public_image_screen(self, api_request_context: APIRequestContext):
        stored_screen = TestUtils.create_screen(
            api_request_context,
            PUBLIC_EVENT_ID,
            PUBLIC_IMAGE_SCREEN_NAME,
            ScreenType.IMAGE,
            {
                'public': True,
                'background_color_checkbox': True,
                'background_image_upload': TINY_IMAGE_DATA_URI,
            },
        )
        yield stored_screen
        TestUtils.delete_screen(api_request_context, PUBLIC_EVENT_ID, stored_screen.id)

    @pytest.fixture()
    def public_input_family(
        self,
        api_request_context: APIRequestContext,
        access_level_test_tournament,
    ):
        stored_family = TestUtils.create_family(
            api_request_context,
            PUBLIC_EVENT_ID,
            access_level_test_tournament,
            PUBLIC_INPUT_FAMILY_UNIQ_ID,
            ScreenType.INPUT,
            {'parts': 2, 'public': True},
        )
        stored_family = TestUtils.update_family_name(
            PUBLIC_EVENT_ID,
            stored_family,
            '%t (%f to %l)',
        )
        yield stored_family
        assert stored_family.id is not None
        TestUtils.delete_family(api_request_context, PUBLIC_EVENT_ID, stored_family.id)

    def test_access(
        self,
        lan_page: Page,
        public_input_screen: StoredScreen,
        private_input_screen: StoredScreen,
    ):
        # Admin tabs

        super().assert_can_access_players_tab(False, lan_page)
        super().assert_can_access_pairings_tab(False, lan_page)

        # Screens

        super().assert_access_to_visible_events(PUBLIC_EVENT_ID, lan_page)
        super().assert_access_to_input_screen(
            True,
            DisplayMode.SCREENS_NOT_IN_MENU,
            lan_page,
            public_input_screen,
        )
        super().assert_access_to_input_screen(
            False,
            DisplayMode.SCREENS_NOT_IN_MENU,
            lan_page,
            private_input_screen,
        )

    def test_anonymous_screen_items_are_clickable_without_actions(
        self,
        lan_page: Page,
        public_input_screen: StoredScreen,
        public_input_family,
    ):
        lan_page.goto(f'/event/{PUBLIC_EVENT_ID}/input-screens?collection_view=list')

        item = lan_page.get_by_test_id('screens-item').filter(
            has_text=public_input_screen.name
        )
        expect(item).to_be_visible()
        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Actions'
        )
        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Multi-Screen'
        )
        expect(lan_page.locator('.collection-list-header')).to_contain_text('Content')
        expect(lan_page.locator('.collection-list-header')).to_contain_text('Timer')
        expect(item.locator('.collection-list-cell-actions')).to_have_count(0)
        expect(item.locator('.collection-list-row')).to_have_class(
            re.compile(r'\bcollection-list-row-actionable\b')
        )
        set_cell = item.locator('.collection-list-cell-screen_sets')
        expect(set_cell).to_contain_text('1 set')
        expect(set_cell.locator('.collection-inline-edit')).to_have_count(0)
        expect(set_cell.locator('.bi-pencil-fill')).to_have_count(0)
        expect(set_cell.locator('[data-bs-toggle="tooltip"]')).to_have_count(0)
        expect(item.locator('.collection-list-cell-source')).to_have_count(0)
        expect(item.locator('.collection-list-cell-timer')).to_contain_text('No timer')

        family_item = (
            lan_page.get_by_test_id('screens-item')
            .filter(
                has=lan_page.locator('.collection-component-identity .badge'),
            )
            .first
        )
        expect(family_item).to_be_visible()
        family_identity = family_item.locator('.collection-component-identity')
        expect(family_identity).to_contain_text(TOURNAMENT_ID)
        expect(family_identity).to_contain_text('(')
        expect(family_identity).to_contain_text(')')
        expect(family_identity.locator('.badge')).to_contain_text('Multi-Screen')
        expect(family_identity.locator('.bi-window-split')).to_have_count(0)
        expect(family_item.locator('.collection-list-cell-source')).to_have_count(0)
        expect(family_item.locator('.collection-list-cell-timer')).to_contain_text(
            'No timer'
        )

        lan_page.get_by_role('button', name='Card view').click()
        item = lan_page.get_by_test_id('screens-item').filter(
            has_text=public_input_screen.name
        )
        expect(item).to_have_class(re.compile(r'\bcollection-card-actionable\b'))
        expect(item.locator('.collection-card-footer')).to_have_count(0)
        expect(item.locator('a[id^="screen-eye-"]')).to_have_count(0)

    def test_anonymous_standalone_screen_types_hide_multiscreen_column(
        self,
        lan_page: Page,
        public_image_screen: StoredScreen,
    ):
        lan_page.goto(f'/event/{PUBLIC_EVENT_ID}/image-screens?collection_view=list')

        item = lan_page.get_by_test_id('screens-item').filter(
            has_text=public_image_screen.name
        )
        expect(item).to_be_visible()
        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Multi-Screen'
        )
        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Content'
        )
        expect(item.locator('.collection-list-cell-source')).to_have_count(0)
        expect(item.locator('.collection-list-cell-screen_sets')).to_have_count(0)

    def test_anonymous_rotator_items_are_clickable_without_actions(
        self,
        lan_page: Page,
        public_rotator: int,
    ):
        lan_page.goto(f'/event/{PUBLIC_EVENT_ID}/rotators?collection_view=list')

        item = lan_page.get_by_test_id('rotators-item').filter(
            has_text=PUBLIC_ROTATOR_NAME
        )
        expect(item).to_be_visible()
        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Actions'
        )
        expect(item.locator('.collection-list-cell-actions')).to_have_count(0)
        expect(item.locator('.collection-list-row')).to_have_class(
            re.compile(r'\bcollection-list-row-actionable\b')
        )
        expect(item.locator('.collection-list-row')).to_have_attribute(
            'data-collection-row-href',
            re.compile(rf'/view/rotator/{PUBLIC_EVENT_ID}/{public_rotator}$'),
        )
        expect(item.locator('.collection-inline-edit')).to_have_count(0)

        lan_page.get_by_role('button', name='Card view').click()
        item = lan_page.get_by_test_id('rotators-item').filter(
            has_text=PUBLIC_ROTATOR_NAME
        )
        expect(item).to_have_class(re.compile(r'\bcollection-card-actionable\b'))
        expect(item.locator('.collection-card-footer')).to_have_count(0)
        expect(item.locator('a:has(i.bi-eye)')).to_have_count(0)

    def test_anonymous_display_controller_items_are_simplified(
        self,
        lan_page: Page,
        display_controllers,
    ):
        assigned_controller, unassigned_controller = display_controllers
        assert assigned_controller.id is not None

        lan_page.goto(
            f'/event/{PUBLIC_EVENT_ID}/display_controllers?collection_view=list'
        )

        expect(lan_page.locator('.collection-list-header')).not_to_contain_text(
            'Actions'
        )
        assigned_item = lan_page.get_by_test_id('display-controllers-item').filter(
            has_text=ASSIGNED_DISPLAY_CONTROLLER_NAME
        )
        expect(assigned_item).to_be_visible()
        expect(assigned_item.locator('.collection-list-cell-actions')).to_have_count(0)
        expect(assigned_item.locator('.collection-list-row')).to_have_class(
            re.compile(r'\bcollection-list-row-actionable\b')
        )
        expect(assigned_item.locator('.collection-list-row')).to_have_attribute(
            'data-collection-row-href',
            re.compile(
                rf'/view/display-controller/{PUBLIC_EVENT_ID}/'
                rf'{assigned_controller.id}$'
            ),
        )
        expect(
            assigned_item.locator('.collection-component-assignment')
        ).to_contain_text('Input Screen with pairings')
        expect(
            assigned_item.locator('.collection-component-assignment')
        ).not_to_contain_text('Currently displaying')
        expect(
            assigned_item.locator('.collection-component-assignment .bi-arrow-right')
        ).to_be_visible()

        unassigned_item = lan_page.get_by_test_id('display-controllers-item').filter(
            has_text=UNASSIGNED_DISPLAY_CONTROLLER_NAME
        )
        expect(unassigned_item).to_be_visible()
        expect(
            unassigned_item.locator('.collection-component-assignment')
        ).to_have_text('None')
        expect(unassigned_item.locator('.collection-list-row')).not_to_have_class(
            re.compile(r'\bcollection-list-row-actionable\b')
        )
        assert unassigned_controller.id is not None

        lan_page.get_by_role('button', name='Card view').click()
        assigned_item = lan_page.get_by_test_id('display-controllers-item').filter(
            has_text=ASSIGNED_DISPLAY_CONTROLLER_NAME
        )
        expect(assigned_item).to_have_class(
            re.compile(r'\bcollection-card-actionable\b')
        )
        expect(assigned_item.locator('.collection-card-footer')).to_have_count(0)
        expect(assigned_item.locator('a:has(i.bi-eye)')).to_have_count(0)
