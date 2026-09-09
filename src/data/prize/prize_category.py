from functools import cached_property
from logging import Logger
import weakref
from _weakref import ReferenceType
from collections.abc import Collection
from typing import TYPE_CHECKING

from common.logger import get_logger
from common.i18n import _
from data.criteria.managers import PrizePlayerFilterManager
from data.player import TournamentPlayer
from data.prize.managers import PrizeSharingManager
from data.prize.prize_criterion import PrizeCriterion
from data.prize.prize import Prize
from data.prize.prize_sharing import PrizeSharing, NoPrizeSharing
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import (
    StoredPrizeCategory,
    StoredPrize,
    StoredPrizeCriterion,
)
from utils import Utils
from utils.enum import PrizeCategoryRankingBasis

if TYPE_CHECKING:
    from data.prize.prize_group import PrizeGroup

logger: Logger = get_logger()


class PrizeCategory:
    def __init__(
        self, prize_group: 'PrizeGroup', stored_prize_category: StoredPrizeCategory
    ):
        self._prize_group_ref: 'ReferenceType[PrizeGroup]' = weakref.ref(prize_group)
        self.stored_prize_category = stored_prize_category

    @cached_property
    def criteria_by_id(self) -> dict[int, PrizeCriterion]:
        criteria: list[PrizeCriterion] = []
        player_filter_ids = PrizePlayerFilterManager(
            self.prize_group.tournament.event
        ).ids()
        for stored_criterion in self.stored_prize_category.stored_prize_criteria:
            if stored_criterion.type not in player_filter_ids:
                logger.warning('Player filter [%s] not found.', stored_criterion.type)
                continue
            criteria.append(PrizeCriterion(self, stored_criterion))
        return {
            criterion.id: criterion
            for criterion in sorted(
                criteria,
                key=lambda c: player_filter_ids.index(c.stored_prize_criterion.type),
            )
        }

    @cached_property
    def prizes_by_id(self) -> dict[int, Prize]:
        prizes_by_id = {}
        for stored_entry in self.stored_prize_category.stored_prizes:
            assert stored_entry.id is not None
            prizes_by_id[stored_entry.id] = Prize(self, stored_entry)
        return prizes_by_id

    @property
    def prize_group(self) -> 'PrizeGroup':
        if (prize_group := self._prize_group_ref()) is None:
            raise RuntimeError('Reference has been garbage collected')
        return prize_group

    @property
    def id(self) -> int:
        assert self.stored_prize_category.id is not None
        return self.stored_prize_category.id

    @property
    def name(self) -> str:
        return self.stored_prize_category.name

    @property
    def is_main(self) -> bool:
        return self.stored_prize_category.is_main

    @property
    def sharing_threshold(self) -> float | None:
        return self.stored_prize_category.sharing_threshold

    @property
    def index(self) -> int:
        return self.stored_prize_category.index

    @property
    def ranking_basis(self) -> PrizeCategoryRankingBasis:
        return PrizeCategoryRankingBasis(self.stored_prize_category.ranking_basis)

    @property
    def ranks_by_final_standing(self) -> bool:
        return self.ranking_basis == PrizeCategoryRankingBasis.FINAL_STANDING

    @property
    def ranks_by_average_performance(self) -> bool:
        return self.ranking_basis == PrizeCategoryRankingBasis.AVERAGE_PERFORMANCE

    @property
    def ranks_by_best_round_performance(self) -> bool:
        return self.ranking_basis == PrizeCategoryRankingBasis.BEST_ROUND_PERFORMANCE

    @property
    def ranking_basis_name(self) -> str:
        return self.ranking_basis.name

    @property
    def prize_sharing(self) -> PrizeSharing:
        return PrizeSharingManager().get_object(
            self.stored_prize_category.prize_sharing
        )

    @property
    def criteria(self) -> Collection[PrizeCriterion]:
        return self.criteria_by_id.values()

    @property
    def prizes(self) -> Collection[Prize]:
        return self.prizes_by_id.values()

    @property
    def sorted_prizes(self) -> list[Prize]:
        return sorted(
            self.prizes,
            key=lambda prize: (-prize.value, not prize.is_monetary, prize.id),
        )

    def format_shared_prizes(self, currency: str) -> str:
        if not self.are_prizes_shared:
            return ''
        threshold_str = ''
        if self.sharing_threshold:
            threshold_str = ', ' + _('minimum: {value}').format(
                value=Utils.currency_value_str(self.sharing_threshold, currency)
            )
        return f'{_("Shared prizes")} ({self.prize_sharing.name}{threshold_str})'

    def player_matches_criteria(self, tournament_player: TournamentPlayer) -> bool:
        """Check if the player matches all criteria of this category."""
        return all(
            criterion.player_filter.is_player_included_function(tournament_player)
            for criterion in self.criteria
        )

    @property
    def tournament_players(self) -> list[TournamentPlayer]:
        return [
            tournament_player
            for tournament_player in self.prize_group.tournament.tournament_players
            if not tournament_player.is_excluded_from_standings
            and self.player_matches_criteria(tournament_player)
        ]

    def ranking_metric(self, tournament_player: TournamentPlayer) -> float | None:
        """The value used to rank a player within this category, according to
        the category's ranking basis. ``None`` for a performance basis when the
        player has played no game. ``None`` for the final-standing basis (the
        standing is expressed through the player rank, not a metric)."""
        match self.ranking_basis:
            case PrizeCategoryRankingBasis.AVERAGE_PERFORMANCE:
                return tournament_player.average_round_performance
            case PrizeCategoryRankingBasis.BEST_ROUND_PERFORMANCE:
                return tournament_player.best_round_performance
            case _:
                return None

    @property
    def sorted_tournament_players(self) -> list[TournamentPlayer]:
        if self.ranking_basis == PrizeCategoryRankingBasis.FINAL_STANDING:
            return sorted(
                self.tournament_players,
                key=lambda tournament_player: tournament_player.rank,
            )

        # Performance bases: highest metric first, players with no performance
        # last, ties broken by the tournament final standing.
        def sort_key(tournament_player: TournamentPlayer) -> tuple[bool, float, int]:
            metric = self.ranking_metric(tournament_player)
            return (metric is None, -(metric or 0.0), tournament_player.rank)

        return sorted(self.tournament_players, key=sort_key)

    @property
    def criteria_string(self) -> str:
        return ', '.join(criterion.name for criterion in self.criteria)

    @property
    def are_prizes_shared(self) -> bool:
        return self.prize_sharing != NoPrizeSharing()

    @property
    def has_non_monetary_prizes(self):
        return any(not prize.is_monetary for prize in self.prizes)

    @property
    def total_monetary_value(self) -> float:
        return sum(prize.monetary_value for prize in self.prizes)

    @property
    def total_non_monetary_value(self) -> float:
        return sum(prize.non_monetary_value for prize in self.prizes)

    def format_total_monetary_value(self, currency: str) -> str:
        return Utils.currency_value_str(self.total_monetary_value, currency)

    def format_total_non_monetary_value(self, currency: str) -> str:
        return Utils.currency_value_str(self.total_non_monetary_value, currency)

    def get_event_database(self) -> EventDatabase:
        return self.prize_group.get_event_database()

    def update(self):
        with self.get_event_database() as database:
            database.update_stored_prize_category(self.stored_prize_category)

    def add_criterion(self, stored_criterion: StoredPrizeCriterion) -> PrizeCriterion:
        with self.get_event_database() as database:
            object_id = database.add_stored_prize_criterion(stored_criterion)
        stored_criterion.id = object_id
        prize_criterion = PrizeCriterion(self, stored_criterion)
        self.criteria_by_id[object_id] = prize_criterion
        return prize_criterion

    def delete_criterion(self, criterion_id: int):
        with self.get_event_database() as database:
            database.delete_stored_prize_criterion(criterion_id)
        if criterion_id in self.criteria_by_id:
            del self.criteria_by_id[criterion_id]

    def add_prize(self, stored_prize: StoredPrize) -> Prize:
        with self.get_event_database() as database:
            object_id = database.add_stored_prize(stored_prize)
        prize = Prize(self, stored_prize)
        stored_prize.id = object_id
        self.prizes_by_id[object_id] = prize
        return prize

    def delete_prize(self, prize_id: int):
        with self.get_event_database() as database:
            database.delete_stored_prize(prize_id)
        if prize_id in self.prizes_by_id:
            del self.prizes_by_id[prize_id]

    def __str__(self):
        return f'{self.__class__.__name__} - {self.id}/{self.name}'

    def __repr__(self):
        return f'{self.__class__.__name__}(prize_group={self.prize_group!r}, stored_prize_category={self.stored_prize_category!r})'
