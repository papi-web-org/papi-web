import tempfile
from datetime import date
from pathlib import Path
from unittest import TestCase

import pytest

from data.event import Event
from data.input_output import TournamentImporter
from data.input_output.tournament_importer_options import FileOption
from data.input_output.trf.trf_data import (
    TrfGame,
    TrfNationalPlayer,
    TrfPlayer,
    TrfRoundBye,
    TrfTeam,
    TrfTeamPABs,
    TrfTournament,
)
from data.input_output.trf.trf_importer import TrfTournamentImporter
from data.input_output.trf.trf_serializer import TrfSerializer
from data.loader import EventLoader
from data.pairings.settings import ColorSeedSetting
from data.pairings.variations import StandardTeamSwissVariation
from data.tournament import Tournament
from plugins.ffe.ffe_tournament_importers import (
    PapiJsonTournamentImporter,
    PapiTournamentImporter,
)
from plugins.ffe.utils import FFEUtils, PlayerFFELicence
from data.pairings.acceleration import BakuSwissVariation
from tests.test_config import TestUtils
from utils.enum import (
    BoardColor,
    EventType,
    PlayerGender,
    PlayerRatingType,
    PlayerTitle,
    Result,
    ScoreType,
    TeamByeType,
    TeamColourType,
)

EVENT_ID = 'test-tournament-importers-event'
BASE_PATH = Path(__file__).parent


