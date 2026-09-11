from datetime import date
from data.event import Event
from data.player import PlayerRating
from database.sqlite.event.event_database import EventDatabase
import pytest
from playwright.sync_api import Page, expect, APIRequestContext
from tests.test_config import TestUtils
from utils.enum import PlayerGender, PlayerTitle, TournamentRating

EVENT_ID = 'event-test-players'
TOURNAMENT_ID = 'tournament-test-players'
SCREEN_ID = 'test-screen'


@pytest.fixture(scope='module', autouse=True)
def setup(api_request_context: APIRequestContext):
    TestUtils.create_event(EVENT_ID, via_api_request_context=api_request_context)
    TestUtils.create_tournament(
        EVENT_ID, TOURNAMENT_ID, via_api_request_context=api_request_context
    )
    yield

    TestUtils.delete_event(EVENT_ID, via_api_request_context=api_request_context)


@pytest.mark.e2e
class TestPlayersFunctionality:
    def test_create_update_delete_player(self, page: Page):
        page.goto(f'/event/{EVENT_ID}/players')
        page.get_by_test_id('add-player-button').click()
        modal = page.locator('#player-modal:not(.htmx-added)')
        expect(modal).to_be_visible()
        modal.get_by_test_id('last-name').fill('doe')
        modal.get_by_test_id('first-name').fill('john')
        modal.get_by_test_id('date-of-birth').fill('2000-10-30')
        modal.get_by_test_id('gender').select_option(
            str(PlayerGender.MAN.value), force=True
        )
        modal.get_by_test_id('club').fill('SC Club')
        modal.get_by_test_id('federation').select_option('FRA', force=True)
        modal.get_by_test_id('fixed').fill('100')
        TestUtils.button_by_text(modal, 'Add manual estimated ratings').click()
        modal.get_by_test_id('standard-rating-estimated').fill('1000')
        modal.get_by_test_id('rapid-rating-national').fill('1500')
        modal.get_by_test_id('blitz-rating-fide').fill('2000')
        modal.get_by_test_id('blitz-rating-k').fill('20')
        modal.get_by_test_id('title').select_option(
            str(PlayerTitle.GRANDMASTER.value), force=True
        )
        modal.get_by_test_id('mail').fill('john.doe@sharly-chess.com')
        # modal.get_by_test_id('phone').fill("0123456789")
        modal.get_by_test_id('owed').fill('10')
        modal.get_by_test_id('paid').fill('20')
        modal.get_by_test_id('comment').fill('Comment')
        modal.get_by_test_id('create-button').click()

        modal = page.locator('.modal-dialog')
        expect(modal).not_to_be_visible()

        # Test that the player was created

        with EventDatabase(EVENT_ID) as database:
            event = Event(database.load_stored_event())
            assert event.player_count == 1
            player = next(iter(event.sorted_players))
            assert player.last_name == 'DOE'
            assert player.first_name == 'John'
            assert player.date_of_birth == date(2000, 10, 30)
            assert player.gender == PlayerGender.MAN
            assert player.club.name == 'SC Club'
            assert player.fixed == 100
            assert player.ratings == {
                TournamentRating.STANDARD: PlayerRating(estimated=1000),
                TournamentRating.RAPID: PlayerRating(national=1500),
                TournamentRating.BLITZ: PlayerRating(fide=2000, k_factor=20),
            }
            assert player.title == PlayerTitle.GRANDMASTER
            assert player.federation.name == 'FRA'
            assert player.mail == 'john.doe@sharly-chess.com'
            assert player.owed == 10
            assert player.paid == 20
            assert player.comment == 'Comment'

        # Update the player

        player_id = player.id

        row = page.locator(f'tr#player-{player_id}')
        expect(row).to_contain_text('DOE John')
        menu_button = row.locator('td:nth-child(1)').locator('button')
        menu_button.click()
        edit_link = row.get_by_text('Edit')
        edit_link.click()
        modal = page.locator('#player-modal:not(.htmx-added)')
        expect(modal).to_be_visible()
        # The coefficients left empty are estimated from the rating and the age.
        expect(modal.get_by_test_id('standard-rating-k')).to_have_attribute(
            'placeholder', '40'
        )
        expect(modal.get_by_test_id('blitz-rating-k')).to_have_attribute(
            'placeholder', '20'
        )
        modal.get_by_test_id('last-name').fill('hoe')
        modal.locator('button[type=submit]').click()

        row = page.locator(f'tr#player-{player_id}')
        expect(row).to_contain_text('HOE John')

        # Delete the player

        menu_button = row.locator('td:nth-child(1)').locator('button')
        menu_button.click()
        delete_link = row.get_by_text('Delete')
        delete_link.click()
        modal = page.locator('#delete-modal:not(.htmx-added)')
        expect(modal).to_be_visible()
        modal.locator('button[type=submit]').click()
        expect(page.locator(f'tr#player-{player_id}')).not_to_be_attached()

        # Test that the player was deleted

        with EventDatabase(EVENT_ID) as database:
            event = Event(database.load_stored_event())
            assert event.player_count == 0
