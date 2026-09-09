"""Test configuration and utilities."""

import re
import shutil
import time
from enum import StrEnum
from pathlib import Path
from typing import Callable, Dict, Optional, Any
from urllib import parse

from playwright.sync_api import Page, Locator, APIRequestContext, APIResponse, expect

from common import BASE_DIR, TMP_DIR
from data.board import PlayerRatingType
from data.input_output.tournament_importer_options import FileOption
from data.loader import EventLoader
from data.pairings.variations import StandardSwissVariation
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredDisplayController,
    StoredEvent,
    StoredFamily,
    StoredTournament,
)
from plugins.ffe.ffe_tournament_importers import PapiJsonTournamentImporter
from data.screens.screen_types import (
    CheckInScreenType,
    InputScreenType,
    BoardsScreenType,
    PlayersScreenType,
    ResultsScreenType,
    RankingScreenType,
    ImageScreenType,
)
from utils.enum import (
    PlayersScreenPlayerFormat,
    PlayersScreenBoardFormat,
    PlayersScreenOpponentFormat,
)


class ScreenType(StrEnum):
    """Screen-type ids used by the tests to create screens and families."""

    CHECK_IN = CheckInScreenType.static_id()
    INPUT = InputScreenType.static_id()
    BOARDS = BoardsScreenType.static_id()
    PLAYERS = PlayersScreenType.static_id()
    RESULTS = ResultsScreenType.static_id()
    RANKING = RankingScreenType.static_id()
    IMAGE = ImageScreenType.static_id()


class TestConfig:
    """Configuration for test environment."""

    # Server configuration
    TEST_HOST = '127.0.0.1'  # Use IP instead of localhost
    TEST_PORT = 9000
    TEST_TIMEOUT = 30  # seconds to wait for server startup

    # Global timeout for all global expect calls.
    # NOTE(Amaras): I set to 10s = 10_000 ms because we often had false-positive failures.
    # Hopefully 10s is long enough to ensure all failures are real failure cases.
    expect.set_options(timeout=10_000)

    @classmethod
    def get_test_env_vars(cls) -> Dict[str, str]:
        """Get environment variables for test environment."""
        return {
            'TEST_ENV': 'true',
        }


