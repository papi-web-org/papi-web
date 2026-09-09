import re

import pytest
from playwright.sync_api import APIRequestContext, Page, expect

from data.pairings.variations import StandardTeamSwissVariation
from tests.test_config import ScreenType, TestUtils
from utils.enum import EventType


TEAM_EVENT_ID = 'admin-collections-team-event'
PRIZE_EVENT_ID = 'admin-collections-prize-event'
TOURNAMENT_ID = 'admin-collections-test-tournament'
SECOND_TOURNAMENT_ID = 'admin-collections-second-tournament'
DISPLAY_CONTROLLER_SCREEN_NAME = 'Collection Display Controller Screen'
DISPLAY_CONTROLLER_NAME = 'Collection Display Controller'
STANDALONE_RESULTS_SCREEN_NAME = 'Collection Last Results Screen'
STANDALONE_IMAGE_SCREEN_NAME = 'Collection Image Screen'
FAMILY_TOURNAMENT_NAME = 'Collection Family Tournament'
FAMILY_UNIQ_ID = 'collection-family-source'
TINY_IMAGE_DATA_URI = 'data:image/gif;base64,R0lGODlhAQABAAAAACw='


@pytest.fixture(scope='module', autouse=True)
def setup(api_request_context: APIRequestContext):
    TestUtils.create_event(
        TEAM_EVENT_ID,
        via_api_request_context=api_request_context,
        overrides={'event_type': EventType.TEAM.value},
    )
    TestUtils.create_tournament(
        TEAM_EVENT_ID,
        TOURNAMENT_ID,
        overrides={
            'pairing': StandardTeamSwissVariation.static_id(),
            'team_player_count': 4,
        },
    )
    TestUtils.create_tournament(
        TEAM_EVENT_ID,
        SECOND_TOURNAMENT_ID,
        overrides={
            'pairing': StandardTeamSwissVariation.static_id(),
            'team_player_count': 4,
        },
    )
    TestUtils.create_event(
        PRIZE_EVENT_ID,
        via_api_request_context=api_request_context,
    )
    TestUtils.create_tournament(
        PRIZE_EVENT_ID,
        TOURNAMENT_ID,
        via_api_request_context=api_request_context,
    )
    TestUtils.create_tournament(
        PRIZE_EVENT_ID,
        SECOND_TOURNAMENT_ID,
        via_api_request_context=api_request_context,
    )
    yield
    TestUtils.delete_event(TEAM_EVENT_ID, via_api_request_context=api_request_context)
    TestUtils.delete_event(PRIZE_EVENT_ID, via_api_request_context=api_request_context)


