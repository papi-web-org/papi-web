"""FIDE 6.6: a round-robin player who completed less than 50% of their games
is dropped from the final standings and their games are not counted in the
opponents' tie-breaks. The results stay in the crosstable.

Built on the TEC round-robin fixture (6 players, 5 rounds, ids 1..6). Player 6 is made to forfeit their last three games (rounds 3-5), so they
left the tournament having completed only 2/5 < 50%.
"""

from unittest import TestCase

import pytest

from data.event import Event
from data.loader import EventLoader
from data.tie_breaks import tie_breaks
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTeam,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from utils.enum import EventType, Result

EVENT_ID = 'test-rr-participation-event'
TOURNAMENT_ID = 'test-rr-participation-tournament'
LEAVER_ID = 6


@pytest.mark.unit
class RoundRobinParticipationRuleTestCase(TestCase):
    def setUp(self) -> None:
        TestUtils.create_event(EVENT_ID)
        TestUtils.create_tournament(
            EVENT_ID, TOURNAMENT_ID, json_file='tec-round-robin'
        )

    def tearDown(self) -> None:
        TestUtils.delete_event(EVENT_ID)

    @property
    def tournament(self):
        # Hold a live reference to the event: the tournament keeps only a
        # weak reference to it.
        self._event: Event = EventLoader().load_event(EVENT_ID)
        return self._event.tournaments_by_name[TOURNAMENT_ID]

    def _forfeit_leaver_rounds(self, rounds: list[int]) -> None:
        """Record a forfeit loss for player ``LEAVER_ID`` in each given round."""
        tournament = self.tournament
        for round_ in rounds:
            board = next(
                board
                for board in tournament.get_round_boards(round_)
                if LEAVER_ID
                in (
                    getattr(board.optional_white_tournament_player, 'id', None),
                    getattr(board.black_tournament_player, 'id', None),
                )
            )
            leaver_is_white = (
                board.optional_white_tournament_player is not None
                and board.optional_white_tournament_player.id == LEAVER_ID
            )
            # add_result stores the white result and the opposite for black;
            # FORFEIT_WIN and FORFEIT_LOSS are opposites.
            tournament.add_result(
                board,
                Result.FORFEIT_LOSS if leaver_is_white else Result.FORFEIT_WIN,
            )

    def test_leaver_excluded_and_ranked_last(self) -> None:
        self._forfeit_leaver_rounds([3, 4, 5])
        tournament = self.tournament

        excluded = {
            player.id: player.is_excluded_from_standings
            for player in tournament.tournament_players
        }
        self.assertTrue(excluded[LEAVER_ID])
        self.assertFalse(any(v for k, v in excluded.items() if k != LEAVER_ID))

        ranks = tournament.compute_tournament_player_ranks()
        # The excluded player is ranked last; the competitors keep 1..5.
        self.assertEqual(ranks[len(ranks)].id, LEAVER_ID)
        competitor_ranks = {
            player.id: rank for rank, player in ranks.items() if player.id != LEAVER_ID
        }
        self.assertEqual(sorted(competitor_ranks.values()), [1, 2, 3, 4, 5])

    def test_leaver_dropped_from_opponents_sonneborn_berger(self) -> None:
        self._forfeit_leaver_rounds([3, 4, 5])
        tournament = self.tournament
        sb = tie_breaks.SonnebornBergerTieBreak()

        for player in tournament.tournament_players:
            if player.id == LEAVER_ID:
                continue
            value = sb.compute_player_value(player, after_round=tournament.rounds)
            # No opponent contribution may come from the excluded leaver: the
            # only games that count are those against the other competitors,
            # weighted by each opponent's *annulled* standings score (their
            # own game against the leaver removed too).
            manual = sum(
                pairing.result.points(tournament.point_values)
                * tournament.players_by_id[pairing.opponent_id].standings_points(
                    tournament.rounds
                )
                for pairing in player.pairings.values()
                if pairing.opponent_id is not None and pairing.opponent_id != LEAVER_ID
            )
            self.assertAlmostEqual(value, manual)

    def test_opponents_points_annulled_for_leaver_games(self) -> None:
        # FIDE 6.6: a game against the excluded leaver is not counted in the
        # final standings — opponents do not keep the points (played win or
        # forfeit win) they scored against them.
        self._forfeit_leaver_rounds([3, 4, 5])
        tournament = self.tournament
        tournament.compute_tournament_player_ranks()
        for player in tournament.tournament_players:
            if player.id == LEAVER_ID:
                continue
            vs_leaver = next(
                pairing
                for pairing in player.pairings.values()
                if pairing.opponent_id == LEAVER_ID
            )
            raw = player.points_after(tournament.rounds)
            annulled = player.standings_points(tournament.rounds)
            self.assertAlmostEqual(
                raw - annulled,
                vs_leaver.result.points(tournament.point_values),
            )
            # The ranking is computed on the annulled score.
            self.assertAlmostEqual(player.points, annulled)

    def _mutate_leaver(self, tournament) -> None:
        """Change the excluded leaver's data in place: a played-game result
        (rounds 1-2 are real games) and their rating. None of it may reach
        any other player's tie-break."""
        from utils.types import PlayerRatingAndType

        leaver = tournament.tournament_players_by_id[LEAVER_ID]
        leaver.__dict__['_tournament_rating'] = PlayerRatingAndType(
            leaver.rating + 400, leaver.rating_type
        )
        pairing = leaver.pairings_by_round[1]
        board = pairing.board
        assert board is not None
        leaver_is_white = board.stored_board.white_player_id == LEAVER_ID
        new_leaver = Result.LOSS if pairing.result == Result.WIN else Result.WIN
        white_result = new_leaver if leaver_is_white else new_leaver.opposite_result
        board.white_pairing.stored_pairing.result = white_result.value
        board.black_pairing.stored_pairing.result = white_result.opposite_result.value

    def test_no_tie_break_counts_the_excluded_player(self) -> None:
        """Auto-discovers every tie-break: an excluded player's results and
        rating must not affect any other player's tie-break value. A new
        tie-break that iterates games without skipping the excluded opponent
        (``game_counts_for_tie_breaks`` / ``standings_points``) fails here —
        no per-tie-break test needed."""
        from data.pairings.systems import RoundRobinPairingSystem
        from data.tie_breaks.sets import _all_tie_break_subclasses

        self._forfeit_leaver_rounds([3, 4, 5])
        tournament = self.tournament
        rr = RoundRobinPairingSystem()

        candidates = []
        for cls in _all_tie_break_subclasses():
            try:
                tie_break = cls()
            except Exception:
                continue
            if (
                not tie_break.is_computed_per_player
                or tie_break.is_manual
                or tie_break.is_team_tiebreak
                or not tie_break.is_compatible_with(rr)
            ):
                continue
            candidates.append(tie_break)

        def values_for(tie_break):
            return {
                player.id: float(
                    tie_break.compute_player_value(
                        player, after_round=tournament.rounds
                    )
                )
                for player in tournament.tournament_players
                if not player.is_excluded_from_standings
            }

        tournament.compute_tournament_player_ranks()
        baseline = {}
        for tie_break in candidates:
            try:
                baseline[tie_break.static_id()] = values_for(tie_break)
            except Exception:
                # Not applicable to this fixture (e.g. needs data it lacks).
                pass

        self._mutate_leaver(tournament)
        tournament.compute_tournament_player_ranks()
        for tie_break in candidates:
            if tie_break.static_id() not in baseline:
                continue
            self.assertEqual(
                baseline[tie_break.static_id()],
                values_for(tie_break),
                f'{tie_break.static_id()} counts the excluded player '
                '(missing the FIDE 6.6 exclusion filter?)',
            )
        # Guard against the discovery silently testing nothing.
        self.assertIn('SONNEBORN_BERGER', baseline)
        self.assertIn('WINS', baseline)

    def test_rule_disabled_keeps_leaver_ranked(self) -> None:
        self._forfeit_leaver_rounds([3, 4, 5])
        tournament = self.tournament
        tournament.stored_tournament.round_robin_participation_rule = False
        # Recompute against the now-disabled rule.
        for player in tournament.tournament_players:
            player.__dict__.pop('is_excluded_from_standings', None)
        self.assertFalse(
            any(
                player.is_excluded_from_standings
                for player in tournament.tournament_players
            )
        )


