from plugins.ffe.ffe_database import FfeDatabase
import pytest
import sqlite3


@pytest.fixture
def init_mock_FFE_database():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()
    cursor.executescript("""
        CREATE TABLE player (
            blitz_rating INTEGER,
            blitz_rating_type INTEGER,
            club TEXT,
            federation TEXT,
            ffe_arbiter_title TEXT,
            ffe_id TEXT,
            ffe_licence TEXT,
            ffe_licence_number TEXT,
            fide_arbiter_title TEXT,
            fide_id TEXT PRIMARY KEY,
            fide_title TEXT,
            fide_women_title TEXT,
            first_name TEXT,
            gender VARCHAR(50),
            last_name TEXT,
            league TEXT,
            rapid_rating INTEGER,
            rapid_rating_type INTEGER,
            standard_rating INTEGER,
            standard_rating_type INTEGER,
            date_of_birth TEXT
        );""")

    mock_data = [
        (
            '0000001',
            'FRA',
            'Alice',
            'Dupont',
            'F',
            '2000-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'A',
        ),
        (
            '0000002',
            'FRA',
            'Benoit',
            'Dupont',
            'M',
            '1992-01-01',
            'BFC',
            '',
            3,
            3,
            3,
            'B',
        ),
        (
            '0000003',
            'FRA',
            'Christine',
            'Dupont',
            'F',
            '1960-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'A',
        ),
        (
            '0000004',
            'FRA',
            'David',
            'Dupont',
            'M',
            '1972-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'A',
        ),
        ('0000005', 'FRA', 'Eva', 'Dupont', 'F', '1986-01-01', 'EST', '', 3, 3, 3, 'N'),
        (
            '0000006',
            'FRA',
            'Frank',
            'Dupont',
            'M',
            '2012-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'A',
        ),
        (
            '0000007',
            'FRA',
            'Gerard',
            'Dupont',
            'M',
            '1949-01-01',
            'BFC',
            '',
            3,
            3,
            3,
            'B',
        ),
        (
            '0000008',
            'FRA',
            'Hanna',
            'Dupont',
            'F',
            '2008-01-01',
            'BFC',
            '',
            3,
            3,
            3,
            'N',
        ),
        (
            '0000009',
            'UKR',
            'Igor',
            'Dupont',
            'M',
            '2015-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'N',
        ),
        (
            '0000010',
            'FRA',
            'Jacques',
            'Dupont',
            'M',
            '2003-01-01',
            'EST',
            '',
            3,
            3,
            3,
            'B',
        ),
    ]

    cursor.executemany(
        'INSERT INTO player (fide_id, federation, first_name, last_name, gender, date_of_birth, league, fide_title, standard_rating_type, rapid_rating_type, blitz_rating_type, ffe_licence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        mock_data,
    )

    database = FfeDatabase()
    database.database = connection
    database.cursor = connection.cursor()
    connection.commit()

    return database


def test_no_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

    result = database.search_player('dupont', 'FRA', 1, None, {})
    assert len(result) == 10


def test_federation_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

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


def test_gender_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

    for filters, expected_result_count in [
        ({'gender_filter': 'F'}, 4),
        ({'gender_filter': 'M'}, 6),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == expected_result_count
        assert all(player.gender == filters['gender_filter'] for player in result)


def test_ffe_licence_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

    for filters, expected_result_count in [
        ({'ffe_licence_filter': 'B'}, 8),
        ({'ffe_licence_filter': 'A'}, 5),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == expected_result_count
        assert all(
            (
                player.plugin_data['ffe']['ffe_licence'] in ['A']
                if filters['ffe_licence_filter'] == 'A'
                else ['A', 'B']
            )
            or player.federation != 'FRA'
            for player in result
        )


def test_ffe_league_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

    for filters, expected_result_count in [
        ({'ffe_league_filter': 'EST'}, 7),
        ({'ffe_league_filter': 'BFC'}, 3),
        ({'ffe_league_filter': 'IDF'}, 0),
    ]:
        result = database.search_player('dupont', 'FRA', 1, None, filters)
        assert len(result) == expected_result_count
        assert all(
            player.plugin_data['ffe']['league'] == filters['ffe_league_filter']
            for player in result
        )


def test_year_of_birth_filter(init_mock_FFE_database):
    database = init_mock_FFE_database

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
        ({'year_of_birth_filter': [(2005, 2014)]}, ['Frank', 'Hanna']),
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


def test_club_filter(init_mock_FFE_database):
    database = init_mock_FFE_database
    database.database.execute('UPDATE player SET club = ?', ("L'Echiquier Rennais",))
    database.database.execute(
        'UPDATE player SET club = ? WHERE fide_id = ?', ('Club de Paris', '0000001')
    )
    database.database.commit()

    for club_filter, expected_result_count in [
        ("L'Echiquier Rennais", 9),
        ('echiquier', 9),
        ('PARIS', 1),
        ('Club de Lyon', 0),
        # An interpolated value would match every player here.
        ("' OR 1=1 --", 0),
    ]:
        result = database.search_player(
            'dupont', 'FRA', 1, None, {'club_filter': club_filter}
        )
        assert len(result) == expected_result_count
