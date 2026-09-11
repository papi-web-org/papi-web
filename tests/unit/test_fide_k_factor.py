"""The FIDE rating coefficient (k) of a player: the one stored alongside
their rating when it is known, the estimate of Section B-02-8.3.3 of the
FIDE handbook otherwise."""

from datetime import date
from unittest import TestCase

import pytest

from data.input_output.data_source import keep_reliable_k_factors, reliable_k_factor
from data.loader import EventLoader
from data.player import Player, TournamentPlayer
from data.tournament import Tournament
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTournament,
    StoredTournamentPlayer,
)
from tests.test_config import TestUtils
from utils.enum import PlayerRatingType, TournamentRating
from utils.types import PlayerRating

EVENT_ID = 'test-fide-k-factor'
PLAYER_ID = 1001


@pytest.mark.unit
class EstimatedKFactorTestCase(TestCase):
    def test_a_player_without_a_fide_rating_gets_forty(self):
        assert Player.estimate_fide_rating_coefficient(None, 1980) == 40

    def test_a_player_above_2400_gets_ten(self):
        assert Player.estimate_fide_rating_coefficient(2401, 1980) == 10

    def test_a_young_player_below_2300_gets_forty(self):
        assert (
            Player.estimate_fide_rating_coefficient(2299, date.today().year - 18) == 40
        )

    def test_a_young_player_from_2300_gets_twenty(self):
        assert (
            Player.estimate_fide_rating_coefficient(2300, date.today().year - 18) == 20
        )

    def test_any_other_player_gets_twenty(self):
        assert Player.estimate_fide_rating_coefficient(2000, 1980) == 20


@pytest.mark.unit
class ReliableKFactorTestCase(TestCase):
    """What survives of the k-factors of a FIDE database whose rating period
    is not the one of the tournament. A coefficient only ever goes down, so
    an outdated one is an upper bound and is kept down to the estimate."""

    def test_ten_survives_a_higher_estimate(self):
        assert reliable_k_factor(10, 2000, 1980) == 10

    def test_twenty_survives_the_estimate_of_a_young_player(self):
        assert reliable_k_factor(20, 2000, date.today().year - 16) == 20

    def test_twenty_gives_way_to_a_player_who_has_reached_2400(self):
        assert reliable_k_factor(20, 2450, 1980) == 10

    def test_forty_gives_way_to_a_player_who_is_no_longer_young(self):
        assert reliable_k_factor(40, 2000, 1980) == 20

    def test_nothing_is_invented(self):
        assert reliable_k_factor(None, 2450, 1980) is None

    def test_the_coefficients_of_a_player_are_all_reduced(self):
        stored_player = StoredPlayer(
            id=PLAYER_ID,
            last_name='DOE',
            year_of_birth=1980,
            ratings={
                TournamentRating.STANDARD.value: PlayerRating(
                    fide=2450, k_factor=20
                ).stored_value,
                TournamentRating.RAPID.value: PlayerRating(
                    fide=2000, k_factor=10
                ).stored_value,
                TournamentRating.BLITZ.value: PlayerRating(
                    fide=2000, k_factor=40
                ).stored_value,
            },
        )
        keep_reliable_k_factors(stored_player)
        assert [
            PlayerRating.from_stored_value(
                stored_player.ratings[tournament_rating.value]
            ).k_factor
            for tournament_rating in TournamentRating
        ] == [10, 10, 20]


@pytest.mark.unit
class TournamentPlayerKFactorTestCase(TestCase):
    def setUp(self):
        TestUtils.create_event(EVENT_ID)
        self.event = EventLoader().load_event(EVENT_ID)

    def tearDown(self):
        TestUtils.delete_event(EVENT_ID)

    def _tournament_player(self, rating: PlayerRating) -> TournamentPlayer:
        self.event.stored_event.stored_players.append(
            StoredPlayer(
                id=PLAYER_ID,
                last_name='DOE',
                year_of_birth=1980,
                ratings={
                    tournament_rating.value: rating.stored_value
                    for tournament_rating in TournamentRating
                },
            )
        )
        self.tournament = Tournament(
            self.event,
            StoredTournament(
                id=1,
                name='k-factor',
                rating=TournamentRating.STANDARD.value,
                player_rating_type=PlayerRatingType.FIDE.value,
                stored_tournament_players=[
                    StoredTournamentPlayer(tournament_id=1, player_id=PLAYER_ID)
                ],
            ),
        )
        return self.tournament.tournament_players_by_id[PLAYER_ID]

    def test_a_stored_coefficient_is_used_as_is(self):
        tournament_player = self._tournament_player(
            PlayerRating(fide=2000, k_factor=10)
        )
        assert tournament_player.fide_rating_coefficient == (10, False)

    def test_the_coefficient_is_estimated_when_none_is_stored(self):
        tournament_player = self._tournament_player(PlayerRating(fide=2000))
        assert tournament_player.fide_rating_coefficient == (20, True)
