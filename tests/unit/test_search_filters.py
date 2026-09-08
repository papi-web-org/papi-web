"""The player search filters: the categories `SearchFilterManager` offers
and the filters loaded from a tournament's criteria."""

from datetime import date

import pytest

from data.board import PlayerRatingType
from data.criteria.managers import SearchFilterManager
from data.event import Event
from data.player_categories import NoCategory
from database.sqlite.event.event_store import StoredEvent, StoredTournament

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
