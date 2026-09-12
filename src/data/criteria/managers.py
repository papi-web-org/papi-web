from typing import TYPE_CHECKING, Any, override
from common.sharly_chess_config import SharlyChessConfig
from data.criteria.player_filter_options import PlayerFilterOption
from data.criteria.player_filters import PlayerFilter
from data.criteria import tournament_criteria as crit
from data.criteria.tournament_criteria import (
    AgeCategoryTournamentCriterion,
    ClubTournamentCriterion,
    FederationTournamentCriterion,
    GenderTournamentCriterion,
    RatingTournamentCriterion,
    TournamentCriterion,
)
from data.player_categories import NoCategory, PlayerCategory
from plugins.manager import plugin_manager
from utils.entity import EventBoundEntityManager
from utils.enum import PlayerGender

if TYPE_CHECKING:
    from data.event import Event


class PrizePlayerFilterManager(EventBoundEntityManager[PlayerFilter]):
    def entity_types(self) -> list[type[PlayerFilter]]:
        from data.criteria import player_filters as filters

        player_filters: list[type[PlayerFilter]] = [
            filters.GenderPlayerFilter,
            filters.RatingPlayerFilter,
            filters.AgePlayerFilter,
            filters.RatingTypePlayerFilter,
            filters.ClubPlayerFilter,
            filters.FederationPlayerFilter,
            filters.CommentPlayerFilter,
            filters.PlayerIdPlayerFilter,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_player_filter_types')(
            player_filter_types=player_filters
        )
        return player_filters


class PlayerFilterOptionManager(EventBoundEntityManager[PlayerFilterOption]):
    @override
    def entity_types(self) -> list[type[PlayerFilterOption]]:
        from data.criteria import player_filter_options as options

        filter_options: list[type[PlayerFilterOption]] = [
            options.GenderOption,
            options.MinRatingOption,
            options.MaxRatingOption,
            options.MinAgeCategoryOption,
            options.MaxAgeCategoryOption,
            options.RatingTypesFilterOption,
            options.ClubsFilterOption,
            options.FederationsFilterOption,
            options.CommentsFilterOption,
            options.PlayersFilterOption,
            options.ExcludeFilterOption,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_player_filter_option_types')(
            player_filter_option_types=filter_options
        )
        return filter_options


class TournamentCriterionManager(EventBoundEntityManager[TournamentCriterion]):
    def entity_types(self) -> list[type[TournamentCriterion]]:
        criteria: list[type[TournamentCriterion]] = [
            crit.RatingTournamentCriterion,
            crit.AgeCategoryTournamentCriterion,
            crit.GenderTournamentCriterion,
            crit.ClubTournamentCriterion,
            crit.FederationTournamentCriterion,
        ]
        plugin_manager.hook_for_event(self.event, 'insert_tournament_criteria_types')(
            criteria_types=criteria
        )
        return criteria


class SearchFilterManager:
    def __init__(self, event: 'Event'):
        self.event = event

    @property
    def _filterable_categories(self) -> list[PlayerCategory]:
        return [
            category
            for category in self.event.player_categories
            if not isinstance(category, NoCategory)
        ]

    def get_filters(self) -> dict[str, Any]:
        federations = {'': '-'} | {
            federation_id: f'{federation_id} - {federation_name}'
            for federation_id, federation_name in SharlyChessConfig().federations.items()
        }
        if 'NON' in federations:
            del federations['NON']

        filters = {
            'federation': {
                'template_name': 'search_filters/federation.html',
                'options': federations,
            },
            'gender': {
                'template_name': 'search_filters/gender.html',
                'options': {gender: gender.name for gender in PlayerGender},
            },
            'category': {
                'template_name': 'search_filters/category.html',
                'options': {
                    category.id: category.name
                    for category in self._filterable_categories
                },
            },
            'club': {
                'template_name': 'search_filters/club.html',
            },
        }
        plugin_manager.hook_for_event(self.event, 'insert_search_filter_types')(
            filters=filters
        )

        return filters

    def get_filters_by_datasource(self) -> dict:
        datasource_mapping = {
            'fide': ['federation_filter', 'gender_filter', 'category_filter']
        }

        plugin_manager.hook_for_event(
            self.event, 'insert_search_filter_for_datasource'
        )(datasource_mapping=datasource_mapping)
        return datasource_mapping

    def get_filters_by_tournament(self) -> dict:
        mapping = {}

        for tournament in self.event.tournaments:
            filter_list: list[tuple] = []
            for criterion in tournament.criteria:
                if isinstance(criterion, AgeCategoryTournamentCriterion):
                    min_category, max_category = criterion.category_limits
                    filter_list.append(
                        (
                            'category_filter',
                            [
                                category.id
                                for category in self._filterable_categories
                                if (min_category is None or not category < min_category)
                                and (
                                    max_category is None or not max_category < category
                                )
                            ],
                        )
                    )

                elif isinstance(criterion, ClubTournamentCriterion):
                    filter_list.append(('club_filter', criterion.value))

                elif isinstance(criterion, FederationTournamentCriterion):
                    filter_list.append(('federation_filter', criterion.value))

                elif isinstance(criterion, GenderTournamentCriterion):
                    filter_list.append(('gender_filter', criterion.value))

                elif isinstance(criterion, RatingTournamentCriterion):
                    pass  # criterion not mapped to a filter

                else:
                    plugin_manager.hook_for_event(
                        self.event, 'map_filter_to_tournament_criteria'
                    )(filter_list=filter_list, criterion=criterion)
            mapping[tournament.id] = filter_list
        return mapping
