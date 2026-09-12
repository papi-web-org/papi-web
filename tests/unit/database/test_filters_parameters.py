"""Search filter values reach the player databases as a JSON query
parameter, so `_process_filters()` must bind them rather than write them
into the SQL. The remote _FFE_ SQL Server has no other coverage: its
queries cannot be run against an in-memory database."""

from database.sqlite.fide.fide_database import FideDatabase
from plugins.ffe.ffe_database import FfeDatabase
from plugins.ffe.ffe_sql_server import FFESqlServer

# A club name with an apostrophe is enough to break an interpolated query.
CLUB: str = "L'Echiquier"


def test_ffe_local_filters_are_bound():
    conditions, params = FfeDatabase._process_filters(
        {
            'federation_filter': 'FRA',
            'gender_filter': 'F',
            'ffe_league_filter': 'BFC',
            'club_filter': CLUB,
            'year_of_birth_filter': [(1990, 2000), (None, 1980), (2010, None)],
        }
    )
    sql = ' AND '.join(conditions)
    assert sql.count('?') == len(params)
    assert CLUB not in sql
    assert params == ['FRA', 'F', 'BFC', f'%{CLUB}%', '1990', '2000', '1980', '2010']


def test_fide_filters_are_bound():
    conditions, params = FideDatabase._process_filters(
        {
            'federation_filter': 'FRA',
            'gender_filter': 'F',
            'year_of_birth_filter': [(1990, 2000)],
        }
    )
    sql = ' AND '.join(conditions)
    assert sql.count('?') == len(params)
    assert params == ['FRA', 'F', '1990', '2000']


def test_ffe_online_filters_are_bound():
    conditions, params = FFESqlServer._process_filters(
        {
            'federation_filter': 'FRA',
            'gender_filter': 'F',
            'ffe_league_filter': 'BFC',
            'club_filter': CLUB,
            'year_of_birth_filter': [(1990, 2000), (None, 1980), (2010, None)],
        }
    )
    sql = ' AND '.join(conditions)
    assert sql.count('%s') == len(params)
    assert CLUB not in sql
    assert params == ['FRA', 'F', 'BFC', f'%{CLUB}%', 1990, 2000, 1980, 2010]


def test_the_licence_filter_holds_no_value():
    conditions, params = FFESqlServer._process_filters({'ffe_licence_filter': 'A'})
    assert len(conditions) == 1
    assert params == []
