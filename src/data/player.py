import weakref
from dataclasses import dataclass
from datetime import date
from functools import total_ordering, cached_property
from typing import TYPE_CHECKING, Any

from babel.lists import format_list

from common.i18n import _, get_locale
from common.i18n.utils import normalized_key
from data.pairing import Pairing
from data.player_categories import PlayerCategory
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPlayer,
    StoredTournamentPlayer,
    StoredPairing,
)
from plugins.manager import plugin_manager
from plugins.utils import PluginData
from utils import Utils
from utils.date_time import format_date
from utils.enum import (
    PlayerGender,
    PlayerTitle,
    BoardColor,
    Result,
    TitleNorm,
    TournamentRating,
    PlayerRatingType,
    CheckInStatus,
)
from utils.types import (
    Federation,
    Club,
    PlayerRating,
    PlayerRatingAndType,
    NormCheckResult,
    TieBreakValue,
)

if TYPE_CHECKING:
    from _weakref import ReferenceType
    from data.criteria.tournament_criteria import TournamentCriterion
    from data.event import Event
    from data.teams.team import Team
    from data.tie_breaks.tie_breaks import TieBreak
    from data.tournament import Tournament
    from data.input_output.trf.trf_data import TrfPlayer

MIN_YOB = 1900
MAX_YOB = date.today().year


@dataclass
class PlayerProfileLink:
    """A federation's identifier for a player, shown on the identity line
    of the record modal and linking to that federation's profile page."""

    #: Short label, e.g. ``FIDE 653055225``.
    label: str
    #: ``None`` when the federation's identifier is known but the one its
    #: profile page is keyed on is not — the label still tells the arbiter
    #: something, so it is shown unlinked.
    url: str | None = None