TEAM_EVENT_ID = 'test-rr-participation-team-event'
TEAM_TOURNAMENT_NAME = 'rr'
TEAM_N = 2  # players per team
TEAMS = 4  # 4 teams -> 3 Berger rounds


@pytest.mark.unit
class TeamRoundRobinParticipationRuleTestCase(TestCase):
    """Same rule for team round-robins: a team that forfeits every board in
    more than half of its matches (a withdrawn / expelled team) is dropped
    from the team standings."""

    def tearDown(self) -> None:
        TestUtils.delete_event(TEAM_EVENT_ID)

    def _create(self) -> None:
        TestUtils.create_event(TEAM_EVENT_ID, overrides={'event_type': EventType.TEAM})
        TestUtils.create_tournament(
            TEAM_EVENT_ID,
            TEAM_TOURNAMENT_NAME,
            overrides={
                'rounds': TEAMS - 1,
                'current_round': 1,
                'team_player_count': TEAM_N,
                'pairing': 'TEAM_ROUND_ROBIN_BERGER',
            },
        )
        self.team_ids: list[int] = []
        with EventDatabase(TEAM_EVENT_ID, write=True) as db:
            tournament = next(
                t
                for t in db.load_stored_tournaments()
                if t.name == TEAM_TOURNAMENT_NAME
            )
            tid = tournament.id
            assert tid is not None
            for seed in range(1, TEAMS + 1):
                team_id = db.add_stored_team(
                    StoredTeam(
                        id=None,
                        name=f'Team{seed}',
                        tournament_id=tid,
                        pairing_number=seed,
                        check_in=True,
                    )
                )
                self.team_ids.append(team_id)
                for p_index in range(TEAM_N):
                    pid = db.add_stored_player(
                        StoredPlayer(
                            id=None,
                            last_name=f'T{seed}P{p_index}',
                            team_id=team_id,
                            team_index=p_index,
                            check_in=True,
                        )
                    )
                    db.add_stored_tournament_player(
                        StoredTournamentPlayer(
                            tournament_id=tid, player_id=pid, pairing_number=p_index
                        )
                    )

    def _load(self):
        try:
            EventLoader.unload_event(TEAM_EVENT_ID)
        except KeyError:
            pass
        self._event = EventLoader().load_event(TEAM_EVENT_ID)
        return self._event.tournaments_by_name[TEAM_TOURNAMENT_NAME]

    def _play_round(self, round_: int, leaver_id: int, forfeit_leaver: bool) -> None:
        """Enter a result on every board of the round so it counts as
        finished (a prerequisite for pairing the next round). When
        *forfeit_leaver* is set, the leaver forfeits every board of its
        match; every other board is drawn."""
        tournament = self._load()
        with EventDatabase(tournament.event.uniq_id, write=True) as db:
            for team_board in tournament.get_round_team_boards(round_):
                stb = team_board.stored_team_board
                if stb.team_b_id is None:
                    continue
                leaver_here = leaver_id in (stb.team_a_id, stb.team_b_id)
                for board in team_board.boards:
                    for pairing in (
                        board.optional_white_pairing,
                        board.optional_black_pairing,
                    ):
                        if pairing is None:
                            continue
                        if leaver_here and forfeit_leaver:
                            is_leaver = pairing.tournament_player.team_id == leaver_id
                            pairing.update_result(
                                db,
                                Result.FORFEIT_LOSS
                                if is_leaver
                                else Result.FORFEIT_WIN,
                            )
                        else:
                            pairing.update_result(db, Result.DRAW)

    def test_leaving_team_excluded_and_ranked_last(self) -> None:
        self._create()
        leaver_id = self.team_ids[-1]
        # The leaver plays round 1, then forfeits its last two matches
        # (rounds 2 and 3): it left the tournament and completed only 1/3.
        for round_, forfeit in ((1, False), (2, True), (3, True)):
            tournament = self._load()
            tournament.pairing_variation.engine.generate_pairings(tournament, round_)
            self._play_round(round_, leaver_id, forfeit_leaver=forfeit)

        tournament = self._load()
        excluded = {
            team.id: team.is_excluded_from_standings for team in tournament.teams
        }
        self.assertTrue(excluded[leaver_id])
        self.assertFalse(any(v for k, v in excluded.items() if k != leaver_id))

        standings = tournament.team_standings()
        self.assertEqual(standings[-1]['team'].id, leaver_id)
        competitor_ranks = sorted(
            row['rank'] for row in standings if row['team'].id != leaver_id
        )
        self.assertEqual(competitor_ranks, [1, 2, 3])

        # The leaver's own matches are annulled: no standing score.
        leaver_row = next(r for r in standings if r['team'].id == leaver_id)
        self.assertEqual(leaver_row['played'], 0)
        self.assertEqual(leaver_row['mp'], 0.0)
        self.assertEqual(leaver_row['gp'], 0.0)

        # Opponents keep no points from a match against the leaver: turning
        # the rule off restores the forfeit-win match points they'd otherwise
        # have banked, so at least one opponent's MP goes up.
        on_mp = {row['team'].id: row['mp'] for row in standings}
        tournament.stored_tournament.round_robin_participation_rule = False
        for team in tournament.teams:
            team.__dict__.pop('is_excluded_from_standings', None)
        off_mp = {row['team'].id: row['mp'] for row in tournament.team_standings()}
        self.assertTrue(
            any(off_mp[tid] > on_mp[tid] for tid in on_mp if tid != leaver_id)
        )

    def _pair_and_play_with_leaver(self) -> int:
        """Pair the three Berger rounds; the last team plays round 1 then
        forfeits its last two matches (leaver, completed 1/3). Returns its id."""
        self._create()
        leaver_id = self.team_ids[-1]
        for round_, forfeit in ((1, False), (2, True), (3, True)):
            tournament = self._load()
            tournament.pairing_variation.engine.generate_pairings(tournament, round_)
            self._play_round(round_, leaver_id, forfeit_leaver=forfeit)
        return leaver_id

    def _perturb_leaver_match(self, leaver_id: int, round_: int) -> None:
        """Change the excluded leaver's played match (round 1 is real) to a
        win for the leaver — its results must not reach any other team."""
        tournament = self._load()
        with EventDatabase(tournament.event.uniq_id, write=True) as db:
            for team_board in tournament.get_round_team_boards(round_):
                stb = team_board.stored_team_board
                if stb.team_b_id is None or leaver_id not in (
                    stb.team_a_id,
                    stb.team_b_id,
                ):
                    continue
                for board in team_board.boards:
                    for pairing in (
                        board.optional_white_pairing,
                        board.optional_black_pairing,
                    ):
                        if pairing is None:
                            continue
                        leaver_side = pairing.tournament_player.team_id == leaver_id
                        pairing.update_result(
                            db, Result.WIN if leaver_side else Result.LOSS
                        )

    def _team_tie_break_snapshot(self) -> dict:
        from data.tie_breaks.sets import _all_tie_break_subclasses

        tournament = self._load()
        records = tournament.team_records(after_round=tournament.rounds)
        records_by_id = {record.team_id: record for record in records}
        context = tournament.team_tie_break_context()
        non_excluded = [
            team for team in tournament.teams if not team.is_excluded_from_standings
        ]
        out: dict = {}
        for cls in _all_tie_break_subclasses():
            try:
                tie_break = cls()
            except Exception:
                continue
            if (
                not tie_break.supports_team_mode
                or tie_break.is_manual
                or tie_break.display_rank_delta  # group-level (EDE) — see below
            ):
                continue
            try:
                out[tie_break.static_id()] = {
                    team.id: float(
                        tie_break.compute_team_value(
                            records_by_id[team.id],
                            records_by_id,
                            context,
                            after_round=tournament.rounds,
                        )
                    )
                    for team in non_excluded
                }
            except Exception:
                continue
        return out

    def test_no_team_tie_break_counts_the_excluded_team(self) -> None:
        """Team analogue of the individual sweep: an excluded team's results
        must not reach any other team's tie-break. The exclusion is centralised
        in ``team_records`` (excluded matches are dropped), so this guards
        against a tie-break bypassing it or that dropping regressing."""
        leaver_id = self._pair_and_play_with_leaver()
        baseline = self._team_tie_break_snapshot()
        self._perturb_leaver_match(leaver_id, 1)
        mutated = self._team_tie_break_snapshot()
        self.assertEqual(baseline, mutated)
        # Guard against the discovery silently testing nothing (team Buchholz
        # and the team Koya are opponent-based).
        self.assertIn('BUCHHOLZ', baseline)
        self.assertIn('KOYA', baseline)
