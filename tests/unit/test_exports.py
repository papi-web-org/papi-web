import xml.etree.ElementTree as ET
from sqlite3 import IntegrityError
from unittest import TestCase
from unittest.mock import PropertyMock, patch

import pytest

from data.event import Event
from data.loader import EventLoader
from data.tie_breaks import TieBreakManager, TieBreak
from data.tie_breaks.tie_breaks import (
    PointsTieBreak,
    StandardBuchholzTieBreak,
    WinsTieBreak,
)
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredAccount, StoredRole
from plugins.chess_results.chess_results_mappers import ChessResultsTieBreak
from plugins.chess_results.chess_results_session import ChessResultsSession
from plugins.chess_results.utils import CRUtils
from plugins.ffe.ffe_tie_breaks import PapiPerformanceTieBreak
from plugins.ffe.papi_converter import PapiConverter
from tests.test_config import TestUtils
from utils.enum import RoleType


EVENT_ID = 'test-tournament-exporters-event'
TOURNAMENT_ID = 'tournament-test-exporters'


@pytest.mark.unit
class TournamentExporterTestCase(TestCase):
    event: Event
    tournament: Tournament

    def setUp(self):
        super().setUp()
        TestUtils.create_event(EVENT_ID)
        TestUtils.create_tournament(EVENT_ID, TOURNAMENT_ID, json_file='tec-swiss')
        self.event = EventLoader().load_event(EVENT_ID)
        self.tournament = self.event.tournaments_by_name[TOURNAMENT_ID]

    def tearDown(self):
        TestUtils.delete_event(EVENT_ID)
        super().tearDown()

    # -------------------------------------------------------------------------
    # Chess-Results
    # -------------------------------------------------------------------------

    def test_chess_results_all_tie_breaks_implemented(self):
        for tie_break in TieBreakManager(self.event).objects():
            try:
                ChessResultsTieBreak.from_tie_break(self.tournament, tie_break)
            except NotImplementedError:
                self.fail(f'Tie-break [{tie_break.id}] not handled.')

    def test_chess_results_exports_each_arbiter_role(self):
        assert self.tournament.id is not None

        account_by_role = {}
        for role_type, first_name in (
            (RoleType.CHIEF_ARBITER, 'Chief'),
            (RoleType.DEPUTY_ARBITER, 'Deputy'),
            (RoleType.ARBITER, 'Simple'),
        ):
            account_by_role[role_type] = self.event.create_account(
                StoredAccount(
                    id=None,
                    active=True,
                    first_name=first_name,
                    last_name='Arbiter',
                    stored_roles=[
                        StoredRole(
                            account_id=None,
                            role=role_type.value,
                            tournament_ids=[self.tournament.id],
                        )
                    ],
                )
            )

        with patch.object(CRUtils, 'encrypt', return_value='encrypted-test-sid'):
            xml = ChessResultsSession(self.tournament).build_tournament_xml(
                self.tournament,
                sid='test-sid',
                tnr='test-key',
                creator_id='test-creator',
                state=None,
            )
        tournament_data = ET.fromstring(xml).find('./tournamentdata/tournament')
        assert tournament_data is not None
        assert tournament_data.attrib['chiefarbiter'] == 'Arbiter, Chief'
        assert tournament_data.attrib['deputyarbiter'] == 'Arbiter, Deputy'
        assert tournament_data.attrib['arbiter'] == 'Arbiter, Simple'
        assert self.tournament.arbiters == [account_by_role[RoleType.ARBITER]]

        simple_arbiter = account_by_role[RoleType.ARBITER]
        with EventDatabase(EVENT_ID, write=True) as database:
            with self.assertRaises(IntegrityError):
                database.add_stored_roles(
                    simple_arbiter.id,
                    RoleType.DEPUTY_ARBITER.value,
                    [self.tournament.id],
                )

    def test_chess_results_getkey_escapes_tournament_name(self):
        """A tournament name with XML metacharacters (e.g. ``R&B``) must be
        escaped in the GETKEY payload, otherwise Chess-Results rejects the
        request with an XML parse error."""

        class FakeResponse:
            text = (
                '<?xml version="1.0"?><chessresults>'
                '<result status="OK" key="new-key" /></chessresults>'
            )

            def raise_for_status(self):
                pass

        captured: dict = {}

        def fake_post(url, params=None, data=None, headers=None):
            captured['data'] = data
            return FakeResponse()

        with (
            patch.object(
                type(self.tournament),
                'full_name',
                new_callable=PropertyMock,
                return_value='Internationaux R&B - <Blitz>',
            ),
            patch.object(CRUtils, 'encrypt', return_value='enc'),
            patch(
                'plugins.chess_results.chess_results_session.requests.post',
                side_effect=fake_post,
            ),
        ):
            key = ChessResultsSession(self.tournament).get_new_tournament_key(
                13, 'sid', 'creator', self.tournament
            )

        assert key == 'new-key'
        # The payload must be well-formed XML with the name preserved.
        root = ET.fromstring(captured['data'])
        getkey = root.find('getkey')
        assert getkey is not None
        assert getkey.attrib['tournament'] == 'Internationaux R&B - <Blitz>'

    # -------------------------------------------------------------------------
    # Papi
    # -------------------------------------------------------------------------

    def _set_tie_breaks(self, tie_breaks: list[TieBreak]):
        """Rank on the points, then on *tie_breaks* — the points being a
        criterion of their own now, they are stated rather than implied."""
        ordered = [PointsTieBreak()] + tie_breaks
        self.tournament.tie_breaks_by_id = {
            index + 1: tie_break for index, tie_break in enumerate(ordered)
        }

    def test_papi_manual_tie_break_pairing_number(self):
        """Check that the pairing number is added as a tie-break if a spot is available."""
        self._set_tie_breaks([PapiPerformanceTieBreak()])
        papi_data = PapiConverter().tournament_to_papi_data(self.tournament)
        self.assertEqual(papi_data.variables.tiebreak2, 'Manuel')
        expected_fixed_by_player = {
            'ALYX': 1016,
            'BRUNO': 1015,
            'CHARLINE': 1014,
            'DAVID': 1013,
            'HELENE': 1012,
            'FRANCK': 1011,
            'GENEVIEVE': 1010,
            'IRINA': 1009,
            'JESSICA': 1008,
            'LAIS': 1007,
            'MARIA': 1006,
            'NICK': 1005,
            'OPAL': 1004,
            'PAUL': 1003,
            'REINE': 1002,
            'STEPHAN': 1001,
        }
        for player in papi_data.players:
            self.assertIn(player.lastName, expected_fixed_by_player)
            self.assertEqual(
                expected_fixed_by_player[player.lastName], player.fixedBoard
            )

    def test_papi_incompatible_tie_breaks_replaced(self):
        """Check that the rankings replaces the first incompatible tie-break."""
        self._set_tie_breaks(
            [
                WinsTieBreak(),
                StandardBuchholzTieBreak(),
                PapiPerformanceTieBreak(),
            ]
        )
        papi_data = PapiConverter().tournament_to_papi_data(self.tournament)

        self.assertEqual(papi_data.variables.tiebreak1, 'Nombre de Victoires')
        self.assertEqual(papi_data.variables.tiebreak2, 'Manuel')
        self.assertEqual(papi_data.variables.tiebreak3, None)
        expected_fixed_by_player = {
            'BRUNO': 1016,
            'STEPHAN': 1015,
            'CHARLINE': 1014,
            'DAVID': 1013,
            'ALYX': 1012,
            'FRANCK': 1011,
            # Maria / Irina swapped from 03/2026 FIDE tie-breaks dummy update
            # Maria BH -1 --> Forfeit win R4 - 1 * (dummy capped to opponent score 1.5 instead of 2.5)
            'IRINA': 1010,
            'MARIA': 1009,
            'HELENE': 1008,
            'REINE': 1007,
            'NICK': 1006,
            'PAUL': 1005,
            'GENEVIEVE': 1004,
            'OPAL': 1003,
            'JESSICA': 1002,
            'LAIS': 1001,
        }
        for player in papi_data.players:
            self.assertIn(player.lastName, expected_fixed_by_player)
            self.assertEqual(
                expected_fixed_by_player[player.lastName], player.fixedBoard
            )

    def test_papi_tie_break_warning_ignores_leading_points(self):
        """A leading PTS takes no Papi slot, so it must not trigger the
        'values will not appear' warning when the real tie-breaks all fit."""
        warning = PapiConverter.check_tiebreaks_warning(
            [
                PointsTieBreak(),
                WinsTieBreak(),
                PapiPerformanceTieBreak(),
            ]
        )
        self.assertIsNone(warning)

    def test_papi_tie_break_warning_when_points_not_first(self):
        """PTS anywhere but first cannot be expressed in Papi, so warn."""
        warning = PapiConverter.check_tiebreaks_warning(
            [WinsTieBreak(), PointsTieBreak()]
        )
        self.assertIsNotNone(warning)
