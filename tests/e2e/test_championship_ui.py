import re
import time
from datetime import date

import pytest
from playwright.sync_api import APIRequestContext, Page, expect

from data.championship.championship_loader import (
    ChampionshipArchiveLoader,
    ChampionshipLoader,
)
from data.loader import EventLoader
from database.sqlite.event.event_store import StoredPlayer
from tests.test_config import TestUtils


EVENT_ID = 'championship-ui-source'
TOURNAMENT_NAME = 'Championship UI Stage'
OTHER_EVENT_ID = 'championship-ui-other-source'
OTHER_TOURNAMENT_NAME = 'Completely Different Stage'
OTHER_TOURNAMENT_NAME_2 = 'Another Different Stage'
CHAMPIONSHIP_NAME = 'Championship UI Test'
TEAM_CHAMPIONSHIP_NAME = 'Team Championship UI Test'
CHAMPIONSHIP_ID = 'championship_ui_test'
RENAMED_CHAMPIONSHIP_ID = 'championship-ui-renamed'
TEAM_CHAMPIONSHIP_ID = 'team_championship_ui_test'


def _select_criterion_type(modal, type_value: str, reveal_container_id: str):
    """Pick a criterion type and wait for its option container to reveal.

    Setting the Select2 ``#type`` fires a late empty-value ``change`` that its
    toggle handler reads as "hide everything", so re-fire ``change`` until the
    reveal survives Select2's settle.
    """
    select = modal.locator('select[name="type"]')
    container = modal.locator(f'#{reveal_container_id}')
    select.select_option(type_value, force=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        select.dispatch_event('change')
        if container.is_visible():
            time.sleep(0.2)
            if container.is_visible():
                return
    expect(container).to_be_visible()


def _delete_test_championship():
    loader = ChampionshipLoader()
    test_ids = {
        CHAMPIONSHIP_NAME,
        CHAMPIONSHIP_ID,
        RENAMED_CHAMPIONSHIP_ID,
        TEAM_CHAMPIONSHIP_NAME,
        TEAM_CHAMPIONSHIP_ID,
    }
    for championship_id in test_ids:
        loader.delete_championship(championship_id)
    for archive in ChampionshipArchiveLoader.get_sorted_archives():
        if archive.name.split('#')[0] in test_ids:
            archive.file.unlink()


@pytest.fixture(scope='module', autouse=True)
def setup(api_request_context: APIRequestContext):
    _delete_test_championship()
    TestUtils.create_event(EVENT_ID, via_api_request_context=api_request_context)
    TestUtils.create_tournament(
        EVENT_ID,
        TOURNAMENT_NAME,
        via_api_request_context=api_request_context,
    )
    event = EventLoader().load_event(EVENT_ID)
    event.add_player(
        StoredPlayer(
            id=None,
            last_name='MURER',
            first_name='Brian',
            year_of_birth=2015,
            gender='M',
            fide_id=651038188,
        ),
        [event.tournaments_by_id[1]],
    )
    TestUtils.create_event(OTHER_EVENT_ID, via_api_request_context=api_request_context)
    TestUtils.create_tournament(
        OTHER_EVENT_ID,
        OTHER_TOURNAMENT_NAME,
        via_api_request_context=api_request_context,
    )
    TestUtils.create_tournament(
        OTHER_EVENT_ID,
        OTHER_TOURNAMENT_NAME_2,
        via_api_request_context=api_request_context,
    )
    yield
    _delete_test_championship()
    TestUtils.delete_event(EVENT_ID, via_api_request_context=api_request_context)
    TestUtils.delete_event(OTHER_EVENT_ID, via_api_request_context=api_request_context)


@pytest.mark.e2e
def test_championship_admin_workflow(page: Page):
    page.goto('/championships')
    expect(page.locator('#nav-championships-tab')).to_contain_text('Current')
    expect(page.locator('#nav-coming_championships-tab')).to_contain_text('Upcoming')
    expect(page.locator('#nav-passed_championships-tab')).to_contain_text('Passed')
    expect(page.locator('#nav-championship_archives-tab')).to_contain_text('Archived')
    expect(page.locator('#nav-championships-tab')).to_be_disabled()
    expect(page.locator('#nav-championship_archives-tab')).to_be_disabled()
    page.get_by_role('button', name='Create a championship', exact=True).first.click()
    modal = page.locator('.modal-dialog')
    expect(modal).to_be_visible()
    modal.locator('input[name="name"]').fill(CHAMPIONSHIP_NAME)
    modal.get_by_test_id('championship-create-submit').click()

    expect(page).to_have_url(re.compile(r'/championship/.+/configuration$'))
    expect(page.get_by_role('heading', name=CHAMPIONSHIP_NAME)).to_be_visible()

    page.goto('/championships')
    expect(page.locator('#nav-championships-tab')).to_be_enabled()
    page.get_by_role('button', name='Card view').click()
    expect(page.get_by_role('button', name='Card view')).to_have_attribute(
        'aria-pressed', 'true'
    )
    page.get_by_role('button', name='List view').click()
    expect(page.get_by_role('button', name='List view')).to_have_attribute(
        'aria-pressed', 'true'
    )
    page.get_by_test_id('championships-item').filter(has_text=CHAMPIONSHIP_NAME).click()
    expect(page.get_by_role('heading', name=CHAMPIONSHIP_NAME)).to_be_visible()

    page.get_by_test_id('nav-sources-tab').click()
    page.get_by_role('button', name='Add a tournament').click()
    modal = page.locator('.modal-dialog')
    expect(modal).to_be_visible()
    # Both selects are Select2 (select_input macro); the native <select> is
    # hidden, so target it by name and force the option change. Choosing an
    # event re-renders the modal server-side with that event's stages.
    tournament_select = modal.locator('select[name="tournament_id"]')
    expect(tournament_select).to_be_disabled()
    event_select = modal.locator('select[name="event_uniq_id"]')
    event_select.select_option(EVENT_ID, force=True)
    expect(tournament_select).to_be_enabled()
    expect(tournament_select.locator('option')).to_have_count(2)
    expect(tournament_select).to_contain_text(TOURNAMENT_NAME)
    expect(tournament_select).not_to_contain_text(OTHER_TOURNAMENT_NAME)
    expect(tournament_select).to_have_value('1')
    event_select.select_option(OTHER_EVENT_ID, force=True)
    expect(tournament_select.locator('option')).to_have_count(3)
    expect(tournament_select).to_contain_text(OTHER_TOURNAMENT_NAME)
    expect(tournament_select).to_contain_text(OTHER_TOURNAMENT_NAME_2)
    expect(tournament_select).not_to_contain_text(TOURNAMENT_NAME)
    expect(tournament_select).to_have_value('')
    event_select.select_option(EVENT_ID, force=True)
    expect(tournament_select).to_have_value('1')
    modal.locator('.dropdown-toggle-split').click()
    modal.get_by_role('button', name='Select and add another').click()
    expect(modal.get_by_text(f'Tournament [{TOURNAMENT_NAME}] added.')).to_be_visible()
    modal.get_by_role('button', name='Cancel').click()
    source_item = page.get_by_test_id('championship-sources-item').filter(
        has_text=TOURNAMENT_NAME
    )
    expect(source_item).to_be_visible()
    expect(page.get_by_text('Live', exact=True)).to_have_count(0)
    source_item.get_by_role('button', name='Remove').click()
    remove_modal = page.locator('.modal-dialog')
    expect(
        remove_modal.get_by_role('heading', name='Remove tournament')
    ).to_be_visible()
    expect(remove_modal).to_contain_text(
        'The source event and tournament will not be deleted.'
    )
    remove_modal.get_by_role('button', name='Cancel').click()

    page.get_by_test_id('nav-competitors-tab').click()
    expect(page.get_by_role('heading', name='Players')).to_be_visible()
    expect(page.get_by_role('button', name='Merge selected players')).to_be_disabled()
    competitors_table = page.locator('#championship-competitors-table')
    expect(competitors_table).to_be_visible()
    expect(competitors_table).to_have_class(re.compile(r'\bprominent\b'))
    expect(competitors_table.get_by_role('columnheader', name='Cat.')).to_be_visible()
    expect(competitors_table.get_by_role('columnheader', name='Gen.')).to_be_visible()
    tournament_count = page.get_by_test_id('championship-tournament-count')
    expect(tournament_count).to_have_text('1')
    # The stage list is rendered as a table inside the (hidden) popover content
    # div; its text content lists the source tournament.
    stage_popover = page.get_by_test_id('championship-stage-popover-content').first
    expect(stage_popover).to_contain_text(TOURNAMENT_NAME)
    expect(page.get_by_role('button', name='Card view')).to_have_count(0)
    expect(page.get_by_role('button', name='List view')).to_have_count(0)

    page.get_by_test_id('nav-documents-tab').click()
    modal = page.locator('.modal-dialog')
    expect(modal.get_by_role('heading', name='Documents')).to_be_visible()
    # The document picker shows only the selected document's options (the
    # #document select is a Select2, so drive the native element + change).
    document_select = modal.locator('select[name="document"]')
    document_select.select_option('tournaments', force=True)
    document_select.dispatch_event('change')
    expect(modal.locator('#tournament_name_container')).to_be_visible()
    expect(modal.locator('#include_popover_container')).to_be_hidden()
    document_select.select_option('rankings', force=True)
    document_select.dispatch_event('change')
    expect(modal.locator('#include_popover_container')).to_be_visible()
    expect(modal.locator('#tournament_name_container')).to_be_hidden()
    modal.get_by_role('button', name='Cancel').click()

    event_delete_modal = page.request.get(
        f'/current_events/event-modal/delete/{EVENT_ID}'
    )
    assert event_delete_modal.ok
    assert CHAMPIONSHIP_NAME in event_delete_modal.text()
    assert 'will break its sources' in event_delete_modal.text()

    tournament_delete_modal = page.request.get(f'/tournament-delete-modal/{EVENT_ID}/1')
    assert tournament_delete_modal.ok
    assert CHAMPIONSHIP_NAME in tournament_delete_modal.text()
    assert 'will break its source' in tournament_delete_modal.text()

    page.get_by_test_id('nav-configuration-tab').click()
    expect(page.get_by_role('heading', name='Configuration')).to_be_visible()
    TestUtils.take_screenshot(page, 'bug')
    page.locator('button[hx-get^="/championship"][hx-get$="/config-modal"]').click()
    modal = page.locator('.modal-dialog')
    expect(modal.get_by_role('heading', name='Base configuration')).to_be_visible()
    expect(modal.locator('#modal-form input[name="uniq_id"]')).to_have_count(0)
    expect(modal).to_contain_text(f'Unique ID: [{CHAMPIONSHIP_ID}]')
    reference_date = modal.locator('input[name="age_category_base_date"]')
    date_placeholder = reference_date.get_attribute('placeholder')
    assert date_placeholder and str(date.today().year) in date_placeholder
    expect(reference_date).to_have_value('')
    modal.get_by_test_id('uniq-id-update-button').click()
    uniq_id_input = modal.get_by_test_id('uniq-id-update-input')
    expect(uniq_id_input).to_be_visible()
    uniq_id_input.fill(RENAMED_CHAMPIONSHIP_ID)
    modal.get_by_test_id('uniq-id-update-submit-button').click()
    expect(page).to_have_url(
        re.compile(rf'/championship/{RENAMED_CHAMPIONSHIP_ID}/configuration$')
    )
    expect(
        page.get_by_role('button', name='Scoring and tie-break rules')
    ).to_be_visible()
    rule_rows = page.get_by_test_id('championship-rule-row')
    expect(rule_rows).to_have_count(1)
    expect(rule_rows.first).to_contain_text('Total points')

    # Add a rule through the config modal.
    page.get_by_test_id('championship-add-rule').click()
    modal = page.locator('.modal-dialog')
    expect(modal.get_by_role('heading', name='Add a rule')).to_be_visible()
    modal.locator('select[name="type"]').select_option('COUNT_WINS', force=True)
    modal.get_by_role('button', name='Add').click()
    expect(rule_rows).to_have_count(2)
    expect(rule_rows.nth(1)).to_contain_text('Number of wins')

    # Edit the first rule: scope it to the best 4 stages.
    rule_rows.nth(0).get_by_role('button', name='Edit rule').click()
    modal = page.locator('.modal-dialog')
    expect(modal.get_by_role('heading', name='Edit rule')).to_be_visible()
    modal.locator('input[name="best_n"]').fill('4')
    modal.get_by_role('button', name='Save').click()
    expect(rule_rows.nth(0)).to_contain_text('best 4 stages')

    # Reordering is enabled once there is more than one rule. Sortable is applied
    # after the htmx swap, so poll rather than reading it once.
    page.wait_for_function(
        "Boolean(Sortable.get(document.getElementById('championship-rule-rows')))"
    )

    # Delete the second rule (confirming in the modal).
    rule_rows.nth(1).get_by_role('button', name='Delete rule').click()
    delete_modal = page.locator('.modal-dialog')
    expect(delete_modal.get_by_role('heading', name='Delete rule')).to_be_visible()
    delete_modal.locator('button[type="submit"]').click()
    expect(rule_rows).to_have_count(1)

    # The base-configuration Edit modal changes the age reference date.
    changed_reference_date = date_placeholder.replace(
        str(date.today().year), str(date.today().year - 1)
    )
    page.locator('button[hx-get^="/championship"][hx-get$="/config-modal"]').click()
    modal = page.locator('.modal-dialog')
    reference_date = modal.locator('input[name="age_category_base_date"]')
    # Type the date (rather than fill) so the air-datepicker keyup handler commits
    # the selection, and wait for it to stick before saving — a raw fill leaves a
    # transient value the picker asynchronously discards.
    reference_date.click()
    reference_date.press_sequentially(changed_reference_date)
    expect(reference_date).to_have_value(changed_reference_date)
    modal.get_by_role('button', name='Save').click()
    expect(page).to_have_url(
        re.compile(rf'/championship/{RENAMED_CHAMPIONSHIP_ID}/configuration$')
    )
    expect(page.get_by_text(changed_reference_date, exact=False).first).to_be_visible()
    expect(rule_rows).to_have_count(1)

    expect(
        page.get_by_text(
            'The General ranking includes all players and is always available.'
        )
    ).to_be_visible()
    expect(page.get_by_role('button', name='Ranking categories')).to_be_visible()
    page.get_by_role('button', name='Create a category').click()
    modal = page.locator('.modal-dialog')
    expect(modal.get_by_role('heading', name='Create a category')).to_be_visible()
    expect(modal.locator('input[name="is_main"]')).to_have_count(0)
    modal.locator('input[name="name"]').fill('Under 12')
    modal.locator('.dropdown-toggle-split').click()
    modal.get_by_role('button', name='Create and add another').click()
    expect(
        modal.get_by_text('Category [Under 12] successfully created!')
    ).to_be_visible()
    modal.locator('input[name="name"]').fill('Women')
    modal.locator('.dropdown-toggle-split').click()
    modal.get_by_role('button', name='Create', exact=True).click()

    category_rows = page.get_by_test_id('championship-category-row')
    expect(category_rows).to_have_count(2)
    expect(category_rows.nth(0)).to_contain_text('Under 12')
    expect(category_rows.nth(1)).to_contain_text('Women')
    # Wait for Sortable: it and the form's ``end`` htmx trigger are wired in
    # the same post-swap pass, so dispatching ``end`` before it loses the event.
    page.wait_for_function(
        "Boolean(Sortable.get(document.getElementById('championship-category-rows')))"
    )
    previous_categories = page.locator('#championship-category-rows').element_handle()
    assert previous_categories
    page.evaluate(
        """
        const rows = document.getElementById('championship-category-rows');
        rows.insertBefore(rows.children[1], rows.children[0]);
        rows.dispatchEvent(new Event('end', {bubbles: true}));
        """
    )
    page.wait_for_function('(element) => !element.isConnected', arg=previous_categories)
    expect(category_rows.nth(0)).to_contain_text('Women')
    expect(category_rows.nth(1)).to_contain_text('Under 12')
    expect(category_rows.nth(0).locator('.championship-category-order')).to_have_text(
        '1'
    )

    under_12_row = category_rows.filter(has_text='Under 12')
    under_12_row.get_by_role('button', name=re.compile('Criteria')).click()
    expect(modal.get_by_role('heading', name='Criteria list')).to_be_visible()
    modal.locator('button.btn-primary', has_text='Add').click()
    expect(modal.get_by_role('heading', name='Create criterion')).to_be_visible()
    _select_criterion_type(modal, 'AGE', 'MIN_AGE_CATEGORY_container')
    expect(modal.locator('#MIN_AGE_CATEGORY_container')).to_be_visible()
    expect(modal.locator('#GENDER_VALUE_container')).to_be_hidden()
    expect(modal.locator('#MIN_RATING_container')).to_be_hidden()
    modal.locator('select[name="MIN_AGE_CATEGORY"]').select_option('U12', force=True)
    modal.locator('select[name="MAX_AGE_CATEGORY"]').select_option('U12', force=True)
    modal.locator('.dropdown-toggle-split').click()
    modal.get_by_role('button', name='Create and add another').click()
    expect(modal.get_by_text('Criterion [Age: U12 – U12]')).to_be_visible()
    _select_criterion_type(modal, 'GENDER', 'GENDER_VALUE_container')
    expect(modal.locator('#GENDER_VALUE_container')).to_be_visible()
    expect(modal.locator('#MIN_AGE_CATEGORY_container')).to_be_hidden()
    modal.locator('select[name="GENDER_VALUE"]').select_option('F', force=True)
    modal.locator('.dropdown-toggle-split').click()
    modal.get_by_role('button', name='Create', exact=True).click()
    expect(modal.get_by_role('heading', name='Criteria list')).to_be_visible()
    expect(modal.get_by_text('Age: U12 – U12', exact=True)).to_be_visible()
    expect(modal.get_by_text('Gender: Women', exact=True)).to_be_visible()
    expect(modal.locator('.modal-footer')).to_have_count(0)
    modal.locator('.btn-close').click()
    expect(under_12_row.get_by_role('button', name='Criteria (2)')).to_be_visible()
    expect(under_12_row).to_contain_text('Age: U12 – U12, Gender: Women')

    page.get_by_test_id('nav-results-tab').click()
    expect(page.get_by_role('heading', name='Rankings')).to_be_visible()
    expect(page.locator('.alert-info')).to_have_count(0)
    ranking_selector = page.get_by_label('Ranking category')
    expect(ranking_selector.locator('option')).to_have_count(3)
    assert ranking_selector.locator('option').all_text_contents() == [
        'General',
        'Women',
        'Under 12',
    ]
    expect(page.get_by_role('heading', name='General ranking')).to_be_visible()
    expect(page.get_by_role('heading', name='Under 12')).to_be_hidden()
    ranking_table = page.locator('#championship-ranking-table-overall')
    expect(ranking_table).to_have_class(re.compile(r'\brankings-table\b'))
    expect(ranking_table).to_have_class(re.compile(r'\bprominent\b'))
    expect(ranking_table.locator('thead').first).to_have_class(
        re.compile(r'\bposition-sticky\b')
    )
    # One rule remains (Total points, best 4 stages); its column shows the acronym.
    expect(ranking_table.locator('th.tie-break')).to_have_count(1)
    expect(ranking_table.locator('th.tie-break').first).to_contain_text('Pts4')
    expect(page.locator('.admin-collection-list')).to_have_count(0)
    stage_count = page.get_by_test_id('championship-stage-count').first
    expect(stage_count).to_have_text('1/1')
    # The stage breakdown is rendered as a table inside the (hidden) popover
    # content div, listing the source tournament and its value.
    stage_popover = page.get_by_test_id(
        'championship-ranking-stage-popover-content'
    ).first
    expect(stage_popover).to_contain_text(TOURNAMENT_NAME)
    ranking_selector.select_option(label='Under 12')
    expect(page.get_by_role('heading', name='Under 12')).to_be_visible()

    page.goto('/championships')
    item = page.get_by_test_id('championships-item').filter(has_text=CHAMPIONSHIP_NAME)
    expect(item).to_be_visible()
    delete_button = item.get_by_role('button', name='Delete')
    expect(delete_button).to_be_visible()
    delete_button.click()
    modal = page.locator('.modal-dialog')
    expect(modal).to_be_visible()
    modal.get_by_role('checkbox').check()
    modal.locator('#delete-button').click()
    expect(
        page.get_by_test_id('championships-item').filter(has_text=CHAMPIONSHIP_NAME)
    ).to_have_count(0)
    expect(page.locator('#nav-championship_archives-tab')).to_be_enabled()
    archive_row = page.get_by_role('row').filter(has_text=CHAMPIONSHIP_NAME)
    expect(archive_row).to_be_visible()
    archive_row.get_by_role('button', name='Restore').click()
    expect(page.locator('#nav-championships-tab')).to_be_enabled()
    expect(
        page.get_by_test_id('championships-item').filter(has_text=CHAMPIONSHIP_NAME)
    ).to_be_visible()


@pytest.mark.e2e
def test_team_championship_uses_team_ranking_controls(page: Page):
    page.goto('/championships')
    page.get_by_role('button', name='Create a championship', exact=True).first.click()
    modal = page.locator('.modal-dialog')
    modal.locator('input[name="name"]').fill(TEAM_CHAMPIONSHIP_NAME)
    modal.locator('select[name="competitor_type"]').select_option('TEAM', force=True)
    modal.get_by_test_id('championship-create-submit').click()

    expect(page.get_by_test_id('nav-competitors-tab')).to_be_visible()
    page.get_by_test_id('nav-sources-tab').click()
    page.get_by_role('button', name='Add a tournament').click()
    expect(
        page.get_by_text('There are no other compatible tournaments')
    ).to_be_visible()
    page.get_by_role('button', name='Close').click()
    page.get_by_test_id('nav-competitors-tab').click()
    expect(page.get_by_role('button', name='Merge selected teams')).to_be_disabled()
    competitors_table = page.locator('#championship-competitors-table')
    expect(competitors_table).to_be_visible()
    expect(competitors_table.get_by_role('columnheader', name='Cat.')).to_have_count(0)
    expect(competitors_table.get_by_role('columnheader', name='Gen.')).to_have_count(0)
    page.get_by_test_id('nav-configuration-tab').click()
    expect(page.get_by_role('button', name='Team score basis')).to_be_visible()
    expect(page.get_by_role('button', name='Age categories')).to_have_count(0)
    expect(page.get_by_role('button', name='Ranking categories')).to_have_count(0)
    page.get_by_test_id('nav-results-tab').click()
    ranking_selector = page.get_by_label('Ranking category')
    expect(ranking_selector).to_be_visible()
    expect(ranking_selector.locator('option')).to_have_count(1)
    expect(ranking_selector).to_have_value('overall')
    expect(page.get_by_role('heading', name='General ranking')).to_be_visible()