class Player:
    def __init__(
        self,
        event: 'Event',
        stored_player: StoredPlayer,
    ):
        self._event_ref: 'ReferenceType[Event]' = weakref.ref(event)
        self.stored_player = stored_player
        self.ratings = self._get_ratings()
        self.plugin_data = self._get_plugin_data()

    @staticmethod
    def plugin_data_class_by_plugin_id() -> dict[str, type[PluginData]]:
        return {
            plugin_id: plugin_data_class
            for plugin_id, plugin_data_class in plugin_manager.hook.get_player_plugin_data_class()
        }

    @property
    def event(self) -> 'Event':
        event = self._event_ref()
        if event is None:
            raise RuntimeError('Event reference has been garbage collected')
        return event

    @property
    def id(self) -> int:
        assert self.stored_player.id is not None
        return self.stored_player.id

    @property
    def last_name(self) -> str:
        return self.stored_player.last_name

    @property
    def first_name(self) -> str:
        return self.stored_player.first_name or ''

    @staticmethod
    def player_full_name(
        first_name: str | None,
        last_name: str,
    ) -> str:
        if first_name:
            return _('{first_name} {last_name}').format(
                first_name=first_name or '', last_name=last_name
            )
        return last_name

    @cached_property
    def full_name(self) -> str:
        return self.player_full_name(self.first_name, self.last_name)

    @cached_property
    def name_sort_key(self) -> tuple[str, str]:
        return normalized_key(self.last_name), normalized_key(self.first_name)

    @property
    def date_of_birth(self) -> date | None:
        return self.stored_player.date_of_birth

    @property
    def date_of_birth_str(self) -> str:
        if self.date_of_birth:
            return format_date(self.date_of_birth)
        return ''

    @property
    def year_of_birth(self) -> int:
        if self.date_of_birth:
            return self.date_of_birth.year
        return self.stored_player.year_of_birth or 0

    @property
    def date_or_year_of_birth_str(self) -> str:
        if self.date_of_birth:
            return format_date(self.date_of_birth)
        if self.year_of_birth:
            return str(self.year_of_birth)
        return ''

    @property
    def gender(self) -> PlayerGender:
        return PlayerGender(self.stored_player.gender)

    @property
    def mail(self) -> str | None:
        return self.stored_player.mail

    @property
    def phone(self) -> str | None:
        return self.stored_player.phone

    @property
    def comment(self) -> str | None:
        return self.stored_player.comment

    @property
    def owed(self) -> float:
        return self.stored_player.owed

    @property
    def paid(self) -> float:
        return self.stored_player.paid

    @property
    def title(self) -> PlayerTitle:
        """The player's open title (GM, IM, FM, CM or NONE)."""
        return PlayerTitle(self.stored_player.title)

    @property
    def women_title(self) -> PlayerTitle:
        """The player's women title (WGM, WIM, WFM, WCM or NONE)."""
        return PlayerTitle(self.stored_player.women_title)

    @property
    def strongest_title(self) -> PlayerTitle:
        """The single most prestigious title held (open or women), by rank.
        Used wherever exactly one title is required — imports, exports,
        sorting and title-holder logic."""
        return max(self.title, self.women_title, key=lambda title: title.sort_index)

    @property
    def display_title(self) -> str:
        """Human-readable title(s) for display. Shows the women title next
        to the open title unless the open title outranks it on the combined
        FIDE ladder: GM hides WGM and IM hides WIM (redundant), but an
        equal or lower open title is shown alongside — e.g. FM + WIM renders
        as "FM/WIM" because FM does not supersede WIM."""
        open_title, women_title = self.title, self.women_title
        if women_title == PlayerTitle.NONE:
            return open_title.short_name
        if open_title == PlayerTitle.NONE:
            return women_title.short_name
        if open_title.fide_tier > women_title.fide_tier:
            return open_title.short_name
        return f'{open_title.short_name}/{women_title.short_name}'

    @property
    def held_titles(self) -> frozenset[PlayerTitle]:
        """The player's held titles (open and/or women), excluding NONE.

        Norm checks test membership against both titles: a player can hold
        an open title and a women title at once (e.g. IM + WIM), and either
        may satisfy a title requirement."""
        return frozenset(
            title
            for title in (self.title, self.women_title)
            if title != PlayerTitle.NONE
        )

    def title_on_norm_ladder(self, title_norm: TitleNorm) -> PlayerTitle:
        """The player's title on the same ladder as `title_norm`: the women
        title for women norms (WIM, WGM), the open title for open norms (IM,
        GM). Open and women titles are separate ladders, so a norm is only
        "already held" when the matching-ladder title outranks it — an FM
        with no women title can still be chasing a WIM norm."""
        return self.women_title if title_norm.player_title.is_women else self.title

    @cached_property
    def category(self) -> PlayerCategory:
        return PlayerCategory.from_year_of_birth(
            self.event,
            self.year_of_birth,
            self.event.start_date,
            self.event.stop_date,
        )

    @cached_property
    def category_name(self) -> str:
        return self.category.name

    @property
    def fide_id(self) -> int | None:
        return self.stored_player.fide_id

    @property
    def fide_profile_url(self) -> str | None:
        if not self.fide_id:
            return None
        return f'https://ratings.fide.com/profile/{self.fide_id}'

    @cached_property
    def profile_links(self) -> list[PlayerProfileLink]:
        """The federation identifiers shown on the record modal's identity
        line. FIDE first, then whatever the enabled plugins contribute for
        their own federation."""
        links: list[PlayerProfileLink] = []
        if (url := self.fide_profile_url) is not None:
            links.append(
                PlayerProfileLink(label=_('FIDE {id}').format(id=self.fide_id), url=url)
            )
        plugin_manager.hook_for_event(self.event, 'insert_player_profile_links')(
            player=self, links=links
        )
        return links

    @property
    def federation(self) -> Federation:
        return Federation(self.stored_player.federation or '')

    @property
    def club(self) -> Club:
        return Club(self.stored_player.club or '')

    @property
    def team_id(self) -> int | None:
        return self.stored_player.team_id

    @property
    def team_index(self) -> int | None:
        return self.stored_player.team_index

    @property
    def event_default_rating(self) -> int | None:
        """Best available rating for the event's default rating type."""
        rating = self.event_default_rating_and_type
        return rating.value or None

    @cached_property
    def event_default_rating_and_type(self) -> 'PlayerRatingAndType':
        """Rating + its source type for display in team/event contexts.

        Uses the team's tournament rating type (Standard/Rapid/Blitz) and
        player-rating type (FIDE/National/Estimated) when the player is on a
        team assigned to a tournament. Falls back to the event's default
        cadence (the shared one when every tournament uses the same,
        Standard otherwise) + event rating type for unassigned players."""
        team = self.team
        if team is not None and team.tournament is not None:
            tournament = team.tournament
            return self.get_rating_and_type(
                tournament.rating,
                tournament.player_rating_type,
                self.category,
            )
        return self.get_rating_and_type(
            self.event.default_tournament_rating,
            self.event.player_rating_type,
            self.category,
        )

    @property
    def team(self) -> 'Team | None':
        if (team_id := self.team_id) is None:
            return None
        return self.event.teams_by_id.get(team_id)

    @property
    def has_been_paired(self) -> bool:
        """True if the player has been placed on a board in any of the
        event's tournaments (whether or not a result was entered). Used
        to lock the team picker — moving a paired player would orphan
        their board(s)."""
        for tournament in self.event.tournaments:
            tournament_player = tournament.tournament_players_by_id.get(self.id)
            if tournament_player is not None and tournament_player.has_been_paired:
                return True
        return False

    @property
    def fixed(self) -> int | None:
        return self.stored_player.fixed

    @property
    def check_in(self) -> bool:
        return self.stored_player.check_in

    @cached_property
    def optional_single_tournament_id(self) -> int | None:
        """The tournament this player is assigned to, or None if unassigned.
        For team events, derived from the player's team."""
        if self.event.is_team_event:
            team = self.team
            if team is not None and team.tournament_id is not None:
                return team.tournament_id
            return None
        for tournament in self.event.tournaments:
            if self.id in tournament.tournament_players_by_id:
                return tournament.id
        return None

    @property
    def single_tournament_id(self) -> int:
        """The tournament this player is assigned to. Raises if unassigned."""
        tournament_id = self.optional_single_tournament_id
        if tournament_id is None:
            raise RuntimeError('Player not assigned to a tournament')
        return tournament_id

    @property
    def single_tournament(self) -> 'Tournament':
        return self.event.tournaments_by_id[self.single_tournament_id]

    @property
    def optional_single_tournament(self) -> 'Tournament | None':
        tournament_id = self.optional_single_tournament_id
        if tournament_id is None:
            return None
        return self.event.tournaments_by_id[tournament_id]

    @property
    def single_tournament_player(self) -> 'TournamentPlayer':
        return self.single_tournament.tournament_players_by_id[self.id]

    @property
    def optional_single_tournament_player(self) -> 'TournamentPlayer | None':
        tournament = self.optional_single_tournament
        if tournament is None:
            return None
        return tournament.tournament_players_by_id.get(self.id)

    def invalidate_team_derived_cache(self):
        """Forget what was worked out from this player's team.

        In a team event the player's tournament comes from their team, and
        it is cached — so joining, leaving or changing team has to drop it.
        """
        Utils.reset_cached_properties(self, 'optional_single_tournament_id')

    def replace_stored_player(self, stored_player: StoredPlayer):
        self.stored_player = stored_player
        self.plugin_data = self._get_plugin_data()
        self.ratings = self._get_ratings()

    def _get_plugin_data(self) -> dict[str, PluginData]:
        return {
            plugin_id: plugin_data_class.from_stored_value(
                self.stored_player.plugin_data.get(plugin_id, {})
            )
            for plugin_id, plugin_data_class in self.plugin_data_class_by_plugin_id().items()
        }

    def _get_ratings(self) -> dict[TournamentRating, PlayerRating]:
        return {
            tournament_rating: PlayerRating.from_stored_value(
                self.stored_player.ratings.get(tournament_rating.value, {})
            )
            for tournament_rating in TournamentRating
        }

    def get_rating_and_type(
        self,
        tournament_rating: TournamentRating,
        player_rating_type: PlayerRatingType,
        category: PlayerCategory,
    ) -> PlayerRatingAndType:
        player_ratings = self.ratings[tournament_rating]
        rating: int | None = None
        type_: PlayerRatingType = PlayerRatingType.ESTIMATED
        if player_rating_type == PlayerRatingType.FIDE:
            rating = player_ratings.fide
            type_ = PlayerRatingType.FIDE
        elif player_rating_type == PlayerRatingType.NATIONAL:
            rating = player_ratings.national
            type_ = PlayerRatingType.NATIONAL
        if rating is None:
            rating_and_type = plugin_manager.hook_for_event(
                self.event, 'get_player_rating'
            )(
                tournament_rating=tournament_rating,
                player_rating_type=player_rating_type,
                player=self,
                category=category,
            )
            if rating_and_type:
                return rating_and_type
            if player_ratings.estimated:
                return PlayerRatingAndType(
                    player_ratings.estimated, PlayerRatingType.ESTIMATED
                )

        return PlayerRatingAndType(rating or 0, type_)

    @property
    def has_real_rating(self) -> bool:
        return any(
            rating.fide is not None or rating.national is not None
            for rating in self.ratings.values()
        )

    @property
    def first_real_rating_str(self) -> str:
        for tournament_rating in TournamentRating:
            rating_and_type = self.get_rating_and_type(
                tournament_rating, PlayerRatingType.FIDE, self.category
            )
            if rating_and_type.type == PlayerRatingType.ESTIMATED:
                rating_and_type = self.get_rating_and_type(
                    tournament_rating, PlayerRatingType.NATIONAL, self.category
                )
            if rating_and_type.type != PlayerRatingType.ESTIMATED:
                return f'{rating_and_type} ({tournament_rating.acronym})'
        raise ValueError('Player expected to have a real rating')

    def update_ratings(self, ratings: dict[TournamentRating, PlayerRating]):
        for tournament_rating, player_rating in ratings.items():
            self.stored_player.ratings[tournament_rating.value] = (
                player_rating.stored_value
            )
        self.ratings = self._get_ratings()

    @property
    def not_paired_str(self) -> str:
        return (
            _('Unpaired *** WOMAN')
            if self.gender == PlayerGender.WOMAN
            else _('Unpaired *** MAN')
        )

    @property
    def exempt_str(self) -> str:
        return (
            _('Exempt *** WOMAN')
            if self.gender == PlayerGender.WOMAN
            else _('Exempt *** MAN')
        )


