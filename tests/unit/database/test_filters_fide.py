from database.sqlite.fide.fide_database import FideDatabase
import pytest
import sqlite3


@pytest.fixture
def init_mock_FIDE_database():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()
    cursor.executescript("""
        CREATE TABLE player (
            blitz_rating INTEGER,
            fide_id TEXT PRIMARY KEY,
            federation TEXT,
            fide_arbiter_title TEXT,
            fide_title TEXT,
            fide_women_title TEXT,
            first_name TEXT,
            gender VARCHAR(50),
            last_name TEXT,
            rapid_rating INTEGER,
            standard_rating INTEGER,
            year_of_birth INTEGER
        );""")

    mock_data = [
        ('0000001', 'FRA', 'Alice', 'Dupont', 'F', '2000'),
        ('0000002', 'FRA', 'Benoit', 'Dupont', 'H', '1992'),
        ('0000003', 'FRA', 'Christine', 'Dupont', 'F', '1960'),
        ('0000004', 'FRA', 'David', 'Dupont', 'H', '1972'),
        ('0000005', 'FRA', 'Eva', 'Dupont', 'F', '1986'),
        ('0000006', 'FRA', 'Frank', 'Dupont', 'H', '2012'),
        ('0000007', 'FRA', 'Gerard', 'Dupont', 'H', '1949'),
        ('0000008', 'FRA', 'Hanna', 'Dupont', 'F', '2008'),
        ('0000009', 'UKR', 'Igor', 'Dupont', 'H', '2015'),
        ('0000010', 'FRA', 'Jacques', 'Dupont', 'H', '2003'),
    ]

    cursor.executemany(
        'INSERT INTO player (fide_id, federation, first_name, last_name, gender, year_of_birth) VALUES (?, ?, ?, ?, ?, ?)',
        mock_data,
    )

    database = FideDatabase()
    database.database = connection
    database.cursor = connection.cursor()
    connection.commit()

    return database


def test_no_filter(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    result = database.search_player('dupont', 'FRA', 1, None, {})
    assert len(result) == 10


def test_federation_filter(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    for filters, expected_result_count in [
        ({'federation_filter': 'FRA'}, 9),
        ({'federation_filter': 'UKR'}, 1),
        ({'federation_filter': 'GER'}, 0),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == expected_result_count
        assert all(
            player.federation == filters['federation_filter'] for player in result
        )


@pytest.mark.unit
def test_gender_filter(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    for filters, expected_result_count in [
        ({'gender_filter': 'F'}, 4),
        ({'gender_filter': 'H'}, 6),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == expected_result_count
        assert all(player.gender == filters['gender_filter'] for player in result)


@pytest.mark.unit
def test_year_of_birth_filter(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    for filters, expected_result in [
        (
            {'year_of_birth_filter': [(None, None)]},
            [
                'Alice',
                'Benoit',
                'Christine',
                'David',
                'Eva',
                'Frank',
                'Gerard',
                'Hanna',
                'Igor',
                'Jacques',
            ],
        ),
        (
            {'year_of_birth_filter': [(2003, None)]},
            ['Frank', 'Hanna', 'Igor', 'Jacques'],
        ),
        (
            {'year_of_birth_filter': [(None, 1998)]},
            ['Benoit', 'Christine', 'David', 'Eva', 'Gerard'],
        ),
        ({'year_of_birth_filter': [(2005, 2015)]}, ['Frank', 'Hanna', 'Igor']),
        (
            {
                'year_of_birth_filter': [
                    (None, 1966),
                    (1973, 1984),
                    (1990, 1998),
                    (2009, None),
                ]
            },
            ['Benoit', 'Christine', 'Frank', 'Gerard', 'Igor'],
        ),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == len(expected_result)
        assert all(player.first_name in expected_result for player in result)


@pytest.mark.unit
def test_all_filters(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    for filters, expected_result in [
        (
            {
                'year_of_birth_filter': [(1950, 2000)],
                'gender_filter': 'F',
                'federation_filter': 'FRA',
            },
            ['Alice', 'Christine', 'Eva'],
        ),
        (
            {
                'year_of_birth_filter': [(None, 1970), (2010, 2016)],
                'gender_filter': 'H',
                'federation_filter': 'FRA',
            },
            ['Frank', 'Gerard'],
        ),
        (
            {
                'year_of_birth_filter': [(None, 2014), (2016, None)],
                'gender_filter': 'F',
                'federation_filter': 'UKR',
            },
            [],
        ),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == len(expected_result)
        assert all(player.first_name in expected_result for player in result)


def test_a_filter_value_is_not_read_as_sql(init_mock_FIDE_database):
    database = init_mock_FIDE_database

    result = database.search_player(
        'dupont', 'FRA', 1, None, {'federation_filter': "FRA' OR '1'='1"}
    )
    assert result == []
