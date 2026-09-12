"""The player search filters: the categories `SearchFilterManager` offers,
the filters loaded from a tournament's criteria, and their conversion into
the birth year intervals the player databases are queried with."""

import json
from datetime import date

import pytest

from data.board import PlayerRatingType
from data.criteria.managers import SearchFilterManager
from data.event import Event
from data.player_categories import NoCategory
from database.sqlite.event.event_store import StoredEvent, StoredTournament
from web.controllers.admin.player_admin_controller import PlayerAdminController

# The event categories below are U10 and U14, which the event completes with
# the O14 filler, plus O20 and O50. With the base date below, the
# representative years are U10: 2016, U14: 2012, O14: 2011, O20: 2005 and
# O50: 1975.
AGE_CATEGORIES: list[str] = ['U10', 'U14', 'O20', 'O50']
BASE_DATE: date = date(2026, 1, 1)


def _event(criteria: dict | None = None, tournaments: bool = True) -> Event:
    stored_tournaments: list[StoredTournament] = []
    if tournaments:
        stored_tournaments.append(
            StoredTournament(
                id=1,
                name='Tournament',
                start_date=date(2026, 6, 1),
                stop_date=date(2026, 6, 3),
                criteria=criteria or {},
            )
        )
    return Event(
        StoredEvent(
            uniq_id='search-filters-test',
            name='Search filters test',
            federation='FRA',
            player_rating_type=PlayerRatingType.FIDE.value,
            enabled_plugins=[],
            age_category_base_date=BASE_DATE,
            age_categories=AGE_CATEGORIES,
            stored_tournaments=stored_tournaments,
        )
    )


def _age_criteria(min_id: str | None, max_id: str | None) -> dict:
    return {'age_category': {'min': min_id, 'max': max_id}}


def _loaded_categories(event: Event) -> list[str]:
    filters = SearchFilterManager(event).get_filters_by_tournament()[1]
    return dict(filters)['category_filter']


def _year_intervals(event: Event, category_ids: list[str]) -> list[tuple]:
    filters = PlayerAdminController._convert_filters(
        event, json.dumps({'category_filter': category_ids})
    )
    return filters['year_of_birth_filter']


class TestGetFilters:
    def test_categories_exclude_the_no_category_filler(self):
        options = SearchFilterManager(_event()).get_filters()['category']['options']
        assert list(options) == ['U10', 'U14', 'O14', 'O20', 'O50']

    def test_the_event_categories_are_left_alone(self):
        event = _event()
        manager = SearchFilterManager(event)
        manager.get_filters()
        manager.get_filters()
        assert isinstance(event.player_categories[0], NoCategory)
        assert len(event.player_categories) == 6


class TestGetFiltersByTournament:
    @pytest.mark.parametrize(
        'min_id, max_id, expected',
        [
            ('U14', 'O20', ['U14', 'O14', 'O20']),
            ('U14', 'U14', ['U14']),
            ('O20', 'O20', ['O20']),
            ('O20', None, ['O20', 'O50']),
            (None, 'U14', ['U10', 'U14']),
            (None, None, ['U10', 'U14', 'O14', 'O20', 'O50']),
        ],
    )
    def test_categories_between_the_criterion_bounds(self, min_id, max_id, expected):
        event = _event(criteria=_age_criteria(min_id, max_id))
        assert _loaded_categories(event) == expected

    def test_a_bound_outside_the_event_categories_is_clamped(self):
        event = _event(criteria=_age_criteria('U12', 'O30'))
        assert _loaded_categories(event) == ['U14', 'O14', 'O20']


class TestConvertFilters:
    @pytest.mark.parametrize(
        'category_ids, expected',
        [
            (['U10'], [(2016, None)]),
            (['U14'], [(2012, 2015)]),
            (['O20'], [(1976, 2005)]),
            (['O50'], [(None, 1975)]),
            (['U10', 'U14'], [(2012, None)]),
            (['U10', 'O20'], [(2016, None), (1976, 2005)]),
        ],
    )
    def test_categories_become_birth_year_intervals(self, category_ids, expected):
        assert _year_intervals(_event(), category_ids) == expected

    def test_the_categories_are_ordered_before_being_merged(self):
        assert _year_intervals(_event(), ['U14', 'U10']) == [(2012, None)]

    @pytest.mark.parametrize('category_id', ['ZZ9', 'NONE', 'U12', ''])
    def test_a_category_the_event_does_not_offer_is_ignored(self, category_id):
        assert _year_intervals(_event(), [category_id]) == []

    def test_an_event_without_a_tournament(self):
        assert _year_intervals(_event(tournaments=False), ['U10']) == [(2016, None)]

    def test_invalid_json(self):
        assert PlayerAdminController._convert_filters(_event(), 'not json') == {}

    def test_the_other_filters_are_passed_through(self):
        filters = PlayerAdminController._convert_filters(
            _event(), json.dumps({'federation_filter': 'FRA'})
        )
        assert filters == {'federation_filter': 'FRA'}