@pytest.mark.e2e
class TestAdminCollections:
    def test_event_row_opens_event_without_making_buttons_click_through(
        self, page: Page
    ):
        page.goto('/current_events?collection_view=list')
        item = page.get_by_test_id('events-item').filter(has_text=PRIZE_EVENT_ID)
        expect(item).to_be_visible()
        row = item.locator('.collection-list-row')
        expect(row).to_have_class(re.compile(r'\bcollection-list-row-actionable\b'))

        item.locator('.collection-details-button').click()
        expect(page).to_have_url(re.compile(r'/current_events'))

        item.locator('.collection-list-cell-identity').click()
        expect(page).to_have_url(re.compile(rf'/event/{PRIZE_EVENT_ID}/tournaments$'))

    def test_team_supports_list_card_and_details_views(self, page: Page):
        page.goto(f'/event/{TEAM_EVENT_ID}/teams')
        TestUtils.button_by_text(page, 'Create a team').click()
        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        name = 'Collection Team'
        modal.get_by_test_id('name').fill(name)
        modal.get_by_role('button', name='Create', exact=True).click()

        item = page.get_by_test_id('teams-item').filter(has_text=name)
        expect(item).to_be_visible()
        empty_drop_zones = page.locator('.team-sortable').filter(
            has=page.locator('.non-sortable')
        )
        expect(empty_drop_zones.first).to_have_class(
            re.compile(r'\bcollection-list-items\b')
        )
        details = item.locator('.collection-list-details')
        item.locator('.collection-details-button').click()
        expect(details).to_have_class(re.compile(r'\bshow\b'))
        details_toggle = page.get_by_role('checkbox', name='Details')
        details_toggle.check()
        expect(item.locator('.collection-list-details')).to_have_class(
            re.compile(r'\bshow\b')
        )
        details_toggle.uncheck()
        expect(details).not_to_have_class(re.compile(r'\bshow\b'))

        auto_sort_directions = item.evaluate(
            """element => {
                const container = element.closest('.team-sortable');
                const onMove = Sortable.get(container).options.onMove;
                const target = document.createElement('div');
                target.dataset.sortKey = 'lineup-avg';
                const related = element.cloneNode(true);
                const relatedInput = related.querySelector('.assignment-input');
                const draggedValue = Number(
                    element.querySelector('.assignment-input').dataset.lineupAvg
                );
                const directionFor = relatedValue => {
                    relatedInput.dataset.lineupAvg = relatedValue;
                    return onMove({
                        to: target,
                        dragged: element,
                        related,
                        willInsertAfter: false,
                    });
                };
                return {
                    beforeLower: directionFor(draggedValue - 1),
                    afterEqual: directionFor(draggedValue),
                    afterHigher: directionFor(draggedValue + 1),
                };
            }"""
        )
        assert auto_sort_directions == {
            'beforeLower': -1,
            'afterEqual': 1,
            'afterHigher': 1,
        }

        page.get_by_role('button', name='Card view').click()
        item = page.get_by_test_id('teams-item').filter(has_text=name)
        expect(page.get_by_role('checkbox', name='Rosters')).to_be_checked()
        expect(page.get_by_role('checkbox', name='Lineups')).to_be_checked()
        expect(item.locator('.collection-card-details')).to_have_count(0)
        expect(item.locator('.collection-component-card_content')).to_contain_text(
            'Roster'
        )
        expect(item.locator('.card-block-button button')).to_be_visible()

    def test_prize_category_uses_the_shared_collection(self, page: Page):
        page.goto(f'/event/{PRIZE_EVENT_ID}/prizes')
        TestUtils.button_by_text(page, 'Create a Prize Bracket').click()
        create_category = page.get_by_role('button', name='Create a category')
        create_category.first.click()
        create_category.last.click()

        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        name = 'Collection Category'
        modal.get_by_test_id('name').fill(name)
        modal.get_by_role('button', name='Create', exact=True).click()

        create_category = page.get_by_role('button', name='Create a category')
        create_category.first.click()
        create_category.last.click()
        modal = page.locator('.modal-dialog')
        expect(modal).to_be_visible()
        modal.get_by_test_id('name').fill('Second Collection Category')
        modal.get_by_role('button', name='Create', exact=True).click()

        item = page.get_by_test_id('prize-categories-item').filter(has_text=name)
        expect(item).to_be_visible()
        expect(item.locator('.collection-component-drag_handle i')).to_have_class(
            re.compile(r'\bbi-grip-vertical\b')
        )

        page.get_by_role('button', name='Card view').click()
        item = page.get_by_test_id('prize-categories-item').filter(has_text=name)
        expect(item.locator('.collection-component-drag_handle i')).to_have_class(
            re.compile(r'\bbi-arrows-move\b')
        )

    def test_tournament_drag_icon_matches_the_view(self, page: Page):
        page.goto(f'/event/{PRIZE_EVENT_ID}/tournaments')
        expect(page.locator('.collection-list-header')).not_to_contain_text(
            'Project-Id-Version'
        )
        column_geometry = page.locator('.admin-collection-list').evaluate(
            """(collection) => {
                const headers = [
                    ...collection.querySelectorAll(
                        ':scope > .collection-list-header > '
                        + '.collection-list-header-cell'
                    ),
                ];
                const cells = [
                    ...collection.querySelector(
                        '.collection-list-row'
                    ).querySelectorAll(':scope > .collection-list-cell'),
                ];
                return headers.map((header, index) => {
                    const headerRect = header.getBoundingClientRect();
                    const cellRect = cells[index].getBoundingClientRect();
                    return {
                        leftDifference: headerRect.left - cellRect.left,
                        widthDifference: headerRect.width - cellRect.width,
                    };
                });
            }"""
        )
        assert all(
            abs(column['leftDifference']) < 1 and abs(column['widthDifference']) < 1
            for column in column_geometry
        )
        item = page.get_by_test_id('tournaments-item').filter(has_text=TOURNAMENT_ID)
        expect(item.locator('.collection-list-row')).not_to_have_class(
            re.compile(r'\bcollection-list-row-actionable\b')
        )
        expect(item.locator('.collection-component-drag_handle i')).to_have_class(
            re.compile(r'\bbi-grip-vertical\b')
        )
        tie_breaks = item.locator('.collection-component-tie_break_summary')
        # A new tournament ranks on the points alone: the criterion is
        # listed, and the warning still says nothing breaks ties.
        expect(tie_breaks).to_contain_text('PTS')
        expect(tie_breaks.locator('[class*="bi-exclamation"]')).to_have_count(1)
        configuration_buttons = item.locator(
            'button[aria-label="Configure the tie-breaks of the tournament."]'
        )
        expect(configuration_buttons).to_have_count(1)
        expect(
            tie_breaks.get_by_role(
                'button',
                name='Configure the tie-breaks of the tournament.',
            )
        ).to_be_visible()
        configuration_button = tie_breaks.locator('button.collection-inline-edit')
        expect(configuration_button).to_be_visible()
        expect(
            configuration_button.locator('.collection-inline-edit-label')
        ).to_have_css('border-bottom-style', 'dotted')
        expect(configuration_button.locator('.bi-gear-fill')).to_have_count(0)

        page.get_by_role('button', name='Card view').click()
        item = page.get_by_test_id('tournaments-item').filter(has_text=TOURNAMENT_ID)
        expect(item.locator('.collection-component-drag_handle i')).to_have_class(
            re.compile(r'\bbi-arrows-move\b')
        )
        expect(
            item.get_by_role(
                'button',
                name='Configure the tie-breaks of the tournament.',
            )
        ).to_be_visible()

    def test_staff_rows_do_not_overflow_when_columns_fit(self, page: Page):
        page.set_viewport_size({'width': 1280, 'height': 800})
        page.goto(f'/event/{PRIZE_EVENT_ID}/accounts')
        get_started = page.get_by_role('button', name='Get started')
        if get_started.is_visible():
            get_started.click()

        list_scroll = page.locator('.admin-collection-list-scroll')
        expect(list_scroll).to_be_visible()
        has_unnecessary_overflow = list_scroll.evaluate(
            '(element) => element.scrollWidth > element.clientWidth + 1'
        )
        assert not has_unnecessary_overflow

        regular_cell = page.locator(
            '.collection-list-cell:not(.collection-list-cell-actions)'
            ':not(.collection-details-column):not(.collection-drag-column)'
        ).first
        expect(regular_cell).to_have_css('overflow', 'hidden')

        page.get_by_role('button', name='Card view').click()
        account = page.get_by_test_id('accounts-item').first
        expect(account.locator('.collection-card-body')).to_have_count(0)

    def test_admin_display_controller_assignment_uses_compact_text(
        self,
        page: Page,
        api_request_context: APIRequestContext,
    ):
        stored_screen = TestUtils.create_screen(
            api_request_context,
            PRIZE_EVENT_ID,
            DISPLAY_CONTROLLER_SCREEN_NAME,
            ScreenType.RESULTS,
        )
        stored_display_controller = TestUtils.create_display_controller(
            api_request_context,
            PRIZE_EVENT_ID,
            DISPLAY_CONTROLLER_NAME,
            screen_uniq_id=stored_screen.uniq_id,
        )
        assert stored_display_controller.id is not None
        try:
            page.goto(f'/event/{PRIZE_EVENT_ID}/display_controllers')
            item = page.get_by_test_id('display-controllers-item').filter(
                has_text=DISPLAY_CONTROLLER_NAME
            )
            expect(item).to_be_visible()
            assignment = item.locator('.collection-component-assignment')
            expect(assignment).to_contain_text(DISPLAY_CONTROLLER_SCREEN_NAME)
            expect(assignment).not_to_contain_text('Currently displaying')
            expect(assignment.locator('.bi-arrow-right')).to_be_visible()
            expect(item.locator('.collection-list-cell-actions')).to_have_count(1)

            page.get_by_role('button', name='Card view').click()
            item = page.get_by_test_id('display-controllers-item').filter(
                has_text=DISPLAY_CONTROLLER_NAME
            )
            assignment = item.locator('.collection-component-assignment')
            expect(assignment).to_contain_text(DISPLAY_CONTROLLER_SCREEN_NAME)
            expect(assignment).not_to_contain_text('Currently displaying')
            expect(assignment.locator('.bi-arrow-right')).to_be_visible()
            expect(item.locator('.collection-card-footer')).to_have_count(1)
        finally:
            TestUtils.delete_display_controller(
                api_request_context,
                PRIZE_EVENT_ID,
                stored_display_controller.id,
            )
            TestUtils.delete_screen(
                api_request_context, PRIZE_EVENT_ID, stored_screen.id
            )

    def test_admin_screen_list_uses_generated_screen_names_without_multiscreen_column(
        self,
        page: Page,
        api_request_context: APIRequestContext,
    ):
        results_screen = TestUtils.create_screen(
            api_request_context,
            PRIZE_EVENT_ID,
            STANDALONE_RESULTS_SCREEN_NAME,
            ScreenType.RESULTS,
        )
        image_screen = TestUtils.create_screen(
            api_request_context,
            PRIZE_EVENT_ID,
            STANDALONE_IMAGE_SCREEN_NAME,
            ScreenType.IMAGE,
            {
                'background_color_checkbox': True,
                'background_image_upload': TINY_IMAGE_DATA_URI,
            },
        )
        family_tournament = TestUtils.create_tournament(
            PRIZE_EVENT_ID,
            FAMILY_TOURNAMENT_NAME,
            via_api_request_context=api_request_context,
        )
        family = TestUtils.create_family(
            api_request_context,
            PRIZE_EVENT_ID,
            family_tournament,
            FAMILY_UNIQ_ID,
            ScreenType.INPUT,
            {'parts': 2},
        )
        family = TestUtils.update_family_name(
            PRIZE_EVENT_ID,
            family,
            '%t (%f to %l)',
        )
        try:
            page.goto(
                f'/event/{PRIZE_EVENT_ID}/screens'
                '?collection_view=list&show_family_screens=true'
            )

            for screen_type, screen_name in (
                (ScreenType.RESULTS, STANDALONE_RESULTS_SCREEN_NAME),
                (ScreenType.IMAGE, STANDALONE_IMAGE_SCREEN_NAME),
            ):
                section = page.locator(f'#admin-screens-show-{screen_type.value}')
                toggle = page.get_by_test_id(
                    f'accordion-screen-type-{screen_type.value}'
                )
                if toggle.get_attribute('aria-expanded') == 'false':
                    toggle.click()
                expect(section).to_be_visible()

                item = section.get_by_test_id('screens-item').filter(
                    has_text=screen_name
                )
                expect(item).to_be_visible()
                expect(section.locator('.collection-list-header')).not_to_contain_text(
                    'Multi-Screen'
                )
                expect(section.locator('.collection-list-header')).not_to_contain_text(
                    'Content'
                )
                expect(section.locator('.collection-list-header')).to_contain_text(
                    'Timer'
                )
                expect(item.locator('.collection-list-cell-source')).to_have_count(0)
                expect(item.locator('.collection-list-cell-screen_sets')).to_have_count(
                    0
                )
                expect(item.locator('.collection-list-cell-timer')).to_contain_text(
                    'No timer'
                )

            input_section = page.locator(
                f'#admin-screens-show-{ScreenType.INPUT.value}'
            )
            input_toggle = page.get_by_test_id(
                f'accordion-screen-type-{ScreenType.INPUT.value}'
            )
            if input_toggle.get_attribute('aria-expanded') == 'false':
                input_toggle.click()
            expect(input_section).to_be_visible()
            expect(
                input_section.locator('.collection-list-header')
            ).not_to_contain_text('Multi-Screen')
            expect(input_section.locator('.collection-list-header')).to_contain_text(
                'Timer'
            )
            expect(input_section.locator('.collection-list-header')).to_contain_text(
                'Content'
            )
            family_item = (
                input_section.get_by_test_id('screens-item')
                .filter(has_text=FAMILY_TOURNAMENT_NAME)
                .first
            )
            expect(family_item).to_be_visible()
            identity = family_item.locator('.collection-component-identity')
            expect(identity).to_contain_text(FAMILY_TOURNAMENT_NAME)
            expect(identity).to_contain_text('(')
            expect(identity).to_contain_text(')')
            expect(identity.locator('.badge')).to_contain_text('Multi-Screen')
            expect(identity.locator('.bi-window-split')).to_have_count(0)
            expect(family_item.locator('.collection-list-cell-source')).to_have_count(0)
            expect(
                family_item.locator('.collection-list-cell-screen_sets')
            ).to_contain_text('1 set')
            expect(family_item.locator('.collection-list-cell-timer')).to_contain_text(
                'No timer'
            )

            page.goto(f'/event/{PRIZE_EVENT_ID}/families?collection_view=list')
            family_list_item = (
                page.get_by_test_id('families-item')
                .filter(has_text=FAMILY_TOURNAMENT_NAME)
                .first
            )
            expect(family_list_item).to_be_visible()
            expect(page.locator('.collection-list-header')).to_contain_text('Timer')
            expect(
                family_list_item.locator('.collection-list-cell-timer')
            ).to_contain_text('No timer')
        finally:
            assert family.id is not None
            TestUtils.delete_family(api_request_context, PRIZE_EVENT_ID, family.id)
            TestUtils.delete_screen(
                api_request_context, PRIZE_EVENT_ID, image_screen.id
            )
            TestUtils.delete_screen(
                api_request_context, PRIZE_EVENT_ID, results_screen.id
            )
            TestUtils.delete_tournament(
                api_request_context, PRIZE_EVENT_ID, family_tournament
            )