@total_ordering
class TournamentPlayer(Player):
    def __init__(
        self,
        tournament: 'Tournament',
        stored_tournament_player: StoredTournamentPlayer,
    ):
        player_id = stored_tournament_player.player_id
        stored_player = tournament.event.players_by_id[player_id].stored_player
        super().__init__(tournament.event, stored_player)
        self._tournament_ref: 'ReferenceType[Tournament]' = weakref.ref(tournament)
        self.stored_tournament_player = stored_tournament_player

        self.points: float | None = None
        self.vpoints: float | None = None
        self.board_id: int | None = None
        self.board_number: int | None = None
        self.color: BoardColor | None = None
        self._tie_break_values: list[TieBreakValue] | None = None
        self._rank: int | None = None
        self.time_control_trf25: str | None = None
        self.time_control_modified: bool | None = None
        self.tie_break_variables: dict[str, Any] = {}
        self.transient_plugin_data: dict[str, object] = {}
        # Per-round sums cached only during a guarded computation pass.
        self._compute_cache: dict[Any, float] = {}

    def clear_compute_caches(self) -> None:
        self._compute_cache.clear()

    @property
    def tournament(self) -> 'Tournament':
        if (tournament := self._tournament_ref()) is None:
            raise RuntimeError('Reference has been garbage collected')
        return tournament

    @property
    def event(self) -> 'Event':
        return self.tournament.event

    @property
    def pairing_number(self) -> int | None:
        return self.stored_tournament_player.pairing_number

    def _get_default_pairing(self, round_: int) -> Pairing:
        return Pairing(
            self,
            StoredPairing(
                tournament_id=self.tournament.id,
                player_id=self.id,
                round_=round_,
                result=Result.NO_RESULT.value,
                board_id=None,
            ),
            exists=False,
        )

    @cached_property
    def pairings_by_round(self) -> dict[int, Pairing]:
        known_pairings: dict[int, Pairing] = {}
        for stored_pairing in self.stored_tournament_player.stored_pairings:
            pairing = Pairing(self, stored_pairing)
            known_pairings[pairing.round] = pairing
        return {
            round_: (
                known_pairings[round_]
                if round_ in known_pairings
                else self._get_default_pairing(round_)
            )
            for round_ in range(1, self.tournament.rounds + 1)
        }

    def delete_pairing(self, round_: int, event_database: EventDatabase):
        event_database.delete_stored_pairing(
            self.pairings_by_round[round_].stored_pairing
        )
        self.pairings_by_round[round_] = self._get_default_pairing(round_)

    @property
    def estimated(self) -> bool:
        return self.rating_type == PlayerRatingType.ESTIMATED

    @cached_property
    def category(self) -> PlayerCategory:
        return PlayerCategory.from_year_of_birth(
            self.event,
            self.year_of_birth,
            self.tournament.start_date,
            self.tournament.stop_date,
        )

    @property
    def rating(self) -> int:
        return self._tournament_rating.value

    @property
    def rating_type(self) -> PlayerRatingType:
        return self._tournament_rating.type

    @cached_property
    def rating_str(self) -> str:
        return str(self._tournament_rating)

    def will_fide_override_with_standard_rating(
        self, tournament_rating: TournamentRating, player_rating_type: PlayerRatingType
    ) -> bool:
        if player_rating_type != PlayerRatingType.FIDE:
            # We only override for tournament that are using the FIDE ratings
            return False

        ratings = self.ratings.get(tournament_rating, None)
        if ratings and ratings.fide is not None:
            return False

        if tournament_rating != TournamentRating.STANDARD:
            ratings = self.ratings.get(TournamentRating.STANDARD, None)
            if ratings and ratings.fide is not None:
                return True

        return False

    @cached_property
    def tournament_rating_is_overridden(self) -> bool:
        return self.rating_is_overridden(
            self.tournament.rating, self.tournament.player_rating_type
        )

    def rating_is_overridden(
        self, tournament_rating: TournamentRating, player_rating_type: PlayerRatingType
    ) -> bool:
        return (
            self.tournament.override_unrated_rapid_blitz
            and self.will_fide_override_with_standard_rating(
                tournament_rating, player_rating_type
            )
        )

    @property
    def manual_tiebreak(self) -> int | None:
        return self.stored_tournament_player.manual_tiebreak

    @property
    def rating_used_by_fide(self) -> PlayerRatingAndType:
        if self.will_fide_override_with_standard_rating(
            self.tournament.rating, self.tournament.player_rating_type
        ):
            rating = self.ratings.get(TournamentRating.STANDARD)
            assert rating is not None
            assert rating.fide is not None
            return PlayerRatingAndType(rating.fide, PlayerRatingType.FIDE)

        return self.get_rating_and_type(
            self.tournament.rating, self.tournament.player_rating_type, self.category
        )

    @cached_property
    def _tournament_rating(self) -> PlayerRatingAndType:
        if self.tournament_rating_is_overridden:
            rating = self.ratings.get(TournamentRating.STANDARD)
            assert rating is not None
            assert rating.fide is not None
            return PlayerRatingAndType(rating.fide, PlayerRatingType.FIDE)

        return self.get_rating_and_type(
            self.tournament.rating, self.tournament.player_rating_type, self.category
        )

    @property
    def fide_rating_value(self) -> int | None:
        rating = self.tournament.rating
        if self.tournament_rating_is_overridden:
            rating = TournamentRating.STANDARD
        return self.ratings[rating].fide

    @property
    def national_rating_value(self) -> int | None:
        return self.ratings[self.tournament.rating].national

    @property
    def ratings_str(self) -> str:
        return '/'.join(
            [
                str(
                    self.get_rating_and_type(
                        tournament_rating,
                        self.tournament.player_rating_type,
                        self.category,
                    )
                )
                for tournament_rating in TournamentRating
            ]
        )

    @property
    def fide_rating_coefficient(self) -> tuple[int, bool]:
        """Returns the player's coefficient (k), or the best guess."""
        from database.sqlite.fide.fide_database import FideDatabase

        if self.fide_id and FideDatabase().exists():
            with FideDatabase() as db:
                k = (db.get_k_factors_by_fide_id(self.fide_id) or {}).get(
                    self.tournament.rating
                )
                if k is not None:
                    return k, False

        # Make the best guess according to Section B-02-8.3.3 of the FIDE handbook
        if self.rating_used_by_fide.type != PlayerRatingType.FIDE:
            return 40, True
        if self.rating_used_by_fide.value > 2400:
            return 10, True
        if self.year_of_birth:
            age = date.today().year - self.year_of_birth
            if age <= 18 and self.rating_used_by_fide.value < 2300:
                return 40, True
        return 20, True

    @property
    def first_fide_rating(self) -> tuple[int | None, str | None]:
        """Calculate a players first FIDE rating based on this tournament."""
        games = [
            pairing
            for pairing in self.pairings.values()
            if pairing.played
            and pairing.opponent
            and pairing.opponent.rating_type == PlayerRatingType.FIDE
        ]
        if len(games) == 0:
            return None, _('No games against FIDE rated opponents.')
        if all(game.loss for game in games):
            return None, _(
                'The player did not win any games against FIDE rated opponents.'
            )

        # Average rating of opponents + 2 fictional opponents with 1800 rating against which the player draws
        total_opponent_ratings = 1800 * 2
        for game in games:
            if game.opponent and game.opponent.rating_used_by_fide:
                total_opponent_ratings += game.opponent.rating_used_by_fide.value

        num_games = len(games) + 2
        average_rating = Utils.round_ranking(total_opponent_ratings / num_games)
        score = (
            sum(game.result.point_value for game in games) + Result.DRAW.point_value * 2
        )
        rating_difference = Utils.performance_bonus(
            Utils.round_ranking(100 * score / num_games) / 100
        )
        return average_rating + rating_difference, None

    @property
    def point_values(self) -> dict[Result, float] | None:
        return self.tournament.point_values

    def points_before(self, before_round: int, only_played: bool = False) -> float:
        caching = self.tournament._compute_caching_enabled
        key = ('points_before', before_round, only_played)
        if caching:
            cached = self._compute_cache.get(key)
            if cached is not None:
                return cached
        value = sum(
            pairing.result.points(self.point_values)
            for round_, pairing in self.pairings.items()
            if round_ < before_round and (pairing.played or not only_played)
        )
        # Bonus / penalty points are part of the score, so they belong in
        # the figure the pairings table shows and sorts on. Excluded from
        # the played-games-only variant, which measures games rather than
        # standing.
        if not only_played:
            value += self.tournament.player_point_adjustment_total(
                self.id, before_round - 1
            )
            # A score counts points won, so it stops at zero: a penalty
            # that would take it below leaves the player on nothing. The
            # pairing engine already works this way — the TRF score is
            # unsigned and bbpPairings floors its own recomputation — so
            # anything else would show a figure the tournament is not
            # actually being run on.
            value = max(0.0, value)
        if caching:
            self._compute_cache[key] = value
        return value

    def points_after(self, after_round: int) -> float:
        caching = self.tournament._compute_caching_enabled
        key = ('points_after', after_round)
        if caching:
            cached = self._compute_cache.get(key)
            if cached is not None:
                return cached
        value = sum(
            pairing.result.points(self.point_values)
            for round_index, pairing in self.pairings.items()
            if round_index <= after_round
        )
        # Manual bonus / penalty points count towards the score, so they
        # reach the score groups the pairing engine works from — which is
        # what the TRF26 299 record they are exported as is for. Floored
        # at zero, as in ``points_before``.
        value += self.tournament.player_point_adjustment_total(self.id, after_round)
        value = max(0.0, value)
        if caching:
            self._compute_cache[key] = value
        return value

    # Standard W/D/L values for the TRF26 team-mode "standard score".
    # Tournament-level ``game_points`` overrides intentionally don't apply
    # here — the spec defines this as an informative over-the-board sum.
    _TEAM_TRF_STANDARD_POINTS: 'dict[Result, float]' = {
        Result.WIN: 1.0,
        Result.DRAW: 0.5,
        Result.LOSS: 0.0,
    }

    def team_trf_standard_points_after(self, after_round: int) -> float:
        """TRF26 §1.6 "standard score" for the 001 ``points`` field in
        team competitions: the player's score from over-the-board games
        and forfeit wins only, using fixed W=1 / D=0.5 / L=0 values.
        Byes (ZPB, HPB, FPB, PAB), forfeit losses and ``REST_GAME``
        don't count — they're informational fillers, not games."""
        return sum(
            pairing.result.points(self._TEAM_TRF_STANDARD_POINTS)
            for round_index, pairing in self.pairings.items()
            if round_index <= after_round
            and (not pairing.result.is_unplayed or pairing.result == Result.FORFEIT_WIN)
        )

    def standings_points(self, after_round: int) -> float:
        """The score that counts towards the final standings after
        *after_round*. Identical to :meth:`points_after`, except games
        against a player excluded from the standings (FIDE 6.6) are not
        counted — for the standings those games did not happen (the leaver's
        results stay in the crosstable for rating/history only). With no
        excluded players this equals :meth:`points_after`."""
        caching = self.tournament._compute_caching_enabled
        key = ('standings_points', after_round)
        if caching:
            cached = self._compute_cache.get(key)
            if cached is not None:
                return cached
        value = sum(
            pairing.result.points(self.point_values)
            for round_, pairing in self.pairings.items()
            if round_ <= after_round and self.game_counts_for_tie_breaks(pairing)
        )
        value += self.tournament.player_point_adjustment_total(self.id, after_round)
        value = max(0.0, value)
        if caching:
            self._compute_cache[key] = value
        return value

    def total_points(self, only_played: bool = False) -> float:
        return sum(
            pairing.result.points(self.point_values)
            for pairing in self.pairings.values()
            if pairing.played or not only_played
        )

    def compute_points(self, *, before_round: int):
        """Computes and stores the points scored by the player before round `before_round` (returns None)"""
        self.points = self.points_before(before_round)

    def points_total(self) -> float:
        return sum(
            pairing.result.points(self.point_values)
            for pairing in self.pairings.values()
        )

    def add_points(self, points: float):
        """If `self.points` is set, add `points` to it.
        Otherwise, leave `self.points` as None."""
        if self.points is not None:
            self.points += points

    @property
    def points_str(self) -> str:
        return Utils.points_str(self.points)

    def add_vpoints(self, vpoints: float):
        """If `self.vpoints` is set, add `vpoints` to it.
        Otherwise, leave `self.vpoints` as None."""
        if self.vpoints is not None:
            self.vpoints += vpoints

    @property
    def vpoints_str(self) -> str:
        return Utils.points_str(self.vpoints)

    @property
    def byes_count(self) -> int:
        byes_count = 0
        for pairing in self.pairings_by_round.values():
            if pairing.result == Result.HALF_POINT_BYE:
                byes_count += 1
            elif pairing.result == Result.FULL_POINT_BYE:
                byes_count += 2
        return byes_count

    def to_trf(
        self,
        after_round: int,
        next_round_pairings_as_zpb: bool,
    ) -> 'TrfPlayer':
        from data.input_output.trf.trf_data import TrfPlayer, TrfGame, TrfNationalPlayer

        games: list[TrfGame] = []
        from data.input_output.trf.trf_mappers import TrfPlayerGender, TrfPlayerTitle

        for round_nb, pairing in self.pairings.items():
            trf_game = pairing.to_trf(round_nb)
            if round_nb <= after_round:
                games.append(trf_game)
            elif (
                round_nb == after_round + 1
                and next_round_pairings_as_zpb
                and not pairing.needs_pairing
            ):
                games.append(
                    TrfGame(
                        opponent_id=0,
                        color='-',
                        result=Result.ZERO_POINT_BYE.to_trf,
                        round=round_nb,
                    )
                )
        trf_dob = ''
        if self.date_of_birth:
            trf_dob = self.date_of_birth.strftime('%Y/%m/%d')
        elif self.year_of_birth:
            trf_dob = f'{self.year_of_birth}/00/00'
        assert self.pairing_number is not None
        trf_player = TrfPlayer(
            id=self.pairing_number,
            name=(
                f'{self.last_name}{f", {self.first_name}" if self.first_name else ""}'
            )[:32],
            gender=TrfPlayerGender.get_outer_value(self.gender) or '',
            title=TrfPlayerTitle.get_outer_value(self.strongest_title) or '',
            rating=self.fide_rating_value or 0,
            federation=self.federation.name,
            fide_id=self.fide_id,
            birth_date=trf_dob,
            points=(
                self.team_trf_standard_points_after(after_round)
                if self.tournament.is_team_tournament
                # The 001 points field is ``11.5`` — unsigned — so a
                # penalty that takes a player below zero cannot be
                # written. bbpPairings floors the recomputed score the
                # same way, so the two still agree.
                else max(0.0, self.points_after(after_round))
            ),
            rank=self.rank,
            games=games,
        )
        np = TrfNationalPlayer(
            player_id=trf_player.id,
            rating=self.national_rating_value or 0,
        )
        plugin_manager.hook_for_event(self.event, 'augment_trf_national_player')(
            player=self, trf_national_player=np
        )
        if np.rating or np.classification or np.origin or np.national_id:
            trf_player.national_player_by_federation[self.event.federation] = np
        return trf_player

    # FIXME(Amaras): this should not be in the Player class
    def reset_board(self):
        self.board_id = None
        self.board_number = None
        self.color = None

    # FIXME(Amaras): this should not be in the Player class
    def set_board(self, board_id: int, board_number: int, color: BoardColor):
        self.board_id = board_id
        self.board_number = board_number
        self.color = color

    @property
    def matches_tournament_criteria(self) -> bool:
        return not self.failing_tournament_criteria

    @cached_property
    def failing_tournament_criteria(self) -> list['TournamentCriterion']:
        """Return the list of tournament criteria that the player does not match."""
        return [
            criterion
            for criterion in self.tournament.criteria
            if not criterion.is_player_included_function(self)
        ]

    @property
    def failing_tournament_criteria_message(self) -> str:
        """Return a formatted list of the failing tournament criteria."""
        locale = get_locale()
        return format_list(
            [criterion.full_name for criterion in self.failing_tournament_criteria],
            locale=locale,
        )

    def achieves_any_title_norm(
        self,
        min_games_override: int | None = None,
        rule_143_exemption: str = 'none',
    ) -> dict[TitleNorm, NormCheckResult]:
        from data.norms import TitleNormSubsetSearcher

        return TitleNormSubsetSearcher(
            self,
            min_games_override=min_games_override,
            rule_143_exemption=rule_143_exemption,
        ).evaluate()

    @cached_property
    def has_real_pairings(self) -> bool:
        """Returns True if the player has already been paired with an opponent
        (i.e. can not be deleted from the tournament anymore)."""
        for pairing in self.pairings.values():
            if pairing.opponent_id is not None or pairing.exempt:
                return True
        return False

    @cached_property
    def has_withdrawn(self) -> bool:
        """Returns True if the player has withdrawn from the tournament."""
        return self.has_withdrawn_for_round(self.tournament.current_round)

    def has_withdrawn_for_round(self, at_round: int) -> bool:
        """Check that the player only has zpbs for all remaining rounds."""
        rounds = self.tournament.rounds
        return all(
            self.pairings_by_round[round_].zero_point_bye
            for round_ in range(min(at_round or 1, rounds), rounds + 1)
        )

    @property
    def first_pab_round(self) -> int | None:
        return next(
            (
                round_
                for round_, pairing in self.pairings.items()
                if pairing.result == Result.PAIRING_ALLOCATED_BYE
            ),
            None,
        )

    def round_played_against(self, opponent_id: int) -> int | None:
        """Get the round at which the player has played against the player *opponent_id*.
        Return None if they have not played against each other."""
        return next(
            (
                round_
                for round_, pairing in self.pairings.items()
                if pairing.opponent_id == opponent_id
            ),
            None,
        )

    @cached_property
    def check_in_status(self) -> CheckInStatus:
        return self.check_in_status_for_round(self.tournament.current_round + 1)

    @property
    def check_in_status_no_bye(self) -> CheckInStatus:
        return CheckInStatus.PRESENT if self.check_in else CheckInStatus.ABSENT

    def check_in_status_for_round(self, round_: int) -> CheckInStatus:
        if self.has_withdrawn_for_round(round_):
            return CheckInStatus.WITHDRAWN
        if round_ <= self.tournament.rounds:
            match self.pairings_by_round[round_].result:
                case Result.ZERO_POINT_BYE:
                    return CheckInStatus.NEXT_ROUND_ZPB
                case Result.HALF_POINT_BYE:
                    return CheckInStatus.NEXT_ROUND_HPB
                case Result.FULL_POINT_BYE:
                    return CheckInStatus.NEXT_ROUND_FPB
        if self.check_in:
            return CheckInStatus.PRESENT
        return CheckInStatus.ABSENT

    @property
    def color_str(self) -> str:
        return str(self.color or '')

    # -------------------------------------------------------------------------
    # Ranking
    # -------------------------------------------------------------------------

    @property
    def tie_break_values(self) -> list[TieBreakValue]:
        """Returns the player's tie-break values."""
        assert self._tie_break_values is not None, (
            'Player._tie_break_values is not set, call Tournament.compute_player_ranks() before.'
        )
        return self._tie_break_values

    @property
    def leading_tie_break_value(self) -> TieBreakValue:
        """This player's value for :attr:`Tournament.leading_tie_break`."""
        return self.tie_break_values[0]

    @property
    def team_ranking_tie_break_values(self) -> list[TieBreakValue]:
        """Returns the player's tie-break values (only the tie-breaks used for team ranking)."""
        return [
            tie_break_value
            for tie_break_index, tie_break_value in enumerate(self.tie_break_values)
            if self.tournament.tie_breaks[tie_break_index].is_used_for_team_ranking
        ]

    def compute_tie_break_values(
        self,
        *,
        after_round: int,
        tie_breaks: list['TieBreak'] | None = None,
    ):
        if tie_breaks is None:
            tie_breaks = self.tournament.tie_breaks
        self._tie_break_values = [
            TieBreakValue(
                tie_break,
                tie_break.compute_player_value(self, after_round=after_round)
                if tie_break.is_computed_per_player
                else 0,
            )
            for tie_break in tie_breaks
        ]

    @property
    def rank(self) -> int:
        assert self._rank, (
            'Player._rank is not set, call Tournament.compute_player_ranks() before.'
        )
        return self._rank

    @rank.setter
    def rank(self, rank: int):
        self._rank = rank

    @cached_property
    def crosstable_strings(self) -> list[str]:
        assert self.tournament is not None
        return [
            pairing.result.to_crosstable
            + (
                f'{self.tournament.tournament_players_by_id[pairing.opponent_id].rank:>3}'
                f'{pairing.color.to_crosstable}'
                if pairing.opponent_id and pairing.color
                else ''
            )
            for pairing in self.pairings.values()
        ]

    @property
    def starting_rank_sort_key(self) -> tuple:
        return (-self.rating, -self.title.sort_index) + self.name_sort_key

    @property
    def board_number_sort_key(self) -> tuple:
        return -(self.vpoints or 0.0), self.pairing_number or 0

    def _rank_key_elements(self) -> list[float]:
        """This player's value for each ranking criterion, in order.

        Each value is negated, so sorting ascending puts the best player
        first: a bigger value is always better.

        The points are in this list like any other criterion, in the
        place the Points tie-break holds — they are not a separate first
        key. Every ranking key below is a slice of this list, so they all
        share one definition of the order.
        """
        return [
            -float(tie_break_value.value) for tie_break_value in self.tie_break_values
        ]

    @property
    def before_manual_rank_key(self) -> tuple:
        """The criteria that outrank the manual reorder — players sharing
        this key are the ones an arbiter may drag past one another.

        Without a manual tie-break there is nothing to delimit, and the
        key falls back to the leading criterion, which is what the ranking
        table groups its score groups by.
        """
        from data.tie_breaks.tie_breaks import ManualTieBreak

        elements = self._rank_key_elements()
        for index, tie_break_value in enumerate(self.tie_break_values):
            if isinstance(tie_break_value.tie_break, ManualTieBreak):
                return tuple(elements[:index])
        return tuple(elements[:1])

    def rank_sort_key_before_tie_break(self, tie_break_index: int) -> tuple:
        """Returns a rank sort key up to the tie-break of index *tie_break_index*."""
        return tuple(self._rank_key_elements()[:tie_break_index])

    def rank_sort_key_without_tie_break(self, tie_break_index: int) -> tuple:
        """Returns a rank sort key as if the tie-break of type *tie_break_type* was not set."""
        elements = self._rank_key_elements()
        assert self.pairing_number is not None
        return tuple(
            element
            for index, element in enumerate(elements)
            if index != tie_break_index
        ) + (self.pairing_number,)

    @property
    def rank_sort_key_without_pairing_number(self) -> tuple:
        return tuple(self._rank_key_elements())

    @property
    def rank_sort_key(self) -> tuple:
        return self.rank_sort_key_without_pairing_number + (self.pairing_number,)

    def __le__(self, other: 'TournamentPlayer') -> bool:
        # p1 <= p2 calls p1.__le__(p2)
        if not isinstance(other, TournamentPlayer):
            return NotImplemented
        return self.board_number_sort_key > other.board_number_sort_key

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        if not isinstance(other, TournamentPlayer):
            return NotImplemented
        return self.board_number_sort_key == other.board_number_sort_key

    def __str__(self):
        return (
            f'(#{self.id} rank={self._rank} ratings={self.ratings_str} '
            f'title={self.title.value} gender={self.gender.value} '
            f'name={self.last_name} {self.first_name} points={self.points})'
        )

    def __repr__(self):
        return f'{self.__class__.__name__}(tournament={self.tournament!r}, stored_tournament_player={self.stored_tournament_player!r})'

    # --------------------------------------------------------------------------
    # Legacy
    # --------------------------------------------------------------------------

    @property
    def pairings(self) -> dict[int, Pairing]:
        return self.pairings_by_round

    @property
    def has_played_games(self) -> bool:
        return any(pairing.played for pairing in self.pairings.values())

    @cached_property
    def is_excluded_from_standings(self) -> bool:
        """FIDE 6.6: in a round-robin, a player who completed less than 50%
        of their games is kept in the crosstable but dropped from the final
        standings, and their games are not counted in opponents' tie-breaks.

        The red flag for a leaver (withdrawn or expelled) is a voluntarily
        unplayed game — a forfeit loss or a requested bye. Two conditions,
        both required:

        - The player did not play their *last* scheduled game. Withdrawing
          or being expelled means they were gone by the end; a player who
          played their final round was present at the end and therefore did
          not leave, however many earlier games they missed.
        - More than half of their scheduled games are voluntarily unplayed
          (equivalently, they completed fewer than half).

        A forfeit *win* or a game still to be played counts as completed.
        """
        from data.pairings.systems import RoundRobinPairingSystem

        tournament = self.tournament
        if not tournament.round_robin_participation_rule:
            return False
        if tournament.pairing_system != RoundRobinPairingSystem():
            return False
        scheduled = [
            pairing
            for pairing in self.pairings.values()
            if pairing.opponent_id is not None
        ]
        if not scheduled:
            return False
        last_scheduled = max(scheduled, key=lambda pairing: pairing.round)
        if not last_scheduled.voluntary_unplayed:
            return False
        voluntarily_unplayed = sum(
            1 for pairing in scheduled if pairing.voluntary_unplayed
        )
        return voluntarily_unplayed * 2 > len(scheduled)

    def game_counts_for_tie_breaks(self, pairing: 'Pairing') -> bool:
        """False when *pairing* is against a player excluded from the final
        standings — that game must not feed any of this player's tie-breaks
        or opponent points (FIDE 6.6). Byes and holes (no opponent) are left
        for each tie-break to handle as before."""
        if pairing.opponent_id is None:
            return True
        opponent = self.tournament.tournament_players_by_id.get(pairing.opponent_id)
        return opponent is None or not opponent.is_excluded_from_standings

    def round_performance(self, round_index: int) -> float | None:
        """Single-round performance indicator: the Elo rating change (K=20)
        for the game played in ``round_index``, based on the opponent's rating
        and the result. ``None`` when that round was not played against an
        opponent (unplayed, bye or forfeit)."""
        pairing = self.pairings.get(round_index)
        if pairing is None or not pairing.opponent_id or not pairing.played:
            return None
        opponent = self.tournament.tournament_players_by_id[pairing.opponent_id]
        expected_score = 1 / (1 + 10 ** ((opponent.rating - self.rating) / 400))
        return 20 * (pairing.result.points() - expected_score)

    @property
    def round_performances(self) -> list[float]:
        """The per-round performance indicators of every game actually played."""
        return [
            performance
            for round_index in self.pairings
            if (performance := self.round_performance(round_index)) is not None
        ]

    @property
    def average_round_performance(self) -> float | None:
        """Average of the per-round performance indicators, ``None`` when the
        player has played no game."""
        performances = self.round_performances
        if not performances:
            return None
        return sum(performances) / len(performances)

    @property
    def best_round_performance(self) -> float | None:
        """Best of the per-round performance indicators, ``None`` when the
        player has played no game."""
        performances = self.round_performances
        return max(performances) if performances else None

    @property
    def has_been_paired(self) -> bool:
        """True if the player has ever been placed on a board (a real
        match slot) in any round. A bye — which carries a pairing but no
        board — does not count as being paired."""
        return any(
            stored_pairing.board_id is not None
            for stored_pairing in self.stored_tournament_player.stored_pairings
        )