class TestUtils:
    """Utility functions for tests."""

    event_defaults = {
        'federation': 'FRA',
        'public': True,
        'location': 'Paris',
        'player_rating_type': PlayerRatingType.FIDE.value,
        'background_color': '#ffffff',
        'message_text': '',
        'message_color': '#000000',
        'message_background_color': '#ffffff',
        'prize_currency': 'EUR',
        'timer_colors': {i: None for i in range(1, 4)},
        'timer_delays': {i: None for i in range(1, 4)},
        'plugin_data': {},
    }

    @staticmethod
    def prepare_form_data(data: dict[str, object]) -> str:
        out: dict[str, object] = {}

        for k, v in data.items():
            if v is None:
                continue
            if isinstance(v, bool):
                if v:
                    # HTML checkbox semantics
                    out[k] = 'on'
                else:
                    continue
            elif isinstance(v, (list, tuple)):
                # leave as sequence; urlencode(doseq=True) expands it
                out[k] = [str(x) for x in v]
            else:
                out[k] = str(v)

        return parse.urlencode(out, doseq=True)

    @staticmethod
    def check_api_response(response: APIResponse):
        assert response.ok
        body = response.body().decode('utf-8')

        # Look for Internal Server Error in an <h1>
        if re.search(
            r'<h1>\s*500\s*[-–—]\s*Internal Server Error\s*</h1>', body, re.IGNORECASE
        ):
            raise AssertionError('Server 500 Internal Server Error page detected')

        # Match divs with class containing 'invalid-feedback', extract id and inner text
        matches = re.findall(
            r'<div[^>]*\bid="([^"]+)"[^>]*class="[^"]*\binvalid-feedback\b[^"]*"[^>]*>(.*?)</div>',
            body,
            re.DOTALL | re.IGNORECASE,
        )

        # Create list of (id, trimmed text)
        errors = [(div_id, text.strip()) for div_id, text in matches]

        assert not errors, errors

    @staticmethod
    def wait_for_htmx_idle(page, timeout=5000):
        page.wait_for_function(
            "() => !document.querySelector('.htmx-request, .htmx-swapping')",
            timeout=timeout,
        )

    @staticmethod
    def fill_and_confirm(locator: Locator, value: str, attempts: int = 10):
        """Fill a field and make sure the value holds.

        A field in a freshly-swapped modal can silently drop the first fill
        while the form is still initialising (the modal runs its init a beat
        after the swap), so re-fill until the value sticks.
        """
        for attempt in range(attempts):
            locator.fill(value)
            try:
                expect(locator).to_have_value(value, timeout=250)
                return
            except AssertionError:
                if attempt == attempts - 1:
                    raise

    @staticmethod
    def poll_expect_with_reload(
        page,
        assertion: Callable[[], None],
        retries: int = 5,
        delay_secs: float = 0.2,
    ):
        for attempt in range(retries):
            page.reload()
            try:
                assertion()
                return
            except AssertionError:
                if attempt == retries - 1:
                    raise
                time.sleep(delay_secs)

    #: A fully-migrated, empty event database, built once and copied for
    #: every event a test creates. See :meth:`_event_template_file`.
    _event_template_path: Path | None = None

    @classmethod
    def _event_template_file(cls) -> Path:
        """An empty event database to copy, built on first use."""
        if cls._event_template_path is None:
            source = EventDatabase('event-template')
            source.file.unlink(missing_ok=True)
            source.create()
            template = TMP_DIR / source.file.name
            template.unlink(missing_ok=True)
            source.file.rename(template)
            cls._event_template_path = template
        return cls._event_template_path

    @classmethod
    def create_event(
        cls,
        uniq_id: str,
        via_api_request_context: APIRequestContext | None = None,
        overrides: Optional[dict] = None,
    ):
        overrides = overrides or {}

        # Provide defaults
        defaults = {
            **cls.event_defaults,
            'uniq_id': uniq_id,
            'name': uniq_id,
        }
        if via_api_request_context:
            defaults |= {
                'plugin_ffe': 'on',
            }
        else:
            defaults |= {
                'enabled_plugins': ['ffe'],
            }

        # Merge overrides
        data = {**defaults, **overrides}

        database = EventDatabase(uniq_id)
        database.file.unlink(missing_ok=True)

        if via_api_request_context:
            form_data = cls.prepare_form_data(data)
            res = via_api_request_context.post(
                '/home/create-event',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=form_data,
            )
            cls.check_api_response(res)
        else:
            shutil.copyfile(cls._event_template_file(), database.file)
            stored_event = StoredEvent(**data)
            with EventDatabase(uniq_id, write=True) as event_database:
                event_database.update_stored_event(stored_event)

    @classmethod
    def delete_event(
        cls,
        uniq_id: str,
        via_api_request_context: APIRequestContext | None = None,
    ):
        if via_api_request_context:
            res = via_api_request_context.delete(
                f'/current_events/event-delete/{uniq_id}',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
            )
            TestUtils.check_api_response(res)
        else:
            EventDatabase(uniq_id).delete()

    @classmethod
    def create_tournament(
        cls,
        event_uniq_id: str,
        name: str,
        via_api_request_context: APIRequestContext | None = None,
        overrides: dict | None = None,
        json_file: str | None = None,
    ):
        overrides = overrides or {}

        # Provide defaults
        defaults: dict[str, Any] = {
            'id': None,
            'name': name,
            'time_control_trf25': None,
            'record_illegal_moves': None,
            'first_board_number': None,
            'paired_bye_result': None,
            'max_byes': None,
            'last_rounds_no_byes': None,
            'location': None,
            'pairing': StandardSwissVariation.static_id(),
            'current_round': None,
            'rounds': 7,
            'rating': 1,
            'stored_prize_groups': [],
            'plugin_data': None,
        }

        # Merge overrides
        data = {**defaults, **overrides}

        if via_api_request_context:
            data['SWISS_pairing_variation'] = StandardSwissVariation.static_id()
            form_data = cls.prepare_form_data(data)
            res = via_api_request_context.post(
                f'/tournament-create/{event_uniq_id}',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=form_data,
            )
            cls.check_api_response(res)
        else:
            with EventDatabase(event_uniq_id, write=True) as event_database:
                stored_tournament = StoredTournament(**data)
                event_database.add_stored_tournament(stored_tournament)

        with EventDatabase(event_uniq_id) as event_database:
            tournaments = event_database.load_stored_tournaments()
            stored_tournament = next(t for t in tournaments if t.name == name)

        if json_file:
            json_path = BASE_DIR / 'tests' / 'json' / f'{json_file}.json'
            assert json_path.exists(), f'Missing test file: {json_path}'

            if via_api_request_context:
                # Send as multipart/form-data with a real file field named "file"
                res = via_api_request_context.post(
                    f'/tournament-import/{event_uniq_id}/{stored_tournament.id}/ffe-PAPI_JSON',
                    multipart={
                        # UploadFile field name in your handler is "file"
                        'file': {
                            'name': f'{json_file}.json',
                            'mimeType': 'application/json',
                            'buffer': json_path.read_bytes(),
                        },
                    },
                )
                cls.check_api_response(res)
            else:
                event = EventLoader().load_event(event_uniq_id)
                importer = PapiJsonTournamentImporter([FileOption(json_path)])
                importer.load_tournament(event, event.tournaments_by_name[name])

        return stored_tournament

    @classmethod
    def delete_tournament(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        stored_tournament: StoredTournament,
    ):
        res = api_request_context.delete(
            f'/tournament-delete/{event_uniq_id}/{stored_tournament.id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        cls.check_api_response(res)

    @classmethod
    def create_screen(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        name: str,
        screen_type: ScreenType,
        overrides: Optional[dict] = None,
    ):
        overrides = overrides or {}

        # Provide defaults
        defaults: dict[str, Any] = {
            'id': None,
            'name': name,
            'init_set_tournament_id': None,
            'columns': None,
            'font_size': None,
            'menu_text': None,
            'timer_id': None,
            'input_exit_button': None,
            'players_show_unpaired': None,
            'players_player_format': PlayersScreenPlayerFormat.NAME_RATING_TYPE_POINTS
            if screen_type == ScreenType.PLAYERS
            else None,
            'players_board_format': PlayersScreenBoardFormat.MINIMAL
            if screen_type == ScreenType.PLAYERS
            else None,
            'players_opponent_format': PlayersScreenOpponentFormat.NAME_RATING_TYPE_POINTS
            if screen_type == ScreenType.PLAYERS
            else None,
            'results_limit': None,
            'results_max_age': None,
            'background_color': None,
            'results_tournament_ids': [],
            'ranking_crosstable': False,
            'ranking_round': None,
            'ranking_min_points': None,
            'ranking_max_points': None,
            'stored_screen_sets': [],
            'last_update': 0.0,
            'public': True,
            'message_default': True,
            'message_text': None,
            'errors': {},
        }

        # Merge overrides
        data = {**defaults, **overrides}

        form_data = cls.prepare_form_data(data)
        res = api_request_context.post(
            f'/screen-create/{event_uniq_id}/{screen_type.value}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form_data,
        )
        cls.check_api_response(res)

        with EventDatabase(event_uniq_id) as event_database:
            stored_screens = event_database.load_stored_screens()
            stored_screen = next(s for s in stored_screens if s.name == name)
            return stored_screen

    @classmethod
    def delete_screen(
        cls, api_request_context: APIRequestContext, event_uniq_id: str, screen_id: int
    ):
        res = api_request_context.delete(
            f'/screen-delete/{event_uniq_id}/{screen_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        cls.check_api_response(res)

    @classmethod
    def create_family(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        tournament: StoredTournament,
        uniq_id: str,
        family_type: ScreenType,
        overrides: Optional[dict] = None,
    ):
        overrides = overrides or {}

        # Provide defaults
        defaults: dict[str, Any] = {
            'id': None,
            'uniq_id': uniq_id,
            'name': uniq_id,
            'tournament_id': tournament.id,
            'columns': None,
            'font_size': None,
            'menu_text': '',
            'timer_id': None,
            'input_exit_button': None,
            'players_show_unpaired': None,
            'players_player_format': PlayersScreenPlayerFormat.NAME_RATING_TYPE_POINTS
            if family_type == ScreenType.PLAYERS
            else None,
            'players_board_format': PlayersScreenBoardFormat.MINIMAL
            if family_type == ScreenType.PLAYERS
            else None,
            'players_opponent_format': PlayersScreenOpponentFormat.NAME_RATING_TYPE_POINTS
            if family_type == ScreenType.PLAYERS
            else None,
            'ranking_crosstable': False,
            'ranking_round': None,
            'ranking_min_points': None,
            'ranking_max_points': None,
            'first': None,
            'last': None,
            'parts': None,
            'number': None,
            'last_update': 0.0,
            'public': True,
            'message_default': True,
            'message_text': None,
            'errors': {},
        }

        # Merge overrides
        data = {**defaults, **overrides}

        with EventDatabase(event_uniq_id) as event_database:
            existing_family_ids = {
                family.id for family in event_database.load_stored_families()
            }

        form_data = cls.prepare_form_data(data)
        res = api_request_context.post(
            f'/family-create/{event_uniq_id}/{family_type.value}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form_data,
        )
        cls.check_api_response(res)

        with EventDatabase(event_uniq_id) as event_database:
            stored_families = event_database.load_stored_families()
            stored_family = next(
                (f for f in stored_families if f.uniq_id == uniq_id), None
            )
            if stored_family is None:
                stored_family = next(
                    (f for f in stored_families if f.id not in existing_family_ids),
                    None,
                )
            if stored_family is None:
                stored_family = next(
                    (
                        f
                        for f in stored_families
                        if f.type == family_type.value
                        and f.tournament_id == tournament.id
                        and f.name == data['name']
                    ),
                    None,
                )
            if stored_family is None:
                body = res.body().decode('utf-8', errors='replace')
                raise AssertionError(
                    f'Family [{data["name"]}] was not created. '
                    f'Response status: {res.status}. Body: {body[:1000]}'
                )
            return stored_family

    @classmethod
    def delete_family(
        cls, api_request_context: APIRequestContext, event_uniq_id: str, family_id: int
    ):
        res = api_request_context.delete(
            f'/family-delete/{event_uniq_id}/{family_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        cls.check_api_response(res)

    @classmethod
    def update_family_name(
        cls,
        event_uniq_id: str,
        stored_family: StoredFamily,
        name: str,
    ) -> StoredFamily:
        stored_family.name = name
        with EventDatabase(event_uniq_id, write=True) as event_database:
            return event_database.update_stored_family(stored_family)

    @classmethod
    def create_rotator(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        name: str,
        overrides: Optional[dict] = None,
        screen_ids: list | None = None,
        family_ids: list | None = None,
    ) -> int:
        overrides = overrides or {}

        # Provide defaults
        defaults = {
            'name': name,
            'public': True,
            'delay': None,
            'message_text_checkbox': True,
            'message_text': '',
        }

        # Merge overrides
        data = {**defaults, **overrides}

        form_data = cls.prepare_form_data(data)
        res = api_request_context.post(
            f'/rotator-create/{event_uniq_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form_data,
        )
        cls.check_api_response(res)
        with EventDatabase(event_uniq_id) as event_database:
            stored_rotators = event_database.load_stored_rotators()
        stored_rotator = next(r for r in stored_rotators if r.name == name)
        assert stored_rotator.id is not None

        for screen_id in screen_ids or []:
            form_data = cls.prepare_form_data({'screen_id': screen_id})
            res = api_request_context.post(
                f'/rotating-screens/create-screen/{event_uniq_id}/{stored_rotator.id}',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=form_data,
            )
            cls.check_api_response(res)

        for family_id in family_ids or []:
            form_data = cls.prepare_form_data({'family_id': family_id})
            res = api_request_context.post(
                f'/rotating-screens/create-family/{event_uniq_id}/{stored_rotator.id}',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data=form_data,
            )
            cls.check_api_response(res)
        return stored_rotator.id

    @classmethod
    def delete_rotator(
        cls, api_request_context: APIRequestContext, event_uniq_id: str, rotator_id: int
    ):
        res = api_request_context.delete(
            f'/rotator-delete/{event_uniq_id}/{rotator_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        cls.check_api_response(res)

    @classmethod
    def create_display_controller(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        name: str,
        overrides: Optional[dict] = None,
        screen_uniq_id: str | None = None,
        rotator_name: str | None = None,
    ) -> StoredDisplayController:
        overrides = overrides or {}
        defaults = {
            'name': name,
            'public': True,
        }
        data = {**defaults, **overrides}

        form_data = cls.prepare_form_data(data)
        res = api_request_context.post(
            f'/display-controller-create/{event_uniq_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=form_data,
        )
        cls.check_api_response(res)
        with EventDatabase(event_uniq_id) as event_database:
            stored_display_controllers = (
                event_database.load_stored_display_controllers()
            )
            stored_display_controller = next(
                controller
                for controller in stored_display_controllers
                if controller.name == name
            )
        assert stored_display_controller.id is not None

        if screen_uniq_id or rotator_name:
            if screen_uniq_id and rotator_name:
                raise ValueError('Assign either a screen or a rotator, not both.')
            assigned_type = 'screen' if screen_uniq_id else 'rotator'
            object_uniq_id = screen_uniq_id or rotator_name
            assert object_uniq_id is not None
            res = api_request_context.patch(
                f'/display-controller-assign/{event_uniq_id}/'
                f'{stored_display_controller.id}/{assigned_type}/'
                f'{parse.quote(object_uniq_id, safe="")}',
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
            )
            cls.check_api_response(res)
            with EventDatabase(event_uniq_id) as event_database:
                reloaded_display_controller = (
                    event_database.get_stored_display_controller(
                        stored_display_controller.id
                    )
                )
            assert reloaded_display_controller is not None
            stored_display_controller = reloaded_display_controller

        return stored_display_controller

    @classmethod
    def delete_display_controller(
        cls,
        api_request_context: APIRequestContext,
        event_uniq_id: str,
        display_controller_id: int,
    ):
        res = api_request_context.delete(
            f'/display-controller-delete/{event_uniq_id}/{display_controller_id}',
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        cls.check_api_response(res)

    @staticmethod
    def button_by_text(obj: Page | Locator, text: str) -> Locator:
        """
        Returns a button by visible text (case-insensitive), ignoring icons or extra whitespace.
        """
        return obj.get_by_role(
            'button', name=re.compile(rf'\b{text.replace("/", "\\/")}\b', re.IGNORECASE)
        )

    @staticmethod
    def take_screenshot(page, name: str):
        """Take a screenshot for debugging."""
        screenshot_dir = Path(__file__).parent / 'screenshots'
        screenshot_dir.mkdir(exist_ok=True)
        screenshot_path = screenshot_dir / f'{name}.png'
        return page.screenshot(path=screenshot_path)