@pytest.mark.unit
class TournamentImporterTestCase(TestCase):
    event: Event

    def setUp(self):
        super().setUp()
        TestUtils.create_event(EVENT_ID)
        self.event = EventLoader().load_event(EVENT_ID)

    def tearDown(self):
        TestUtils.delete_event(EVENT_ID)
        super().tearDown()

    def _import_tournament(self, importer: TournamentImporter) -> Tournament:
        tournament_id = importer.load_tournament(self.event)
        self.event = EventLoader().load_event(EVENT_ID)
        return self.event.tournaments_by_id[tournament_id]

    def test_trf_import(self):
        file_path = BASE_PATH / 'trf-import-test.trf'
        importer = TrfTournamentImporter([FileOption(file_path)])
        tournament = self._import_tournament(importer)
        self.assertEqual(tournament.name, 'TRF import test')
        self.assertEqual(tournament.location, 'Sharly-Chess HQ')
        first_day = date(year=2025, month=9, day=13)
        second_day = date(year=2025, month=9, day=14)
        self.assertEqual(tournament.start_date, first_day)
        self.assertEqual(tournament.stop_date, second_day)
        date_by_round = {
            round_: datetime_.date() if datetime_ else None
            for round_, datetime_ in tournament.round_datetimes.items()
        }
        expected_date_by_round = {
            1: first_day,
            2: first_day,
            3: first_day,
            4: second_day,
            5: second_day,
        }
        self.assertEqual(date_by_round, expected_date_by_round)
        self.assertEqual(tournament.rounds, 5)
        self.assertEqual(
            tournament.pairing_settings.get(ColorSeedSetting().id), BoardColor.BLACK
        )
        self.assertEqual(tournament.player_rating_type, PlayerRatingType.NATIONAL)
        self.assertEqual(tournament.pairing_variation.id, BakuSwissVariation().id)

        self.assertEqual(len(tournament.players), 16)
        player = tournament.tournament_players_by_pairing_number.get(1)
        assert player is not None
        self.assertEqual(player.gender, PlayerGender.MAN)
        self.assertEqual(player.title, PlayerTitle.GRANDMASTER)
        self.assertEqual(player.last_name, 'CARLSEN')
        self.assertEqual(player.first_name, 'Magnus')
        self.assertEqual(player.fide_rating_value, 2840)
        self.assertEqual(player.federation.name, 'NOR')
        self.assertEqual(player.date_of_birth, date(year=1990, month=11, day=30))

        self.assertEqual(player.national_rating_value, 2200)
        ffe_data = FFEUtils.get_player_plugin_data(player)
        self.assertEqual(ffe_data.ffe_licence, PlayerFFELicence.A)
        self.assertEqual(ffe_data.ffe_licence_number, 'D50113')
        self.assertEqual(ffe_data.league, 'IDF')

        results_player = tournament.tournament_players_by_pairing_number[9]
        results = [pairing.result for pairing in results_player.pairings.values()]
        expected_results = [
            Result.LOSS,
            Result.LOSS,
            Result.HALF_POINT_BYE,
            Result.FORFEIT_LOSS,
            Result.PAIRING_ALLOCATED_BYE,
        ]
        self.assertEqual(results, expected_results)

    def test_trf_individual_point_system_is_imported(self):
        trf_tournament = TrfTournament(
            name='Football scoring',
            num_rounds=2,
            individuals_point_system={'W': 3.0, 'D': 1.0, 'L': 0.0, 'P': 3.0},
            players=[
                TrfPlayer(
                    id=number,
                    name=f'Player{number:02d}, Test',
                    rating=2000,
                    federation='FRA',
                    birth_date='1990/01/01',
                    points=0.0,
                    rank=number,
                    games=[],
                )
                for number in (1, 2)
            ],
        )
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as fh:
            fh.write(TrfSerializer.dumps(trf_tournament))
            trf_path = fh.name
        try:
            importer = TrfTournamentImporter([FileOption(Path(trf_path))])
            self.assertEqual(importer.get_not_importable_features(self.event), [])
            tournament = self._import_tournament(importer)
        finally:
            Path(trf_path).unlink(missing_ok=True)
        self.assertEqual(tournament.point_values[Result.WIN], 3.0)
        self.assertEqual(tournament.point_values[Result.DRAW], 1.0)
        self.assertEqual(tournament.point_values[Result.LOSS], 0.0)
        self.assertEqual(tournament.point_values[Result.PAIRING_ALLOCATED_BYE], 3.0)

    def test_trf_national_rating_of_the_event_federation_is_used(self):
        """TRF26 allows one National Rating Support record per
        federation. We keep a single national rating, so the event's own
        federation is the one that counts; the others are dropped, and
        the import dialog says so."""
        trf_tournament = TrfTournament(
            name='National ratings',
            num_rounds=1,
            players=[
                TrfPlayer(
                    id=1,
                    name='Player01, Test',
                    rating=2000,
                    federation='FRA',
                    birth_date='1990/01/01',
                    points=0.0,
                    rank=1,
                    games=[],
                    national_player_by_federation={
                        'FRA': TrfNationalPlayer(player_id=1, rating=1750),
                        'BEL': TrfNationalPlayer(player_id=1, rating=1500),
                    },
                )
            ],
        )
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as fh:
            fh.write(TrfSerializer.dumps(trf_tournament))
            trf_path = fh.name
        try:
            importer = TrfTournamentImporter([FileOption(Path(trf_path))])
            features = importer.get_not_importable_features(self.event)
            tournament = self._import_tournament(importer)
        finally:
            Path(trf_path).unlink(missing_ok=True)
        self.assertEqual(self.event.federation, 'FRA')
        player = tournament.tournament_players_by_pairing_number[1]
        self.assertEqual(player.fide_rating_value, 2000)
        self.assertEqual(player.national_rating_value, 1750)
        # The Belgian rating is discarded, and that is reported.
        self.assertEqual(len(features), 1, features)
        self.assertIn('FRA', features[0])

    def _import_trf(self, trf_tournament: TrfTournament) -> Tournament:
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as fh:
            fh.write(TrfSerializer.dumps(trf_tournament))
            trf_path = fh.name
        try:
            return self._import_tournament(
                TrfTournamentImporter([FileOption(Path(trf_path))])
            )
        finally:
            Path(trf_path).unlink(missing_ok=True)

    def _trf_player(self, number: int, **kwargs) -> TrfPlayer:
        return TrfPlayer(
            id=number,
            name=f'Player{number:02d}, Test',
            federation='FRA',
            birth_date='1990/01/01',
            points=0.0,
            rank=number,
            games=[],
            **kwargs,
        )

    def test_trf_starting_rank_method_reflects_the_ratings_used(self):
        """TRF26 172 states how the field was actually ranked, so it is
        derived from the ratings that were used, not from the tournament
        setting. Estimated ratings cannot be expressed in the format at
        all, so a field carrying any of them is OTHER."""
        rated = self._import_trf(
            TrfTournament(
                name='FIDE rated',
                num_rounds=1,
                starting_rank_federation='FRA',
                starting_rank_method='FIDE',
                players=[
                    self._trf_player(number, rating=2000 + number) for number in (1, 2)
                ],
            )
        )
        trf = rated.to_trf(after_round=0)
        self.assertEqual(trf.starting_rank_method, 'FIDE')
        self.assertEqual(trf.starting_rank_federation, 'FRA')

        unrated = self._import_trf(
            TrfTournament(
                name='Unrated',
                num_rounds=1,
                starting_rank_federation='FRA',
                starting_rank_method='FIDE',
                players=[self._trf_player(number, rating=0) for number in (1, 2)],
            )
        )
        self.assertEqual(unrated.to_trf(after_round=0).starting_rank_method, 'OTHER')

    def test_trf_starting_rank_methods_map_to_a_rating_type(self):
        """All four methods we can honour set the tournament's rating;
        the rest are reported rather than silently reinterpreted."""
        for method, expected in (
            ('FIDE', PlayerRatingType.FIDE),
            ('FIDON', PlayerRatingType.FIDE),
            ('NRO', PlayerRatingType.NATIONAL),
            ('NIDOF', PlayerRatingType.NATIONAL),
        ):
            tournament = self._import_trf(
                TrfTournament(
                    name=f'Ranked by {method}',
                    num_rounds=1,
                    starting_rank_federation='FRA',
                    starting_rank_method=method,
                    players=[self._trf_player(1, rating=2000)],
                )
            )
            self.assertEqual(tournament.player_rating_type, expected, method)

        for method in ('HBFN', 'LBFN', 'OTHER'):
            trf_tournament = TrfTournament(
                name=f'Ranked by {method}',
                num_rounds=1,
                starting_rank_federation='FRA',
                starting_rank_method=method,
                players=[self._trf_player(1, rating=2000)],
            )
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ) as fh:
                fh.write(TrfSerializer.dumps(trf_tournament))
                trf_path = fh.name
            try:
                importer = TrfTournamentImporter([FileOption(Path(trf_path))])
                features = importer.get_not_importable_features(self.event)
            finally:
                Path(trf_path).unlink(missing_ok=True)
            self.assertTrue(
                any(method in feature for feature in features),
                f'{method} should be reported, got {features}',
            )

    def test_trf_imported_teams_and_players_are_checked_in(self):
        """A team or player carried by an imported file is taking part.
        Left checked out, every team is given a zero-point bye when the
        next round is paired (TRF26 240), leaving bbpPairings nothing to
        pair — which surfaces as "pairing is impossible"."""
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        file_path = BASE_PATH / 'trf-team-import-test.trf'
        tournament = self._import_tournament(
            TrfTournamentImporter([FileOption(file_path)])
        )
        self.assertTrue(tournament.teams)
        for team in tournament.teams:
            self.assertTrue(team.check_in, f'{team.name} is checked out')
        # No team should be flagged absent for the round being paired.
        trf = tournament.to_trf(after_round=1)
        absent = [bye for bye in trf.round_byes if bye.type == 'Z' and bye.round == 2]
        self.assertEqual(absent, [], 'teams flagged absent for the next round')

    def test_trf_point_adjustments_reach_the_310_totals(self):
        """The 310 record carries the standings, so bonus / penalty
        points belong in its totals — the 299 records emitted alongside
        say where the difference from the played results came from.
        Rank always included them, so leaving the totals out made the
        two disagree on the same line."""
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        tournament = self._import_tournament(
            TrfTournamentImporter([FileOption(BASE_PATH / 'trf-team-import-test.trf')])
        )
        team = next(t for t in tournament.teams if t.pairing_number == 1)
        before = tournament.to_trf(after_round=1)
        earned = next(t for t in before.teams if t.id == 1).match_points

        from database.sqlite.event.event_database import EventDatabase

        with EventDatabase(self.event.uniq_id, write=True) as database:
            tournament.set_manual_point_adjustment(
                team.id, 1, -3.0, 0.0, 'test penalty', database
            )
        self.event = EventLoader().load_event(EVENT_ID)
        tournament = self.event.tournaments_by_id[tournament.id]

        trf = tournament.to_trf(after_round=1)
        adjusted = next(t for t in trf.teams if t.id == 1)
        self.assertEqual(adjusted.match_points, earned - 3.0)
        # …and the 299 record explains the gap.
        self.assertEqual(
            [
                (a.match_points, a.round, a.pairing_numbers)
                for a in trf.abnormal_points_assignments
            ],
            [(-3.0, 1, [1])],
        )
        # The pairing-info groups read the same totals.
        self.assertEqual(
            tournament.team_primary_score_before_round(team.id, 2), earned - 3.0
        )

    def test_trf_unsupported_type_is_rejected(self):
        """TRF files whose 192 tournament type is unknown or CUSTOM_* must
        be refused, not silently coerced to another pairing system."""
        from common.exception import ImporterError

        base = (BASE_PATH / 'trf-import-test.trf').read_text(encoding='utf-8')
        self.assertIn('FIDE_DUTCH_2026_BAKU', base)
        for bad_type in ('CUSTOM_SCHILLER', 'CUSTOM_TEAM_ROUNDROBIN', 'WAT_IS_THIS'):
            content = base.replace('FIDE_DUTCH_2026_BAKU', bad_type)
            with tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ) as fh:
                fh.write(content)
                trf_path = fh.name
            try:
                importer = TrfTournamentImporter([FileOption(Path(trf_path))])
                with self.assertRaises(ImporterError, msg=f'{bad_type} not rejected'):
                    importer.load_tournament(self.event)
            finally:
                Path(trf_path).unlink(missing_ok=True)

    def test_trf_team_import_into_a_second_tournament_keeps_them_apart(self):
        """A team belongs to one tournament, so importing the same file
        again must build the second tournament its own teams. Reusing the
        first tournament's teams by name attached every imported player to
        it and left the new tournament empty."""
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        file_path = BASE_PATH / 'trf-team-import-test.trf'

        first = self._import_tournament(TrfTournamentImporter([FileOption(file_path)]))
        players, teams = len(first.players), len(first.teams)
        self.assertTrue(players and teams)

        second = self._import_tournament(TrfTournamentImporter([FileOption(file_path)]))
        self.assertNotEqual(second.id, first.id)
        # Reload the first through the same event as the second.
        first = self.event.tournaments_by_id[first.id]
        self.assertEqual((len(first.players), len(first.teams)), (players, teams))
        self.assertEqual((len(second.players), len(second.teams)), (players, teams))
        self.assertFalse(
            {team.id for team in first.teams} & {team.id for team in second.teams},
            'the two tournaments share a team',
        )

    def test_trf_team_swiss_import(self):
        """Import a TRF26 file carrying team rosters (310) + team
        match-point system (362) + board-colour sequence (352) +
        team-Swiss encoded type (192). The importer should:
        - decode the encoded_type into the team-Swiss variation;
        - set primary_score / secondary_score from the code suffix;
        - create one StoredTeam per 310 record (TPN → pairing_number);
        - assign each player to the right team in lineup order;
        - read match_points / color_pattern / team_player_count."""
        # Recreate the event as a Team event so the team-Swiss
        # variation is registered when the importer resolves
        # ``stored_tournament.pairing``.
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)

        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            )
        )
        try:
            importer = TrfTournamentImporter([FileOption(Path(trf_path))])
            self.assertEqual(importer.get_not_importable_features(self.event), [])
            tournament = self._import_tournament(importer)
        finally:
            Path(trf_path).unlink(missing_ok=True)

        self.assertEqual(tournament.name, 'Team Swiss import test')
        self.assertEqual(
            tournament.pairing_variation.id, StandardTeamSwissVariation().id
        )
        self.assertTrue(tournament.is_team_tournament)
        self.assertEqual(tournament.team_player_count, 2)
        self.assertEqual(tournament.primary_score, ScoreType.MATCH_POINTS)
        self.assertEqual(tournament.secondary_score, ScoreType.GAME_POINTS)
        self.assertEqual(tournament.team_colour_type, TeamColourType.A)
        self.assertEqual(tournament.color_pattern, 'WB')
        # PAB default = DRAW points in team Swiss, absence default = LOSS
        # points; ``Tournament`` injects both for us so the dict always
        # contains five entries.
        self.assertEqual(
            tournament.match_points,
            {
                Result.WIN: 2.0,
                Result.DRAW: 1.0,
                Result.LOSS: 0.0,
                Result.ZERO_POINT_BYE: 0.0,
                Result.PAIRING_ALLOCATED_BYE: 1.0,
            },
        )

        self.assertEqual(len(tournament.players), 8)
        self.assertEqual(len(tournament.teams), 4)
        teams_by_pn = tournament.teams_by_pairing_number
        self.assertEqual(set(teams_by_pn), {1, 2, 3, 4})
        self.assertEqual(teams_by_pn[1].name, 'Alphas')
        team_1_player_names = sorted(p.last_name for p in teams_by_pn[1].players)
        self.assertEqual(team_1_player_names, ['ALPHA-ONE', 'ALPHA-TWO'])

    @staticmethod
    def _write_team_trf(
        file_obj,
        *,
        add_blank_reserve: bool = False,
        add_default_pairings: bool = False,
        add_future_team_bye: bool = False,
        add_unrecorded_team_zpb: bool = False,
    ) -> str:
        """Build a minimal TRF26 team Swiss (4 teams × 2 players, no
        rounds played) and write it to ``file_obj``. Returns the file
        path so the caller can clean it up. The fixture is generated
        instead of stored on disk so it stays robust to changes in TRF
        column formatting (which is the serializer's concern)."""
        team_names = [
            ('Alphas', 'ALP', 'Alpha'),
            ('Betas', 'BET', 'Beta'),
            ('Gammas', 'GAM', 'Gamma'),
            ('Deltas', 'DEL', 'Delta'),
        ]
        trf_tournament = TrfTournament(
            name='Team Swiss import test',
            city='Sharly-Chess HQ',
            federation='FRA',
            start_date='2026/06/01',
            end_date='2026/06/02',
            num_rounds=3,
            initial_color=BoardColor.WHITE.value,
            encoded_type='FIDE_TEAM_TYPEA_MP_GP',
            board_color_sequence='WB',
            teams_point_system={'TW': 2.0, 'TD': 1.0, 'TL': 0.0},
            starting_rank_method='FIDON',
            pairing_controller_id='Sharly Chess',
        )
        next_player_id = 1
        trf_teams: list[TrfTeam] = []
        for tpn, (name, nickname, last_prefix) in enumerate(team_names, start=1):
            player_ids = []
            for position, suffix in enumerate(['ONE', 'TWO'], start=1):
                player = TrfPlayer(
                    id=next_player_id,
                    gender='m',
                    title='',
                    name=f'{last_prefix.upper()}-{suffix}, Player',
                    rating=2000 + tpn * 10 + position,
                    federation='FRA',
                    fide_id=0,
                    birth_date='2000/01/01',
                    points=0.0,
                    rank=0,
                    games=[],
                )
                trf_tournament.players.append(player)
                player_ids.append(player.id)
                next_player_id += 1
            trf_teams.append(
                TrfTeam(
                    id=tpn,
                    name=name,
                    nickname=nickname,
                    strength_factor=0,
                    match_points=0.0,
                    game_points=0.0,
                    rank=tpn,
                    player_ids=player_ids,
                )
            )
        trf_tournament.teams = trf_teams
        trf_tournament.num_players = len(trf_tournament.players)
        trf_tournament.num_teams = len(trf_tournament.teams)
        # Each player needs at least one game record so the round count
        # is derivable; record a single round-1 zero-point bye for now.
        for player in trf_tournament.players:
            player.games.append(TrfGame(opponent_id=0, color='-', result='Z', round=1))

        if add_default_pairings:
            games = {
                1: (3, 'w', '1'),
                2: (4, 'b', '='),
                3: (1, 'b', '0'),
                4: (2, 'w', '='),
                5: (7, 'w', '='),
                6: (8, 'b', '0'),
                7: (5, 'b', '='),
                8: (6, 'w', '1'),
            }
            for player_id, (opponent_id, color, result) in games.items():
                trf_tournament.players[player_id - 1].games[0] = TrfGame(
                    opponent_id=opponent_id,
                    color=color,
                    result=result,
                    round=1,
                )
        elif add_unrecorded_team_zpb:
            # Teams 1 and 2 play in default 310 order. Team 3 receives
            # the 320 PAB, leaving team 4 as the optional-by-exclusion
            # ZPB: no 240 Z record is emitted.
            games = {
                1: (3, 'w', '1'),
                2: (4, 'b', '='),
                3: (1, 'b', '0'),
                4: (2, 'w', '='),
            }
            for player_id, (opponent_id, color, result) in games.items():
                trf_tournament.players[player_id - 1].games[0] = TrfGame(
                    opponent_id=opponent_id,
                    color=color,
                    result=result,
                    round=1,
                )
            for player_id in (5, 6):
                trf_tournament.players[player_id - 1].games[0] = TrfGame(
                    opponent_id=0,
                    color='-',
                    result='U',
                    round=1,
                )
            trf_tournament.team_pabs = TrfTeamPABs(
                match_points=1.0,
                game_points=1.0,
                team_id_by_round={1: 3},
            )
        elif add_blank_reserve:
            # Give the round one ordinary board as well. Real team exports
            # have board data alongside their team-bye records, and the
            # importer reconstructs team envelopes while walking those
            # populated rounds.
            trf_tournament.players[2].games[0] = TrfGame(
                opponent_id=5, color='w', result='1', round=1
            )
            trf_tournament.players[4].games[0] = TrfGame(
                opponent_id=3, color='b', result='0', round=1
            )
            reserve = TrfPlayer(
                id=next_player_id,
                gender='m',
                title='',
                name='ALPHA-RESERVE, Player',
                rating=1900,
                federation='FRA',
                fide_id=0,
                birth_date='2000/01/01',
                points=0.0,
                rank=0,
                games=[
                    # The explicit round-2 Z forces the serializer to retain
                    # round 1's empty block, exactly as Sharly does for a
                    # reserve who was not fielded in round 1.
                    TrfGame(opponent_id=None, color=' ', result=' ', round=1),
                    TrfGame(opponent_id=0, color='-', result='Z', round=2),
                ],
            )
            trf_tournament.players.append(reserve)
            trf_tournament.teams[0].player_ids.append(reserve.id)
            trf_tournament.num_players += 1
            # Team 1 has a round-1 ZPB independently of the reserve's blank
            # 001 entry.
            trf_tournament.round_byes.append(
                TrfRoundBye(type='Z', round=1, pairing_numbers=[1])
            )

        if add_future_team_bye:
            trf_tournament.round_byes.append(
                TrfRoundBye(type='H', round=2, pairing_numbers=[1])
            )

        path = file_obj.name
        TrfSerializer.dump(file_obj, trf_tournament)
        file_obj.close()
        return path

    def test_trf_team_boardless_player_byes_are_not_imported(self):
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ),
            add_blank_reserve=True,
        )
        try:
            tournament = self._import_tournament(
                TrfTournamentImporter([FileOption(Path(trf_path))])
            )
        finally:
            Path(trf_path).unlink(missing_ok=True)

        team = tournament.teams_by_pairing_number[1]
        reserve_player = next(
            player for player in team.players if player.last_name == 'ALPHA-RESERVE'
        )
        reserve = tournament.tournament_players_by_id[reserve_player.id]
        self.assertEqual(team.round_bye_type(1), TeamByeType.ZPB)
        self.assertEqual(reserve.pairings_by_round[1].result, Result.NO_RESULT)
        self.assertFalse(reserve.pairings_by_round[1].exists)
        # Explicit player Z records are also not persisted as pairings:
        # in a team 001 record, Z may simply mean that this roster player
        # was absent or not nominated. Any team bye is represented
        # independently by its team envelope.
        self.assertEqual(reserve.pairings_by_round[2].result, Result.NO_RESULT)
        self.assertFalse(reserve.pairings_by_round[2].exists)

    def test_trf_team_default_order_matches_do_not_require_300(self):
        """TRF26 omits 300 when both teams follow their 310 order.
        Reciprocal 001 opponents must still reconstruct the team match
        envelopes, board slots and round lineups."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ),
            add_default_pairings=True,
        )
        try:
            tournament = self._import_tournament(
                TrfTournamentImporter([FileOption(Path(trf_path))])
            )
        finally:
            Path(trf_path).unlink(missing_ok=True)

        pairing_number_by_team_id = {
            team.id: pairing_number
            for pairing_number, team in tournament.teams_by_pairing_number.items()
        }
        matches = tournament.get_round_team_boards(1)
        self.assertEqual(
            {
                (
                    pairing_number_by_team_id[match.stored_team_board.team_a_id],
                    pairing_number_by_team_id[match.stored_team_board.team_b_id],
                )
                for match in matches
                if match.stored_team_board.team_b_id is not None
            },
            {(1, 2), (3, 4)},
        )
        self.assertTrue(
            all([board.index for board in match.boards] == [0, 1] for match in matches)
        )
        self.assertTrue(
            all(
                team.has_explicit_round_lineup(1)
                for team in tournament.teams_by_pairing_number.values()
            )
        )

    def test_trf_team_zpb_is_inferred_when_240_z_is_omitted(self):
        """A team Z entry in 240 is optional in TRF26. Once matches and
        the 320 PAB account for every other team, the remaining team is
        the round ZPB by exclusion."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ),
            add_unrecorded_team_zpb=True,
        )
        try:
            tournament = self._import_tournament(
                TrfTournamentImporter([FileOption(Path(trf_path))])
            )
        finally:
            Path(trf_path).unlink(missing_ok=True)

        teams_by_pn = tournament.teams_by_pairing_number
        pairing_number_by_team_id = {
            team.id: pairing_number for pairing_number, team in teams_by_pn.items()
        }
        bye_type_by_pairing_number = {
            pairing_number_by_team_id[
                team_board.stored_team_board.team_a_id
            ]: team_board.stored_team_board.bye_type
            for team_board in tournament.get_round_team_boards(1)
            if team_board.stored_team_board.team_b_id is None
        }
        self.assertEqual(
            bye_type_by_pairing_number,
            {3: None, 4: TeamByeType.ZPB},
        )
        for player in teams_by_pn[4].players:
            tournament_player = tournament.tournament_players_by_id[player.id]
            self.assertFalse(tournament_player.pairings_by_round[1].exists)

    def test_trf_team_future_240_bye_does_not_mark_other_teams_absent(self):
        """ITDX requires future-round 240 pre-marks. They create only
        the requested envelope and are not evidence that the round has
        otherwise been paired."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            ),
            add_future_team_bye=True,
        )
        try:
            tournament = self._import_tournament(
                TrfTournamentImporter([FileOption(Path(trf_path))])
            )
        finally:
            Path(trf_path).unlink(missing_ok=True)

        round_two_envelopes = tournament.get_round_team_boards(2)
        self.assertEqual(len(round_two_envelopes), 1)
        envelope = round_two_envelopes[0].stored_team_board
        self.assertEqual(envelope.team_a_id, tournament.teams_by_pairing_number[1].id)
        self.assertEqual(envelope.bye_type, TeamByeType.HPB)

    def test_trf_team_recovers_pab_from_legacy_conflicting_320(self):
        """Old Sharly exports could put the wrong team in 320 when a
        manual team bye existed in the same round. The remaining U
        boards still identify the real PAB team and must cause its team
        envelope to be recovered."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        trf_text = (BASE_PATH / 'trf-team-import-test.trf').read_text(encoding='utf-8')
        trf_text = trf_text.replace(
            '320  2.0  5.0   5   3',
            '240 Z 001    1\n320  2.0  5.0   1   3',
        )
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as file:
            file.write(trf_text)
            trf_path = Path(file.name)
        try:
            tournament = self._import_tournament(
                TrfTournamentImporter([FileOption(trf_path)])
            )
        finally:
            trf_path.unlink(missing_ok=True)

        expected_team = tournament.teams_by_pairing_number[5]
        pab = next(
            team_board
            for team_board in tournament.get_round_team_boards(1)
            if team_board.stored_team_board.team_a_id == expected_team.id
            and team_board.stored_team_board.team_b_id is None
        )
        self.assertEqual(pab.stored_team_board.bye_type, None)
        self.assertTrue(
            any(
                pairing.result == Result.PAIRING_ALLOCATED_BYE
                for player in expected_team.players
                if (
                    tournament_player := tournament.tournament_players_by_id.get(
                        player.id
                    )
                )
                for pairing in tournament_player.pairings_by_round.values()
            )
        )

    def test_trf_team_round_trip_with_oodo(self):
        """Re-importing a TRF26 file emitted by Sharly preserves every
        team-specific field the spec lets us encode: variation, score
        config + colour rule (192), match-points (362), per-team PAB
        override (320), per-game-point override (162), colour pattern
        (352), team rosters (310), per-round historical lineups (300),
        the round count (142), and the actual board-by-board
        round-1 match order.

        Uses a real loubatiere-style team Swiss export saved as
        ``trf-team-import-test.trf``."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)

        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)

        # --- top-level tournament fields ---
        self.assertTrue(tournament.is_team_tournament)
        self.assertEqual(tournament.team_player_count, 4)
        self.assertEqual(tournament.rounds, 3)
        self.assertEqual(tournament.color_pattern, 'WBBW')
        self.assertEqual(
            tournament.pairing_variation.id, StandardTeamSwissVariation().id
        )
        # FIDE_TEAM_TYPEA_MP_GP → Type A colour preferences, primary
        # MP, secondary GP for colour allocation.
        from utils.enum import TeamColourType

        self.assertEqual(tournament.team_colour_type, TeamColourType.A)
        self.assertEqual(tournament.primary_score, ScoreType.MATCH_POINTS)
        self.assertEqual(tournament.secondary_score, ScoreType.GAME_POINTS)

        # --- 362 team-point system + 320 team-PAB override ---
        match_points = tournament.match_points
        self.assertEqual(match_points[Result.WIN], 3.0)
        self.assertEqual(match_points[Result.DRAW], 1.0)
        self.assertEqual(match_points[Result.LOSS], 0.0)
        # 320 said PAB MP = 2.0, PAB GP = 5.0 — both must round-trip
        # to the stored tournament.
        self.assertEqual(match_points[Result.PAIRING_ALLOCATED_BYE], 2.0)
        self.assertEqual(tournament.team_pab_game_points, 5.0)
        # 162 override on PAB game points (only key present in the
        # source file).
        self.assertEqual(
            tournament.stored_tournament.game_points,
            {Result.PAIRING_ALLOCATED_BYE.value: 5.0},
        )

        # --- 310 team rosters + team membership ---
        self.assertEqual(len(tournament.teams), 5)
        teams_by_pn = tournament.teams_by_pairing_number
        self.assertEqual(set(teams_by_pn), {1, 2, 3, 4, 5})
        self.assertEqual(teams_by_pn[1].name, 'ERP A')
        self.assertEqual(teams_by_pn[5].name, 'Tour de chartreuse A')
        # Team players have no persisted pairing number (they're synthetic
        # — no tournament_player row), so identify them by name.
        erp_a_player_names = sorted(
            tp.last_name
            for tp in tournament.tournament_players
            if tp.team_id == teams_by_pn[1].id
        )
        self.assertEqual(erp_a_player_names, ['AUBRY', 'BEC', 'BERNARD', 'MINETTO'])

        # --- 300 historical round lineups + per-match board order ---
        # ERP A's match in round 1: OOdO lineup is [10, 15, 7, 14], so
        # boards 0..3 must hold AUBRY, MINETTO, BEC, BERNARD Alex
        # exactly in that order. (310 has the players in a *different*
        # order — [7, 10, 15, 14] — which is what the old fallback
        # would produce; this test exists to prevent regressing back
        # to that fallback when OOdO is present.)
        team_a = teams_by_pn[1]
        round_1_match = next(
            tb
            for tb in tournament.team_boards_by_id.values()
            if tb.round == 1 and tb.stored_team_board.team_a_id == team_a.id
        )
        self.assertIsNotNone(round_1_match.team_b)
        self.assertEqual(
            [board.stored_board.index for board in round_1_match.boards],
            [0, 1, 2, 3],
        )

        def team_a_last_name_per_board(team_match):
            result: list[str] = []
            for board in team_match.boards:
                for player in (
                    board.white_tournament_player,
                    board.black_tournament_player,
                ):
                    if player is not None and player.team_id == team_a.id:
                        result.append(player.last_name)
                        break
            return result

        # OOdO lineup [10, 15, 7, 14] = Aubry, Minetto, Bec, Bernard.
        self.assertEqual(
            team_a_last_name_per_board(round_1_match),
            ['AUBRY', 'MINETTO', 'BEC', 'BERNARD'],
        )

        # ERP A's round-1 lineup must also be persisted in
        # ``team_round_lineup`` so subsequent rounds see the historical
        # board assignment (otherwise the next round's UI defaults to
        # the 310 roster).
        self.assertTrue(team_a.has_explicit_round_lineup(1))
        lineup_names = [p.last_name for p in team_a.get_round_lineup(1)]
        self.assertEqual(lineup_names, ['AUBRY', 'MINETTO', 'BEC', 'BERNARD'])

        # --- per-round match order on the round page ---
        # OOdO lists round 1 as (1,3), (4,2), so canonicalised by
        # pairing number the matches are (1,3) team_board.index 0,
        # (2,4) team_board.index 1, (5, None) team_board.index 2.
        round_1_matches = sorted(
            (tb for tb in tournament.team_boards_by_id.values() if tb.round == 1),
            key=lambda tb: tb.index or 0,
        )
        pn_pairs = [
            (
                tournament.event.teams_by_id[
                    tb.stored_team_board.team_a_id
                ].pairing_number,
                tournament.event.teams_by_id[
                    tb.stored_team_board.team_b_id
                ].pairing_number
                if tb.stored_team_board.team_b_id is not None
                else None,
            )
            for tb in round_1_matches
        ]
        # Orientation comes from the 300 records' first-seen entry per
        # match: ERP A appears with ERP B as opponent first (so team_a
        # = ERP A here), but for the Crest/Lyon match the 300 listed
        # Lyon as team_id first → orientation (4, 2). Tour got the
        # round-1 PAB.
        self.assertEqual(pn_pairs, [(1, 3), (4, 2), (5, None)])

        # --- 001 game records ↔ pairing import ---
        # AUBRY had a round-1 win over DUBOIS, so the pairing record must
        # reflect that.
        aubry = next(
            tp for tp in tournament.tournament_players if tp.last_name == 'AUBRY'
        )
        round_1_pairing = aubry.pairings[1]
        self.assertEqual(round_1_pairing.result, Result.WIN)
        opponent = round_1_pairing.opponent
        assert opponent is not None
        self.assertEqual(opponent.last_name, 'DUBOIS')

        # --- round 2 reconstruction ---
        # The source TRF has round 2 with three matches: Lyon vs ERP A
        # (with two real boards + two unplayed slots on the ERP A
        # side), Crest vs Tour, and ERP B with the PAB. All three
        # must show up in ``team_boards_by_round``; previously the
        # importer was dropping the Lyon vs ERP A match and only
        # surfacing the lone-team groups.
        round_2_matches = [
            tb for tb in tournament.team_boards_by_id.values() if tb.round == 2
        ]
        match_keys = sorted(
            (
                tournament.event.teams_by_id[
                    tb.stored_team_board.team_a_id
                ].pairing_number,
                tournament.event.teams_by_id[
                    tb.stored_team_board.team_b_id
                ].pairing_number
                if tb.stored_team_board.team_b_id is not None
                else None,
            )
            for tb in round_2_matches
        )
        self.assertIn((4, 1), match_keys, 'Lyon vs ERP A missing in round 2')
        self.assertIn((2, 5), match_keys, 'Crest vs Tour missing in round 2')
        self.assertIn((3, None), match_keys, 'ERP B PAB missing in round 2')

    def test_trf_team_round_trip_with_lineup_holes(self):
        """Round-2 ERP A line in the fixture is
        ``300   2   1   4   10    7 0000 0000`` — slots 2 and 3 are
        holes. Importing must preserve them as index gaps in the
        team's round lineup, and re-emitting via :meth:`to_trf` must
        produce the same OOdO record."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)

        teams_by_pn = tournament.teams_by_pairing_number
        erp_a = teams_by_pn[1]
        lyon = teams_by_pn[4]

        # --- import: ERP A's round-2 lineup is two-deep, holes at the end ---
        slots = erp_a.effective_round_slots(2)
        self.assertEqual(len(slots), 4)
        self.assertIsNotNone(slots[0])
        self.assertIsNotNone(slots[1])
        self.assertIsNone(slots[2], 'expected hole at slot 2 for ERP A round 2')
        self.assertIsNone(slots[3], 'expected hole at slot 3 for ERP A round 2')
        present_names = sorted(p.last_name for p in slots if p is not None)
        self.assertEqual(present_names, ['AUBRY', 'BEC'])

        # ``team_round_lineup`` is stored as index-gapped rows — only
        # the slots that have a player exist in the DB.
        lineup_entries = erp_a.stored_team.stored_round_lineups[2]
        stored_indexes = sorted(e.index for e in lineup_entries)
        self.assertEqual(stored_indexes, [0, 1])

        # --- import: the team match's boards reflect the holes ---
        # Slot 0 and 1: both teams present → black_player_id is set.
        # Slot 2 and 3: ERP A has a hole → board's black_player_id is
        # NULL, white_player_id is Lyon's player on that slot.
        round_2_match = next(
            tb
            for tb in tournament.team_boards_by_id.values()
            if tb.round == 2
            and {
                tb.stored_team_board.team_a_id,
                tb.stored_team_board.team_b_id,
            }
            == {erp_a.id, lyon.id}
        )
        boards_by_slot = {b.index: b for b in round_2_match.boards}
        self.assertEqual(set(boards_by_slot), {0, 1, 2, 3})
        for full_slot in (0, 1):
            self.assertIsNotNone(
                boards_by_slot[full_slot].stored_board.black_player_id,
                f'slot {full_slot} should have both players',
            )
        for hole_slot in (2, 3):
            board = boards_by_slot[hole_slot]
            self.assertIsNone(
                board.stored_board.black_player_id,
                f'slot {hole_slot}: hole side should be NULL',
            )
            present_player_id = board.stored_board.white_player_id
            assert present_player_id is not None
            present_tp = tournament.tournament_players_by_id[present_player_id]
            self.assertEqual(
                present_tp.team_id,
                lyon.id,
                f'slot {hole_slot}: present player must be Lyon (the team that '
                f'still has a player on this slot)',
            )

        # --- re-export: holes round-trip via ``to_trf`` ---
        # OOdO record for (round=2, team_a=ERP A, team_b=Lyon) must put
        # 0 at slots 2 and 3 (and the present-team's pairing numbers
        # at the filled slots).
        trf = tournament.to_trf(after_round=2)
        erp_a_record = next(
            r
            for r in trf.oodo_team_pairings
            if r.round == 2 and r.team_id == 1 and r.opponent_team_id == 4
        )
        # Players are renumbered on export (no persisted team-player
        # numbers), so verify the board order by identity: Aubry, Bec,
        # then the two holes.
        by_pn = tournament.tournament_players_by_pairing_number
        board_names = [
            by_pn[pn].last_name if pn is not None else None
            for pn in erp_a_record.boards
        ]
        self.assertEqual(board_names, ['AUBRY', 'BEC', None, None])
        # And the opposite-direction OOdO for Lyon must list all four
        # slots filled (Lyon had a full lineup).
        lyon_record = next(
            r
            for r in trf.oodo_team_pairings
            if r.round == 2 and r.team_id == 4 and r.opponent_team_id == 1
        )
        self.assertEqual(
            [pn is not None for pn in lyon_record.boards],
            [True, True, True, True],
        )

    def test_trf_team_full_round_trip_with_hole_opponent_forfeit(self):
        """Full export → re-import round trip. After import, the
        opposing player on a slot whose own team has a hole carries a
        ``FORFEIT_WIN``. The serialised TRF emits ``+`` as the result
        and a colour next to ``0000`` — the importer's validation rules
        must accept that combination (forfeit-result + colour +
        opponent_id=0 is valid per TRF-2026 in team mode)."""
        import io

        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)

        # Force a hole-opponent scenario into the imported state: a
        # team-match board on round 2 where one side is a real player
        # and the other side is a hole. The fixture's round-2 ERP A vs
        # Lyon match has ERP A holes at slots 2 & 3 — Lyon's slot-2 and
        # slot-3 players need result=FORFEIT_WIN so the re-export
        # writes ``0000 b +`` / ``0000 w +``.
        from utils.enum import Result
        from database.sqlite.event.event_database import EventDatabase

        teams_by_pn = tournament.teams_by_pairing_number
        lyon = teams_by_pn[4]
        erp_a = teams_by_pn[1]
        round_2_match = next(
            tb
            for tb in tournament.team_boards_by_id.values()
            if tb.round == 2
            and {
                tb.stored_team_board.team_a_id,
                tb.stored_team_board.team_b_id,
            }
            == {erp_a.id, lyon.id}
        )
        with EventDatabase(self.event.uniq_id, write=True) as db:
            for board in round_2_match.boards:
                if board.stored_board.black_player_id is None:
                    # Lyon player (on white) gets a forfeit win.
                    pairing = board.optional_white_pairing
                    assert pairing is not None
                    pairing.stored_pairing.result = Result.FORFEIT_WIN.value
                    pairing.update(db)

        # --- export to TRF text ---
        trf_tournament = tournament.to_trf(after_round=2)
        buf = io.StringIO()
        TrfSerializer.dump(buf, trf_tournament)
        trf_text = buf.getvalue()

        # --- re-import the emitted TRF text ---
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as f:
            f.write(trf_text)
            reimport_path = Path(f.name)
        try:
            reimporter = TrfTournamentImporter([FileOption(reimport_path)])
            reimported = self._import_tournament(reimporter)
        finally:
            reimport_path.unlink(missing_ok=True)

        # The re-imported tournament must have the same hole structure
        # and the forfeit-win results preserved.
        reimported_teams_by_pn = reimported.teams_by_pairing_number
        reimported_erp_a = reimported_teams_by_pn[1]
        slots = reimported_erp_a.effective_round_slots(2)
        self.assertEqual(len(slots), 4)
        self.assertIsNone(slots[2], 'ERP A slot 2 hole lost in round trip')
        self.assertIsNone(slots[3], 'ERP A slot 3 hole lost in round trip')

    def _set_team_manual_bye(
        self, tournament: Tournament, team_id: int, round_: int, bye_type: str
    ) -> None:
        """Replace whatever envelope the team currently has for
        ``round_`` with a manual bye of ``bye_type``."""
        from database.sqlite.event.event_database import EventDatabase
        from database.sqlite.event.event_store import StoredTeamBoard

        round_team_boards = tournament.get_round_team_boards(round_)
        existing = next(
            (
                tb
                for tb in round_team_boards
                if tb.stored_team_board.team_a_id == team_id
                and tb.stored_team_board.team_b_id is None
            ),
            None,
        )
        with EventDatabase(tournament.event.uniq_id, write=True) as db:
            if existing is not None:
                existing.stored_team_board.bye_type = bye_type
                db.update_stored_team_board(existing.stored_team_board)
            else:
                indexes = [
                    tb.stored_team_board.index
                    for tb in round_team_boards
                    if tb.stored_team_board.index is not None
                ]
                next_index = max(indexes, default=-1) + 1
                stb = StoredTeamBoard(
                    id=None,
                    tournament_id=tournament.id,
                    round_=round_,
                    team_a_id=team_id,
                    team_b_id=None,
                    index=next_index,
                    bye_type=bye_type,
                )
                stb.id = db.add_stored_team_board(stb)
                tournament.stored_tournament.stored_team_boards_by_round.setdefault(
                    round_, []
                ).append(stb)
        tournament.clear_team_cache()

    def test_team_standings_scores_each_bye_type_distinctly(self):
        """``Tournament.team_standings`` must distinguish PAB / HPB /
        FPB / ZPB envelopes. Before, every ``team_b_id IS NULL`` row
        was awarded ``pab_mp`` + ``team_pab_game_points`` regardless of
        ``bye_type`` — Lyon's ZPB ended up scored like a PAB. Each bye
        type should now translate to its own MP/GP contribution."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)
        teams_by_pn = tournament.teams_by_pairing_number
        zpb_team = teams_by_pn[1]
        hpb_team = teams_by_pn[2]
        fpb_team = teams_by_pn[3]
        pab_team = teams_by_pn[4]
        # Wipe rounds 2 and 3 results so the only contribution to the
        # standings comes from the round-2 byes we're about to inject.
        # (Round 1's mixed match data complicates the arithmetic.)
        for r in (1, 2, 3):
            for stb in list(
                tournament.stored_tournament.stored_team_boards_by_round.get(r, [])
            ):
                from database.sqlite.event.event_database import EventDatabase

                with EventDatabase(tournament.event.uniq_id, write=True) as db:
                    if stb.id is not None:
                        db.delete_stored_team_board(stb.id)
            tournament.stored_tournament.stored_team_boards_by_round[r] = []
        tournament.clear_team_cache()

        # Inject a different bye for each team at round 1.
        self._set_team_manual_bye(tournament, zpb_team.id, 1, 'ZPB')
        self._set_team_manual_bye(tournament, hpb_team.id, 1, 'HPB')
        self._set_team_manual_bye(tournament, fpb_team.id, 1, 'FPB')
        self._set_team_manual_bye(tournament, pab_team.id, 1, 'PAB')

        standings = {row['team'].id: row for row in tournament.team_standings()}
        match_points = tournament.match_points
        win_mp = match_points[Result.WIN]
        draw_mp = match_points[Result.DRAW]
        loss_mp = match_points[Result.LOSS]
        pab_mp = match_points[Result.PAIRING_ALLOCATED_BYE]
        n = float(tournament.team_player_count or 0)

        self.assertEqual(standings[zpb_team.id]['mp'], loss_mp)
        self.assertEqual(standings[zpb_team.id]['gp'], 0.0)
        self.assertEqual(standings[hpb_team.id]['mp'], draw_mp)
        self.assertEqual(standings[hpb_team.id]['gp'], n * 0.5)
        self.assertEqual(standings[fpb_team.id]['mp'], win_mp)
        self.assertEqual(standings[fpb_team.id]['gp'], n * 1.0)
        self.assertEqual(standings[pab_team.id]['mp'], pab_mp)
        self.assertEqual(standings[pab_team.id]['gp'], tournament.team_pab_game_points)

    def test_create_team_round_pairing_flow(self):
        """Manual team pairing — first click creates a PAB envelope
        (team_a only, PAB-result individual boards), mirroring an
        engine bye. Second click on a different team completes the
        pair: the PAB envelope is mutated to a real ``team_a`` /
        ``team_b`` match, individual boards regenerated with both
        lineups and result flipped from PAB to NO_RESULT."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)
        teams_by_pn = tournament.teams_by_pairing_number
        team_a = teams_by_pn[1]
        team_b = teams_by_pn[2]
        # Wipe round 2 so we have a clean slate to manually pair.
        from database.sqlite.event.event_database import EventDatabase

        for stb in list(
            tournament.stored_tournament.stored_team_boards_by_round.get(2, [])
        ):
            with EventDatabase(tournament.event.uniq_id, write=True) as db:
                if stb.id is not None:
                    db.delete_stored_team_board(stb.id)
        tournament.stored_tournament.stored_team_boards_by_round[2] = []
        tournament.clear_team_cache()

        # First click on team A: creates a PAB envelope with PAB-result
        # individual boards. The team_b column is empty. Boards with a
        # present player have a PAB pairing; bare-hole boards stay empty.
        tb_pending = tournament.create_team_round_pairing(2, team_a.id)
        self.assertIsNone(tb_pending.team_b)
        self.assertEqual(tb_pending.team_a.id, team_a.id)
        self.assertEqual(tb_pending.bye_type, 'PAB')
        n = tournament.team_player_count or 0
        self.assertEqual(len(tb_pending.boards), n)
        present_pending = 0
        for board in tb_pending.boards:
            present = board.optional_white_pairing or board.optional_black_pairing
            if present is not None:
                self.assertEqual(present.result, Result.PAIRING_ALLOCATED_BYE)
                present_pending += 1
        self.assertGreater(present_pending, 0)

        # Second click on team B: completes the pair. PAB-side boards
        # are dropped and rebuilt with both lineups; results flip to
        # NO_RESULT (each board with at least one present player).
        tb_complete = tournament.create_team_round_pairing(2, team_b.id)
        complete_team_b = tb_complete.team_b
        assert complete_team_b is not None
        self.assertEqual(
            {tb_complete.team_a.id, complete_team_b.id},
            {team_a.id, team_b.id},
        )
        # Same envelope was mutated, not duplicated.
        self.assertEqual(tb_complete.id, tb_pending.id)
        self.assertEqual(len(tb_complete.boards), n)
        for board in tb_complete.boards:
            white_pairing = board.optional_white_pairing
            black_pairing = board.optional_black_pairing
            if white_pairing is not None and black_pairing is not None:
                self.assertEqual(white_pairing.result, Result.NO_RESULT)
                self.assertEqual(black_pairing.result, Result.NO_RESULT)
            else:
                # Hole on one side → present player has FORFEIT_WIN.
                present = white_pairing or black_pairing
                if present is not None:
                    self.assertEqual(present.result, Result.FORFEIT_WIN)

    def test_create_team_round_pairing_clears_existing_bye(self):
        """Pairing a team that already has a manual bye for the round
        should supersede the bye — the bye envelope is removed."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)
        teams_by_pn = tournament.teams_by_pairing_number
        team_a = teams_by_pn[1]
        team_b = teams_by_pn[2]
        from database.sqlite.event.event_database import EventDatabase

        for stb in list(
            tournament.stored_tournament.stored_team_boards_by_round.get(2, [])
        ):
            with EventDatabase(tournament.event.uniq_id, write=True) as db:
                if stb.id is not None:
                    db.delete_stored_team_board(stb.id)
        tournament.stored_tournament.stored_team_boards_by_round[2] = []
        tournament.clear_team_cache()

        # Give team_b a ZPB at round 2.
        self._set_team_manual_bye(tournament, team_b.id, 2, 'ZPB')
        self.assertEqual(team_b.round_bye_type(2), 'ZPB')
        # Manually pair team_a and team_b. The ZPB should be removed.
        tournament.create_team_round_pairing(2, team_a.id)
        tournament.create_team_round_pairing(2, team_b.id)
        self.assertIsNone(team_b.round_bye_type(2))
        boards = tournament.get_round_team_boards(2)
        # Only one envelope — the completed pair.
        self.assertEqual(len(boards), 1)
        self.assertIsNotNone(boards[0].team_b)

    def test_team_primary_score_before_round_matches_standings(self):
        """``team_primary_score_before_round(team, R)`` and
        ``_team_trf_totals_after(R-1)`` must agree on each team's
        cumulative score, and both must honour bye_type. Used by the
        engine + post-import sort, so a drift would silently produce
        a different display order each side."""
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)
        teams_by_pn = tournament.teams_by_pairing_number
        team = teams_by_pn[1]
        # Replace round 2's envelope for the team with a ZPB.
        self._set_team_manual_bye(tournament, team.id, 2, 'ZPB')

        # As of start of round 3, the team's primary score should
        # *not* include the ZPB as a PAB. Match the totals helper.
        score = tournament.team_primary_score_before_round(team.id, 3)
        totals = tournament._team_trf_totals_after(2)
        match_points = tournament.match_points
        if tournament.primary_score == ScoreType.MATCH_POINTS:
            self.assertEqual(score, totals[team.id][0])
        else:
            self.assertEqual(score, totals[team.id][1])
        # The ZPB contribution itself must not equal a PAB
        # contribution.
        self.assertNotEqual(
            score,
            tournament._team_trf_totals_after(1)[team.id][
                0 if tournament.primary_score == ScoreType.MATCH_POINTS else 1
            ]
            + match_points[Result.PAIRING_ALLOCATED_BYE],
        )

    def test_trf_team_round_trip_preserves_manual_bye_history(self):
        """A manual bye applied to a *past* round must survive a TRF
        export → re-import cycle. Earlier, ``_team_trf_round_byes``
        only emitted 240 records for the round being paired, and the
        importer didn't read 240 at all — so a past-round
        ``HPB``/``FPB``/``ZPB`` collapsed into a plain PAB envelope on
        re-import."""
        import io

        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        importer = TrfTournamentImporter(
            [FileOption(BASE_PATH / 'trf-team-import-test.trf')]
        )
        tournament = self._import_tournament(importer)
        teams_by_pn = tournament.teams_by_pairing_number

        # Each team chosen for these rounds already has a PAB
        # envelope we can convert to a manual bye, so we don't have to
        # tear down a real match in the fixture.
        injections = [
            (teams_by_pn[5].id, 1, 'ZPB'),
            (teams_by_pn[3].id, 2, 'HPB'),
        ]
        for team_id, round_, bye_type in injections:
            self._set_team_manual_bye(tournament, team_id, round_, bye_type)

        # Export the modified tournament.
        trf = tournament.to_trf(after_round=tournament.rounds)
        buf = io.StringIO()
        TrfSerializer.dump(buf, trf)
        trf_text = buf.getvalue()

        # Re-import into a fresh event and verify bye_type survives.
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', suffix='.trfx', delete=False
        ) as f:
            f.write(trf_text)
            reimport_path = Path(f.name)
        try:
            reimporter = TrfTournamentImporter([FileOption(reimport_path)])
            reimported = self._import_tournament(reimporter)
        finally:
            reimport_path.unlink(missing_ok=True)

        reimported_teams_by_pn = reimported.teams_by_pairing_number
        for pn, round_, expected_bye in [
            (5, 1, 'ZPB'),
            (3, 2, 'HPB'),
        ]:
            team_id = reimported_teams_by_pn[pn].id
            round_team_boards = reimported.get_round_team_boards(round_)
            envelope = next(
                (
                    tb
                    for tb in round_team_boards
                    if tb.stored_team_board.team_a_id == team_id
                    and tb.stored_team_board.team_b_id is None
                ),
                None,
            )
            assert envelope is not None, (
                f'team pn={pn} should have a bye envelope in round {round_}'
            )
            self.assertEqual(
                envelope.stored_team_board.bye_type,
                expected_bye,
                f'team pn={pn} round {round_}: bye_type lost on round trip',
            )

    def test_trf_team_320_excludes_manual_byes(self):
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        tournament = self._import_tournament(
            TrfTournamentImporter([FileOption(BASE_PATH / 'trf-team-import-test.trf')])
        )
        pab_team = tournament.teams_by_pairing_number[5]
        self._set_team_manual_bye(tournament, pab_team.id, 1, TeamByeType.ZPB)

        team_pabs = tournament.to_trf(after_round=1).team_pabs
        self.assertIsNotNone(team_pabs)
        assert team_pabs is not None
        self.assertNotIn(1, team_pabs.team_id_by_round)

    def test_trf_team_into_individual_event_is_rejected(self):
        """A team TRF must not be importable into an individual event,
        and a non-team TRF must not be importable into a team event."""
        from common.exception import ImporterError

        trf_path = self._write_team_trf(
            tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.trfx', delete=False
            )
        )
        try:
            # Default ``self.event`` is an individual event.
            individual_importer = TrfTournamentImporter([FileOption(Path(trf_path))])
            features = individual_importer.get_not_importable_features(self.event)
            self.assertTrue(
                any('individual event' in feature for feature in features),
                f'expected cross-type warning, got {features!r}',
            )
            with self.assertRaises(ImporterError):
                individual_importer.load_tournament(self.event)
        finally:
            Path(trf_path).unlink(missing_ok=True)

        # Now swap to a team event and try importing an individual TRF.
        TestUtils.delete_event(EVENT_ID)
        TestUtils.create_event(EVENT_ID, overrides={'event_type': EventType.TEAM})
        self.event = EventLoader().load_event(EVENT_ID)
        individual_trf = BASE_PATH / 'trf-import-test.trf'
        team_event_importer = TrfTournamentImporter([FileOption(individual_trf)])
        features = team_event_importer.get_not_importable_features(self.event)
        self.assertTrue(
            any('team event' in feature for feature in features),
            f'expected cross-type warning, got {features!r}',
        )
        with self.assertRaises(ImporterError):
            team_event_importer.load_tournament(self.event)

    def test_papi_import(self):
        file_path = BASE_PATH / 'papi-import-test.papi'
        importer = PapiTournamentImporter([FileOption(file_path)])
        tournament = self._import_tournament(importer)
        self.assertEqual(tournament.name, 'Papi import test')
        self.assertEqual(len(tournament.players), 16)

    def test_papi_json_import(self):
        file_path = BASE_PATH / 'papi-json-import-test.json'
        importer = PapiJsonTournamentImporter([FileOption(file_path)])
        tournament = self._import_tournament(importer)
        self.assertEqual(tournament.name, 'Papi JSON import test')
        self.assertEqual(len(tournament.players), 16)
