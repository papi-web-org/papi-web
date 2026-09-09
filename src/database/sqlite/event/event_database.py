import shutil
from collections import defaultdict
from datetime import datetime
from collections.abc import Iterator
from functools import cached_property
from logging import Logger
from pathlib import Path
from typing import Any, TYPE_CHECKING, Sequence, override, cast

from packaging.version import Version

from common import (
    DEVEL_ENV,
    EVENTS_DIR,
)
from common.logger import get_logger
from data.event_metadata import EventMetadata
from database.sqlite.event.event_store import (
    StoredDisplayController,
    StoredTournament,
    StoredEvent,
    StoredTimer,
    StoredTimerHour,
    StoredFamily,
    StoredRotator,
    StoredMenu,
    StoredMenuItem,
    StoredScreenSet,
    StoredScreen,
    StoredPrizeGroup,
    StoredProhibitedPairingGroup,
    StoredPrizeCategory,
    StoredPrizeCriterion,
    StoredPrize,
    StoredPlayer,
    StoredTournamentPlayer,
    StoredPairing,
    StoredBoard,
    StoredAccount,
    StoredRotatingScreen,
    StoredPermission,
    StoredRole,
    StoredTieBreak,
    StoredTeam,
    StoredTeamBoard,
    StoredTeamGroup,
    StoredTeamPairingBlock,
    StoredTeamPointAdjustment,
    StoredPlayerPointAdjustment,
    StoredTeamRoundLineupEntry,
)
from database.sqlite.event import migrations
from database.sqlite.migration_database import MigrationDatabase
from plugins.manager import plugin_manager
from utils.enum import Extension, EventType

if TYPE_CHECKING:
    from data.loader import EventBackup
    from database.sqlite.migration import DatabaseMigrationManager

logger: Logger = get_logger()


class EventDatabase(MigrationDatabase):
    """The SQLite database class for Sharly Chess events."""

    def __init__(
        self,
        uniq_id: str | None = None,
        write: bool = False,
        *,
        file_path: Path | None = None,
        check_dirty_tournaments: bool = True,
        enable_foreign_keys: bool = True,
    ):
        """Initialize EventDatabase with either a unique ID or a file path."""
        if uniq_id is not None and file_path is not None:
            raise ValueError('Cannot specify both uniq_id and file_path')
        if uniq_id is None and file_path is None:
            raise ValueError('Must specify either uniq_id or file_path')
        self.check_dirty_tournaments = check_dirty_tournaments

        if file_path is not None:
            # Initialize with file path
            self.uniq_id = file_path.stem
        else:
            # Traditional initialization with uniq_id
            assert uniq_id is not None
            self.uniq_id = uniq_id
            file_path = self.event_database_path(self.uniq_id)
        super().__init__(file_path, write, enable_foreign_keys=enable_foreign_keys)

    def __exit__(self, exc_type, exc_value, tb):
        dirty_tournaments: list[StoredTournament] = []
        stored_event: StoredEvent | None = None

        try:
            if (
                self.write
                and exc_type is None
                and self.check_dirty_tournaments
                # When auto-uploading to the FFE website, the database is copied to
                # tmpdir/event.sce. Not taking the database path into account will make the hook below
                # try to load the wrong event (which will error out or load an unrelated event).
                and self.event_database_path(self.uniq_id).resolve()
                == self.file.resolve()
            ):
                try:
                    self.execute('SELECT * FROM tournament WHERE dirty = 1;')
                    dirty_tournaments = [
                        self._row_to_stored_tournament(row) for row in self.fetchall()
                    ]
                    if dirty_tournaments:
                        self.execute('SELECT * FROM `info`')
                        stored_event = self._row_to_base_stored_event(
                            self.fetchone(), StoredEvent
                        )
                        self.execute('UPDATE tournament SET dirty = 0 WHERE dirty = 1;')
                except Exception as e:
                    # Log but don’t block cleanup
                    logger.exception(
                        'Error in EventDatabase.__exit__ pre-cleanup: %s',
                        e,
                    )
        finally:
            # Always release DB
            super().__exit__(exc_type, exc_value, tb)

        # We need to call the hook on all dirty tournaments after committing the changes above
        for stored_tournament in dirty_tournaments:
            plugin_manager.hook.on_tournament_data_updated(
                stored_event=stored_event,
                stored_tournament=stored_tournament,
            )

    @cached_property
    def migration_managers(self) -> list['DatabaseMigrationManager']:
        from database.sqlite.migration import DatabaseMigrationManager

        return [DatabaseMigrationManager(self, migrations)] + (
            plugin_manager.hook.get_event_migration_manager(event_database=self)
        )

    @property
    def migration_by_legacy_version(self) -> dict[Version, str]:
        return {
            Version('2.4.0'): 'm001_create_database',
            Version('2.4.2'): 'm002_alter_screens',
            Version('2.4.4'): 'm003_add_input_exit_buttons',
            Version('2.4.5'): 'm004_drop_rotator_show_menu',
            Version('2.4.8'): 'm005_add_hide_background_image',
            Version('2.4.12'): 'm006_add_rules',
            Version('2.4.13'): 'm007_add_last_ffe_rules_upload',
            Version('2.4.16'): 'm008_add_messages',
            Version('2.4.20'): 'm009_add_tournament_check_in_open',
            Version('2.4.21'): 'm010_refactor_chessevent',
            Version('2.4.22'): 'm011_add_tournament_byes',
            Version('2.4.23'): 'm012_add_tournament_tie_breaks',
            Version('2.4.24'): 'm013_replace_tournament_paired_bye_points',
            Version('2.4.25'): 'm014_mark_plugin_columns_as_deprecated',
            Version('2.4.26'): 'm015_add_screen_ranking',
            Version('2.4.27'): 'm016_add_family_ranking',
        }

    @property
    def migration_instance_kwargs(self) -> dict[str, Any]:
        return {
            'file_path': self.file,
            'check_dirty_tournaments': False,
        }

    @property
    def log_prefix(self) -> str:
        return f'Database [{self.uniq_id}] - '

    @override
    def upgrade(self):
        if DEVEL_ENV:
            with self.get_migration_instance() as database:
                if database.is_metadata_table_installed():
                    database.create_backup()
        super().upgrade()

    @staticmethod
    def event_database_path(uniq_id: str) -> Path:
        return EVENTS_DIR / f'{uniq_id}.{Extension.EVENT_DB}'

    @classmethod
    def database_modified_at(cls, uniq_id: str) -> datetime:
        return datetime.fromtimestamp(cls.event_database_path(uniq_id).lstat().st_mtime)

    def delete(self) -> Path:
        """Soft-deletes the event database file by archiving it."""
        from data.loader import ArchiveLoader, EventLoader

        index = 0
        arch_file = ArchiveLoader.get_archive_path(self.uniq_id)
        while arch_file.exists():
            index += 1
            arch_file = ArchiveLoader.get_archive_path(f'{self.uniq_id}#{index}')
        arch_file.parent.mkdir(parents=True, exist_ok=True)
        self.file.rename(arch_file)
        logger.info('Database has been archived (%s).', arch_file)
        EventLoader.unload_event(self.uniq_id)
        return arch_file

    def rename(self, new_uniq_id: str):
        """Changes the event file database to the one associated to the
        provided `new_uniq_id`."""

        from data.loader import EventLoader

        self.file.rename(EventDatabase(new_uniq_id).file)
        EventLoader.unload_event(self.uniq_id)

    def clone(self, new_uniq_id: str):
        """Create a copy of the event database file corresponding to an event
        with name `new_uniq_id`."""

        shutil.copy(self.file, EventDatabase(new_uniq_id).file)

    def create_backup(self) -> 'EventBackup':
        """Creates a backup of the event database.
        If a backup already exists for the same version, overwrite it."""
        from data.loader import EventBackup

        backup = EventBackup(self.uniq_id, self.get_version())
        backup.file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.file, backup.file)
        return backup

    # ---------------------------------------------------------------------------------
    # Utils
    # ---------------------------------------------------------------------------------

    @classmethod
    def dump_to_json_database_timer_colors(cls, colors) -> str | None:
        """Serializes the timer colors into JSON.
        By default, returns a serialization of {i: None} (i in (1, 2, 3))."""
        return cls.dump_to_json_database_field(colors, {i: None for i in range(1, 4)})

    @classmethod
    def dump_to_json_database_timer_delays(cls, delays) -> str | None:
        """Serializes the timer delays into JSON.
        By default, returns a serialization of {i: None} (i in (1, 2, 3))."""
        return cls.dump_to_json_database_field(delays, {i: None for i in range(1, 4)})

    # ---------------------------------------------------------------------------------
    # Plugin metadata
    # ---------------------------------------------------------------------------------

    def create_plugin_metadata_table(self):
        self.execute(
            'CREATE TABLE IF NOT EXISTS `plugin_metadata` ('
            '   `name` TEXT NOT NULL,'
            '   `version` TEXT NOT NULL,'
            "   `migration` TEXT NOT NULL DEFAULT 'm000_no_migration',"
            '    PRIMARY KEY(`name`)'
            ')'
        )

    def is_plugin_in_metadata_table(self, plugin_id: str) -> bool:
        self.execute('SELECT 1 FROM `plugin_metadata` WHERE `name` = ?', (plugin_id,))
        return '1' in self.fetchone()

    def insert_plugin_metadata(self, plugin_id: str, version: Version):
        self.execute(
            'INSERT INTO `plugin_metadata` (`name`, `version`) VALUES (?, ?)',
            (plugin_id, str(version)),
        )

    def get_plugin_migration(self, plugin_id: str) -> str:
        self.execute(
            'SELECT `migration` FROM `plugin_metadata` WHERE `name` = ?', (plugin_id,)
        )
        return self.fetchone()['migration']

    def set_plugin_migration(self, plugin_id: str, migration: str):
        self.execute(
            'UPDATE `plugin_metadata` SET `migration` = ? WHERE `name` = ?',
            (migration, plugin_id),
        )

    def get_plugin_version(self, plugin_id: str) -> Version:
        self.execute(
            'SELECT `version` FROM `plugin_metadata` WHERE `name` = ?', (plugin_id,)
        )
        return Version(self.fetchone()['version'])

    def set_plugin_version(self, plugin_id: str, version: Version):
        self.execute(
            'UPDATE `plugin_metadata` SET `version` = ? WHERE `name` = ?',
            (str(version), plugin_id),
        )

    # ---------------------------------------------------------------------------------
    # StoredEvent
    # ---------------------------------------------------------------------------------

    def _row_to_base_stored_event[T: StoredEvent | EventMetadata](
        self, row: dict[str, Any], stored_event_type: type[T]
    ) -> T:
        """Convert a row to a StoredEvent record."""
        stored_event = stored_event_type(
            uniq_id=self.uniq_id,
            name=row['name'],
            federation=row.get('federation', ''),
            player_rating_type=row.get('player_rating_type', 3),
            public=self.load_bool_from_database_field(row['public']),
            location=row['location'],
            background_color=row['background_color'],
            timer_colors=self.set_dict_int_keys(
                self.load_json_from_database_field(row['timer_colors'], {})
            ),
            timer_delays=self.set_dict_int_keys(
                self.load_json_from_database_field(row['timer_delays'], {})
            ),
            message_text=row['message_text'],
            message_color=row['message_color'],
            message_background_color=row['message_background_color'],
            prize_currency=row['prize_currency'],
            age_categories=self.load_json_from_database_field(row['age_categories']),
            age_category_base_date=self.load_optional_date_from_database_field(
                row['age_category_base_date']
            ),
            age_category_change_month=row['age_category_change_month'],
            organiser_name=row['organiser_name'],
            organiser_home_page=row['organiser_home_page'],
            organiser_email=row['organiser_email'],
            organiser_director=row['organiser_director'],
            allow_multi_tournament_players=self.load_bool_from_database_field(
                row['allow_multi_tournament_players']
            ),
            event_type=EventType(row['event_type']),
            tag_ids=self.load_json_from_database_field(row['tag_ids'], []),
            plugin_data=self.load_json_from_database_field(row['plugin_data'], {}),
            enabled_plugins=self.load_json_from_database_field(
                row['enabled_plugins'], []
            ),
        )

        return cast(T, stored_event)

    def load_stored_event(self) -> StoredEvent:
        self.execute('SELECT * FROM `info`')
        stored_event: StoredEvent = self._row_to_base_stored_event(
            self.fetchone(), StoredEvent
        )
        stored_event.stored_players = self.load_stored_players()
        stored_event.stored_tournaments = self.load_stored_tournaments()
        stored_event.stored_teams = self.load_stored_teams()
        stored_event.stored_team_groups = self.load_stored_team_groups()
        stored_event.stored_timers = list(self.load_stored_timers())
        stored_event.stored_families = list(self.load_stored_families())
        stored_event.stored_screens = list(self.load_stored_screens())
        stored_event.stored_rotators = self.load_stored_rotators()
        stored_event.stored_menus = self.load_stored_menus()
        stored_event.stored_display_controllers = list(
            self.load_stored_display_controllers()
        )
        stored_event.stored_accounts = self.load_stored_accounts()
        return stored_event

    def load_stored_event_metadata(self) -> EventMetadata:
        self.execute('SELECT * FROM `info`')
        metadata: EventMetadata = self._row_to_base_stored_event(
            self.fetchone(), EventMetadata
        )
        metadata.tournament_count = self._get_table_count('tournament')
        if metadata.tournament_count:
            self.execute(
                'SELECT MIN(start_date) AS start_date, '
                'MAX(stop_date) AS stop_date FROM `tournament`'
            )
            row = self.fetchone()
            metadata.start_date = self.load_date_from_database_field(row['start_date'])
            metadata.stop_date = self.load_date_from_database_field(row['stop_date'])
        metadata.player_count = self._get_table_count('player')
        metadata.team_count = self._get_table_count('team')
        metadata.timer_count = self._get_table_count('timer')
        metadata.screen_count = self._get_table_count('screen')
        metadata.family_count = self._get_table_count('family')
        metadata.rotator_count = self._get_table_count('rotator')
        return metadata

    def update_stored_event(
        self,
        stored_event: StoredEvent,
    ):
        """Updates the event database with the information in the provided `stored_event`."""
        fields = self._get_fields_dict(
            stored_event,
            [
                'name',
                'public',
                'federation',
                'location',
                'player_rating_type',
                'background_color',
                'message_text',
                'message_color',
                'message_background_color',
                'prize_currency',
                'age_category_change_month',
                'organiser_name',
                'organiser_home_page',
                'organiser_email',
                'organiser_director',
                'allow_multi_tournament_players',
            ],
        ) | {
            'event_type': stored_event.event_type.value,
            'age_category_base_date': self.dump_date_to_database_field(
                stored_event.age_category_base_date
            ),
            'age_categories': self.dump_to_json_database_field(
                stored_event.age_categories
            ),
            'timer_colors': self.dump_to_json_database_timer_colors(
                stored_event.timer_colors
            ),
            'timer_delays': self.dump_to_json_database_timer_delays(
                stored_event.timer_delays
            ),
            'plugin_data': self.dump_to_json_database_field(
                stored_event.plugin_data, {}
            ),
            'enabled_plugins': self.dump_to_json_database_field(
                stored_event.enabled_plugins, []
            ),
            'tag_ids': self.dump_to_json_database_field(stored_event.tag_ids, []),
        }

        field_sets = (f'`{f}` = ?' for f in fields.keys())
        self.execute(
            f'UPDATE `info` SET {", ".join(field_sets)}', tuple(fields.values())
        )

    def delete_all_tags(self):
        """Drops the tags of the event. Tag ids only mean something within
        the installation that defined them, so they are stripped whenever
        the event database leaves it (export) or enters it (import)."""
        self.execute("UPDATE `info` SET `tag_ids` = '[]'")

    # ---------------------------------------------------------------------------------
    # StoredTimerHour
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_timer_hour(cls, row: dict[str, Any]) -> StoredTimerHour:
        return StoredTimerHour(
            id=row['id'],
            uniq_id=row['uniq_id'],
            timer_id=row['timer_id'],
            triggered_at=cls.load_datetime_from_database_field(row['triggered_at']),
            text_before=row['text_before'],
            text_after=row['text_after'],
        )

    def get_stored_timer_hour(self, timer_hour_id: int) -> StoredTimerHour | None:
        self.execute(
            'SELECT * FROM `timer_hour` WHERE `id` = ?',
            (timer_hour_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_timer_hour(row)
        return None

    def load_stored_timer_hours(self, timer_id: int) -> Iterator[StoredTimerHour]:
        self.execute(
            'SELECT * FROM `timer_hour` WHERE `timer_id` = ? ORDER BY `triggered_at`',
            (timer_id,),
        )
        yield from map(self._row_to_stored_timer_hour, self.fetchall())

    def _get_stored_timer_hour_fields(
        self, stored_timer_hour: StoredTimerHour
    ) -> dict[str, Any]:
        return self._get_fields_dict(
            stored_timer_hour,
            [
                'timer_id',
                'uniq_id',
                'triggered_at',
                'text_before',
                'text_after',
            ],
        ) | {
            'triggered_at': self.dump_datetime_to_database_field(
                stored_timer_hour.triggered_at
            ),
        }

    def update_stored_timer_hour(self, stored_timer_hour: StoredTimerHour):
        fields = self._get_stored_timer_hour_fields(stored_timer_hour)
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_timer_hour.id is not None
        self.execute(
            f'UPDATE `timer_hour` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_timer_hour.id,),
        )

    def add_stored_timer_hour(self, stored_timer_hour: StoredTimerHour) -> int:
        fields = self._get_stored_timer_hour_fields(stored_timer_hour)
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `timer_hour`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        id_ = self._last_inserted_id()
        if id_ is None:
            raise RuntimeError('Timer hour insertion failed')
        return id_

    def delete_stored_timer_hour(self, timer_hour_id: int):
        self.execute('DELETE FROM `timer_hour` WHERE `id` = ?', (timer_hour_id,))

    # ---------------------------------------------------------------------------------
    # StoredTimer
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_timer(cls, row: dict[str, Any]) -> StoredTimer:
        return StoredTimer(
            id=row['id'],
            name=row['name'],
            colors=cls.set_dict_int_keys(
                cls.load_json_from_database_field(row['colors'])
            ),
            delays=cls.set_dict_int_keys(
                cls.load_json_from_database_field(row['delays'])
            ),
        )

    def get_stored_timer(self, timer_id: int) -> StoredTimer:
        self.execute(
            'SELECT * FROM `timer` WHERE `id` = ?',
            (timer_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_timer(row)
        raise RuntimeError('Unable to fetch timer to load')

    def get_stored_timer_ids(self) -> Iterator[int]:
        self.execute('SELECT `id` FROM `timer` ORDER BY `name`')
        for row in self.fetchall():
            yield row['id']

    def load_stored_timers(self) -> Iterator[StoredTimer]:
        for stored_timer_id in self.get_stored_timer_ids():
            stored_timer: StoredTimer = self.get_stored_timer(stored_timer_id)
            assert stored_timer.id is not None
            stored_timer.stored_timer_hours = list(
                self.load_stored_timer_hours(stored_timer.id)
            )
            yield stored_timer

    def add_stored_timer(self, stored_timer: StoredTimer) -> int:
        fields = {
            'name': stored_timer.name,
            'colors': self.dump_to_json_database_timer_colors(stored_timer.colors),
            'delays': self.dump_to_json_database_timer_delays(stored_timer.delays),
        }
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `timer`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        timer_id = self._last_inserted_id()
        if timer_id is None:
            raise RuntimeError('Timer insertion failed')
        return timer_id

    def update_stored_timer(self, stored_timer: StoredTimer):
        fields = {
            'name': stored_timer.name,
            'colors': self.dump_to_json_database_timer_colors(stored_timer.colors),
            'delays': self.dump_to_json_database_timer_delays(stored_timer.delays),
        }
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_timer.id is not None
        self.execute(
            f'UPDATE `timer` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_timer.id,),
        )

    def delete_stored_timer(self, timer_id: int):
        self.execute('DELETE FROM `timer` WHERE id = ?;', (timer_id,))

    # ---------------------------------------------------------------------------------
    # StoredTournament
    # ---------------------------------------------------------------------------------

    @classmethod
    def _load_round_datetimes_from_database_field(
        cls, value: str | None
    ) -> dict[int, datetime | None]:
        """Load round_datetimes from a JSON database field."""
        raw: dict[str, str | None] = cls.load_json_from_database_field(value, {})
        result: dict[int, datetime | None] = {}
        for k, v in raw.items():
            result[int(k)] = datetime.fromisoformat(v) if v else None
        return result

    @classmethod
    def _dump_round_datetimes_to_database_field(
        cls, round_datetimes: dict[int, datetime | None]
    ) -> str | None:
        """Serialize round_datetimes to a JSON string for storage."""
        if not round_datetimes:
            return None
        raw: dict[str, str | None] = {
            str(k): v.isoformat() if v is not None else None
            for k, v in round_datetimes.items()
        }
        return cls.dump_to_json_database_field(raw)

    @classmethod
    def _row_to_stored_tournament(cls, row: dict[str, Any]) -> StoredTournament:
        stored_tournament = StoredTournament(
            id=row['id'],
            name=row['name'],
            index=row['index'],
            time_control_trf25=row['time_control_trf25'],
            record_illegal_moves=row['record_illegal_moves'],
            first_board_number=row['first_board_number'],
            paired_bye_result=row['paired_bye_result'],
            max_byes=row['max_byes'],
            last_rounds_no_byes=row['last_rounds_no_byes'],
            pairing=row['pairing'],
            pairing_settings=cls.load_json_from_database_field(
                row['pairing_settings'], {}
            ),
            current_round=row['current_round'],
            check_in_open=cls.load_bool_from_database_field(row['check_in_open']),
            rounds=row['rounds'],
            rating=row['rating'],
            last_update=cls.load_datetime_from_database_field(row['last_update']),
            last_player_update=cls.load_optional_timestamp_from_database_field(
                row['last_player_update']
            ),
            last_pairing_update=cls.load_optional_timestamp_from_database_field(
                row['last_pairing_update']
            ),
            start_date=cls.load_date_from_database_field(row['start_date']),
            stop_date=cls.load_date_from_database_field(row['stop_date']),
            location=row['location'],
            player_rating_type=row['player_rating_type'],
            override_unrated_rapid_blitz=cls.load_bool_from_database_field(
                row['override_unrated_rapid_blitz']
            ),
            game_points=cls._load_int_keyed_float_dict_from_db(row['game_points']),
            plugin_data=cls.load_json_from_database_field(row['plugin_data'], {}),
            round_datetimes=cls._load_round_datetimes_from_database_field(
                row['round_datetimes']
            ),
            criteria=cls.load_json_from_database_field(row['criteria'], {}),
            team_player_count=row['team_player_count'],
            roster_max_size=row['roster_max_size'],
            match_points=cls._load_int_keyed_float_dict_from_db(row['match_points']),
            color_pattern=row['color_pattern'],
            primary_score=row['primary_score'],
            secondary_score_for_colours=cls.load_bool_from_database_field(
                row['secondary_score_for_colours']
            ),
            team_colour_type=row['team_colour_type'],
            enforce_roster_order=cls.load_bool_from_database_field(
                row['enforce_roster_order']
            ),
            team_sort_mode=row['team_sort_mode'],
            rule_set=row['rule_set'],
            rule_set_config=cls.load_json_from_database_field(
                row['rule_set_config'], {}
            ),
            prohibited_pairing_dimension=row['prohibited_pairing_dimension'],
            prohibited_pairing_dimension_is_hard=cls.load_bool_from_database_field(
                row['prohibited_pairing_dimension_is_hard']
            ),
            round_robin_participation_rule=cls.load_bool_from_database_field(
                row['round_robin_participation_rule']
            ),
        )

        return stored_tournament

    @staticmethod
    def _load_int_keyed_float_dict_from_db(
        value: str | None,
    ) -> dict[int, float] | None:
        if value is None:
            return None
        raw = EventDatabase.load_json_from_database_field(value)
        if raw is None:
            return None
        return {int(k): float(v) for k, v in raw.items()}

    def get_stored_tournament(self, tournament_id: int) -> StoredTournament | None:
        self.execute(
            'SELECT * FROM `tournament` WHERE `id` = ?',
            (tournament_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_tournament(row)
        return None

    def load_stored_tournaments(self) -> list[StoredTournament]:
        self.execute('SELECT * FROM `tournament` ORDER BY `name`')
        stored_tournaments: list[StoredTournament] = []
        for row in self.fetchall():
            stored_tournament = self._row_to_stored_tournament(row)
            id_ = stored_tournament.id
            assert id_ is not None
            stored_tournament.stored_tie_breaks = (
                self.load_tournament_stored_tie_breaks(id_)
            )
            stored_tournament.stored_prize_groups = (
                self.load_tournament_stored_prize_groups(id_)
            )
            stored_tournament.stored_tournament_players = (
                self.load_stored_tournament_players(id_)
            )
            stored_tournament.stored_boards_by_round = (
                self.load_tournament_stored_boards_by_round(id_)
            )
            stored_tournament.stored_team_boards_by_round = (
                self.load_tournament_stored_team_boards_by_round(id_)
            )
            stored_tournament.stored_team_pairing_blocks = (
                self.load_tournament_stored_team_pairing_blocks(id_)
            )
            stored_tournament.stored_team_point_adjustments = (
                self.load_tournament_stored_team_point_adjustments(id_)
            )
            stored_tournament.stored_player_point_adjustments = (
                self.load_tournament_stored_player_point_adjustments(id_)
            )
            stored_tournament.stored_prohibited_pairing_groups = (
                self.load_tournament_stored_prohibited_pairing_groups(id_)
            )
            stored_tournaments.append(stored_tournament)
        return stored_tournaments

    @classmethod
    def _get_tournament_fields_dict(
        cls, stored_tournament: StoredTournament
    ) -> dict[str, Any]:
        return cls._get_fields_dict(
            stored_tournament,
            [
                'name',
                'index',
                'time_control_trf25',
                'record_illegal_moves',
                'first_board_number',
                'paired_bye_result',
                'max_byes',
                'rounds',
                'rating',
                'pairing',
                'location',
                'player_rating_type',
                'last_rounds_no_byes',
                'override_unrated_rapid_blitz',
                'team_player_count',
                'roster_max_size',
                'color_pattern',
                'primary_score',
                'secondary_score_for_colours',
                'team_colour_type',
                'enforce_roster_order',
                'team_sort_mode',
                'rule_set',
                'prohibited_pairing_dimension',
                'prohibited_pairing_dimension_is_hard',
                'round_robin_participation_rule',
            ],
        ) | {
            'start_date': cls.dump_date_to_database_field(stored_tournament.start_date),
            'stop_date': cls.dump_date_to_database_field(stored_tournament.stop_date),
            'last_update': cls.now_as_database_timestamp(),
            'plugin_data': cls.dump_to_json_database_field(
                stored_tournament.plugin_data, {}
            ),
            'round_datetimes': cls._dump_round_datetimes_to_database_field(
                stored_tournament.round_datetimes
            ),
            'criteria': cls.dump_to_json_database_field(stored_tournament.criteria),
            'rule_set_config': cls.dump_to_json_database_field(
                stored_tournament.rule_set_config, {}
            ),
            'game_points': cls.dump_to_json_database_field(
                stored_tournament.game_points
            ),
            'match_points': cls.dump_to_json_database_field(
                stored_tournament.match_points
            ),
        }

    def add_stored_tournament(self, stored_tournament: StoredTournament) -> int:
        fields = self._get_tournament_fields_dict(stored_tournament)
        fields |= {'check_in_open': True}
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `tournament`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        tournament_id: int | None = self._last_inserted_id()
        if tournament_id is None:
            raise RuntimeError('Tournament insertion failed')
        from data.tie_breaks.tie_breaks import PointsTieBreak

        self.add_stored_tie_break(
            StoredTieBreak(
                id=None,
                tournament_id=tournament_id,
                type=PointsTieBreak.static_id(),
                options={},
                index=0,
            )
        )
        return tournament_id

    def update_stored_tournament(self, stored_tournament: StoredTournament):
        fields = self._get_tournament_fields_dict(stored_tournament)
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_tournament.id is not None
        self.execute(
            f'UPDATE `tournament` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_tournament.id,),
        )

    def _delete_exclusive_players(self, tournament_id: int):
        """Delete the players a tournament holds that no other tournament
        holds too. Players belong to the event, so one entered in several
        tournaments has to survive losing this one.

        A player is held either by a `tournament_player` row or by
        belonging to one of the tournament's teams. Team tournaments
        store no `tournament_player` rows at all — the loader synthesises
        them from team membership — so for a team roster only the second
        branch finds anything.
        """
        self.execute(
            'DELETE FROM `player` WHERE `id` IN ('
            '   SELECT `player_id` FROM `tournament_player` WHERE `tournament_id` = ? '
            '   UNION '
            '   SELECT `player`.`id` FROM `player` '
            '   JOIN `team` ON `team`.`id` = `player`.`team_id` '
            '   WHERE `team`.`tournament_id` = ?'
            ') AND `id` NOT IN ('
            '   SELECT `player_id` FROM `tournament_player` WHERE `tournament_id` <> ?'
            ') AND `id` NOT IN ('
            '   SELECT `player`.`id` FROM `player` '
            '   JOIN `team` ON `team`.`id` = `player`.`team_id` '
            '   WHERE `team`.`tournament_id` IS NOT NULL '
            '   AND `team`.`tournament_id` <> ?'
            ')',
            (tournament_id, tournament_id, tournament_id, tournament_id),
        )

    def delete_stored_tournament(self, tournament_id: int):
        # Teams cascade with the tournament (see the `team` foreign key).
        # The players have to be found first, while the rows tying them
        # to the tournament still exist.
        self._delete_exclusive_players(tournament_id)
        self.execute('DELETE FROM `tournament` WHERE `id` = ?;', (tournament_id,))

    def set_tournament_check_in_open(self, tournament_id: int, check_in_open: bool):
        self.execute(
            'UPDATE `tournament` SET `check_in_open` = ? WHERE `id` = ?',
            (check_in_open, tournament_id),
        )

    def set_tournament_pairing_settings(
        self, tournament_id: int, pairing_settings: dict[str, Any]
    ):
        self.execute(
            'UPDATE `tournament` SET '
            '`pairing_settings` = ?, `last_update` = ? '
            'WHERE `id` = ?',
            (
                self.dump_to_json_database_field(pairing_settings),
                self.now_as_database_timestamp(),
                tournament_id,
            ),
        )

    def set_tournament_current_round(
        self, tournament_id: int, current_round: int | None
    ):
        self.execute(
            'UPDATE `tournament` SET '
            '`current_round` = ?, `last_update` = ? '
            'WHERE `id` = ?',
            (
                current_round,
                self.now_as_database_timestamp(),
                tournament_id,
            ),
        )

    # ---------------------------------------------------------------------------------
    # StoredTieBreak
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_tie_break(cls, row: dict[str, Any]) -> StoredTieBreak:
        return StoredTieBreak(
            id=row['id'],
            tournament_id=row['tournament_id'],
            type=row['type'],
            options=cls.load_json_from_database_field(row['options']),
            index=row['index'],
        )

    def load_tournament_stored_tie_breaks(
        self, tournament_id: int
    ) -> list[StoredTieBreak]:
        self.execute(
            'SELECT * FROM `tie_break` WHERE `tournament_id` = ? ORDER BY `index`',
            (tournament_id,),
        )
        return [self._row_to_stored_tie_break(row) for row in self.fetchall()]

    def add_stored_tie_break(
        self,
        stored_tie_break: StoredTieBreak,
    ) -> int:
        fields = self._get_fields_dict(
            stored_tie_break, ['tournament_id', 'type', 'index']
        ) | {'options': self.dump_to_json_database_field(stored_tie_break.options)}
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `tie_break`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (tie_break_id := self._last_inserted_id()):
            raise RuntimeError('Tie break insertion failed')
        return tie_break_id

    def update_stored_tie_break(
        self,
        stored_tie_break: StoredTieBreak,
    ):
        fields = self._get_fields_dict(
            stored_tie_break, ['tournament_id', 'type', 'index']
        ) | {'options': self.dump_to_json_database_field(stored_tie_break.options)}
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_tie_break.id is not None
        self.execute(
            f'UPDATE `tie_break` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_tie_break.id,),
        )

    def delete_stored_tie_break(self, tie_break_id: int):
        self.execute(
            'DELETE FROM `tie_break` WHERE `id` = ?;',
            (tie_break_id,),
        )

    def delete_all_tournament_stored_tie_breaks(self, tournament_id: int):
        self.execute(
            'DELETE FROM `tie_break` WHERE `tournament_id` = ?;',
            (tournament_id,),
        )

    # ---------------------------------------------------------------------------------
    # StoredPlayer
    # ---------------------------------------------------------------------------------

    def load_stored_players(self) -> list[StoredPlayer]:
        self.execute(
            'SELECT `id`, `last_name`, `ratings`, `first_name`, '
            '`date_of_birth`, `year_of_birth`, `gender`, `mail`, `phone`, '
            '`comment`, `owed`, `paid`, `title`, `women_title`, `fide_id`, '
            '`federation`, `club`, `fixed`, `check_in`, `team_id`, '
            '`team_index`, `plugin_data` FROM `player`'
        )
        assert self.cursor is not None
        stored_players: list[StoredPlayer] = []
        for (
            player_id,
            last_name,
            ratings,
            first_name,
            date_of_birth,
            year_of_birth,
            gender,
            mail,
            phone,
            comment,
            owed,
            paid,
            title,
            women_title,
            fide_id,
            federation,
            club,
            fixed,
            check_in,
            team_id,
            team_index,
            plugin_data,
        ) in self.cursor.fetchall():
            stored_players.append(
                StoredPlayer(
                    id=player_id,
                    last_name=last_name,
                    ratings=self.set_dict_int_keys(
                        self.load_json_from_database_field(ratings)
                    ),
                    first_name=first_name,
                    date_of_birth=self.load_optional_date_from_database_field(
                        date_of_birth
                    ),
                    year_of_birth=year_of_birth,
                    gender=gender,
                    mail=mail,
                    phone=phone,
                    comment=comment,
                    owed=owed,
                    paid=paid,
                    title=title,
                    women_title=women_title,
                    fide_id=fide_id,
                    federation=federation,
                    club=club,
                    fixed=fixed,
                    check_in=self.load_bool_from_database_field(check_in),
                    team_id=team_id,
                    team_index=team_index,
                    plugin_data=self.load_json_from_database_field(plugin_data, {}),
                )
            )
        return stored_players

    @classmethod
    def _get_player_fields_dict(cls, stored_player: StoredPlayer) -> dict[str, Any]:
        return cls._get_fields_dict(
            stored_player,
            [
                'first_name',
                'last_name',
                'gender',
                'mail',
                'phone',
                'comment',
                'owed',
                'paid',
                'title',
                'women_title',
                'fide_id',
                'federation',
                'club',
                'fixed',
                'check_in',
                'year_of_birth',
                'team_id',
                'team_index',
            ],
        ) | {
            'date_of_birth': cls.dump_date_to_database_field(
                stored_player.date_of_birth
            ),
            'ratings': cls.dump_to_json_database_field(stored_player.ratings),
            'plugin_data': cls.dump_to_json_database_field(stored_player.plugin_data),
        }

    def add_stored_player(
        self,
        stored_player: StoredPlayer,
    ) -> int:
        fields = self._get_player_fields_dict(stored_player)
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `player`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (player_id := self._last_inserted_id()):
            raise RuntimeError('Player insertion failed')
        return player_id

    def update_stored_player(self, stored_player: StoredPlayer):
        fields = self._get_player_fields_dict(stored_player)
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_player.id is not None
        self.execute(
            f'UPDATE `player` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_player.id,),
        )

    def delete_stored_player(self, player_id: int):
        self.execute('DELETE FROM `player` WHERE `id` = ?;', (player_id,))

    def set_player_check_in(self, player_id: int, check_in: bool):
        self.execute(
            'UPDATE `player` SET `check_in` = ? WHERE `id` = ?',
            (check_in, player_id),
        )

    def set_players_check_in(self, player_ids: list[int], check_in: bool):
        list_set = ', '.join(['?'] * len(player_ids))
        self.execute(
            f'UPDATE `player` SET `check_in` = ? WHERE `id` IN ({list_set})',
            (check_in,) + tuple(player_ids),
        )

    def delete_players_personal_data(self):
        """Delete all personal data (email and phone number) from the database."""
        self.execute(
            'UPDATE `player` SET `phone` = ?, `mail`= ?',
            (
                '',
                '',
            ),
        )

    def delete_all_stored_players(self):
        self.execute('DELETE FROM `player`')

    # ---------------------------------------------------------------------------------
    # StoredTournamentPlayer
    # ---------------------------------------------------------------------------------

    def load_stored_tournament_players(
        self, tournament_id: int
    ) -> list[StoredTournamentPlayer]:
        self.execute(
            (
                'SELECT `tournament_id`, `player_id`, `pairing_number`, '
                '`manual_tiebreak` FROM `tournament_player` '
                'WHERE `tournament_id` = ?'
            ),
            (tournament_id,),
        )
        assert self.cursor is not None
        tournament_player_rows = self.cursor.fetchall()
        pairings_by_player = self.load_tournament_stored_pairings_by_player(
            tournament_id
        )
        stored_tournament_players: list[StoredTournamentPlayer] = []
        seen_player_ids: set[int] = set()
        for (
            stored_tournament_id,
            player_id,
            pairing_number,
            manual_tiebreak,
        ) in tournament_player_rows:
            stored_tournament_player = StoredTournamentPlayer(
                tournament_id=stored_tournament_id,
                player_id=player_id,
                pairing_number=pairing_number,
                manual_tiebreak=manual_tiebreak,
                stored_pairings=pairings_by_player.get(player_id, []),
            )

            assert stored_tournament_player.player_id is not None
            seen_player_ids.add(stored_tournament_player.player_id)
            stored_tournament_players.append(stored_tournament_player)

        # In team events, players linked to a team assigned to this tournament
        # do not get a tournament_player row; synthesize one in-memory so the
        # rest of the codebase sees them.
        self.execute(
            'SELECT `player`.`id` FROM `player` '
            'JOIN `team` ON `player`.`team_id` = `team`.`id` '
            'WHERE `team`.`tournament_id` = ?',
            (tournament_id,),
        )
        assert self.cursor is not None
        for (player_id,) in self.cursor.fetchall():
            if player_id in seen_player_ids:
                continue
            synthetic = StoredTournamentPlayer(
                tournament_id=tournament_id,
                player_id=player_id,
                pairing_number=None,
                manual_tiebreak=None,
                stored_pairings=pairings_by_player.get(player_id, []),
            )
            seen_player_ids.add(player_id)
            stored_tournament_players.append(synthetic)
        return stored_tournament_players

    def add_stored_tournament_player(
        self,
        stored_tournament_player: StoredTournamentPlayer,
        persist_player_row: bool = True,
    ):
        """Persist a tournament player's pairings, and (unless
        *persist_player_row* is False) its ``tournament_player`` row.

        Team tournaments don't store ``tournament_player`` rows for
        rostered players — they're synthesised in-memory from team
        membership at load time — so team imports pass
        ``persist_player_row=False`` to keep only the pairings (the
        ``pairing`` table has no foreign key to ``tournament_player``)."""
        if persist_player_row:
            fields = self._get_fields_dict(
                stored_tournament_player,
                ['tournament_id', 'player_id', 'pairing_number', 'manual_tiebreak'],
            )
            fields_str = ', '.join(f'`{f}`' for f in fields)
            values_str = ', '.join(['?'] * len(fields))
            self.execute(
                f'INSERT INTO `tournament_player`({fields_str}) VALUES ({values_str})',
                tuple(fields.values()),
            )
        for stored_pairing in stored_tournament_player.stored_pairings:
            self.add_stored_pairing(stored_pairing)

    def set_tournament_player_pairing_number(
        self, stored_tournament_player: StoredTournamentPlayer
    ):
        self.execute(
            (
                'UPDATE `tournament_player` SET `pairing_number` = ? '
                'WHERE `tournament_id` = ? AND `player_id` = ?'
            ),
            (
                stored_tournament_player.pairing_number,
                stored_tournament_player.tournament_id,
                stored_tournament_player.player_id,
            ),
        )

    def set_tournament_players_manual_tiebreak(
        self,
        tournament_id: int,
        updates: dict[int, int | None],
    ) -> int:
        """
        Bulk-update manual_tiebreak for many players in a tournament.
        updates: { player_id: int | None }  (None -> set NULL)
        Returns total rows updated.
        """
        if not updates:
            return 0

        params = [(mtb, tournament_id, pid) for pid, mtb in updates.items()]
        sql = (
            'UPDATE `tournament_player` '
            'SET `manual_tiebreak` = ? '
            'WHERE `tournament_id` = ? AND `player_id` = ?'
        )

        return self.executemany(sql, params)

    def delete_stored_tournament_player(self, tournament_id: int, player_id: int):
        self.execute(
            (
                'DELETE FROM `tournament_player` '
                'WHERE `tournament_id` = ? AND `player_id` = ?'
            ),
            (tournament_id, player_id),
        )
        self.execute(
            'DELETE FROM `pairing` WHERE `tournament_id` = ? AND `player_id` = ?',
            (tournament_id, player_id),
        )

    def delete_players_in_tournament(self, tournament_id: int):
        """Empty a tournament of its players, keeping its teams — what
        importing "and delete the existing players" asks for.

        Dropping the `tournament_player` rows alone wouldn't do it: it
        leaves the player records in the event, and a team tournament has
        no such rows to drop in the first place. So the players it alone
        holds are deleted outright, and any it shares with another
        tournament merely lose their place in this one.
        """
        self._delete_exclusive_players(tournament_id)
        self.execute(
            'DELETE FROM `tournament_player` WHERE `tournament_id` = ?',
            (tournament_id,),
        )

    # ---------------------------------------------------------------------------------
    # StoredPairings
    # ---------------------------------------------------------------------------------

    def load_tournament_stored_pairings_by_player(
        self, tournament_id: int
    ) -> dict[int, list[StoredPairing]]:
        """Load and group every pairing of a tournament."""
        self.execute(
            (
                'SELECT `tournament_id`, `player_id`, `round`, `result`, '
                '`board_id`, `illegal_moves`, `effective_points` FROM `pairing` '
                'WHERE `tournament_id` = ? '
                'ORDER BY `player_id`, `round`'
            ),
            (tournament_id,),
        )
        pairings_by_player: dict[int, list[StoredPairing]] = {}
        assert self.cursor is not None
        for (
            stored_tournament_id,
            player_id,
            round_,
            result,
            board_id,
            illegal_moves,
            effective_points,
        ) in self.cursor.fetchall():
            stored_pairing = StoredPairing(
                tournament_id=stored_tournament_id,
                player_id=player_id,
                round_=round_,
                result=result,
                board_id=board_id,
                illegal_moves=illegal_moves,
                effective_points=effective_points,
            )
            pairings_by_player.setdefault(stored_pairing.player_id, []).append(
                stored_pairing
            )
        return pairings_by_player

    def add_stored_pairing(
        self,
        stored_pairing: StoredPairing,
    ):
        fields = self._get_fields_dict(
            stored_pairing,
            [
                'tournament_id',
                'player_id',
                'result',
                'board_id',
                'illegal_moves',
                'effective_points',
            ],
        ) | {'round': stored_pairing.round_}
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `pairing`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )

    def update_stored_pairing(self, stored_pairing: StoredPairing):
        fields = self._get_fields_dict(
            stored_pairing,
            ['result', 'board_id', 'illegal_moves', 'effective_points'],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        self.execute(
            (
                f'UPDATE `pairing` SET {field_sets} '
                'WHERE `tournament_id` = ? AND `player_id` = ? AND `round` = ?'
            ),
            tuple(fields.values())
            + (
                stored_pairing.tournament_id,
                stored_pairing.player_id,
                stored_pairing.round_,
            ),
        )

    def delete_stored_pairing(self, stored_pairing: StoredPairing):
        self.execute(
            (
                'DELETE FROM `pairing` '
                'WHERE `tournament_id` = ? AND `player_id` = ? AND `round` = ?'
            ),
            (
                stored_pairing.tournament_id,
                stored_pairing.player_id,
                stored_pairing.round_,
            ),
        )

    def delete_stored_pairings_after_round(self, tournament_id: int, round_: int):
        self.execute(
            'DELETE FROM `pairing` WHERE `tournament_id` = ? and `round` > ?',
            (tournament_id, round_),
        )

    def delete_all_stored_pairings(self):
        self.execute('DELETE FROM `pairing`')

    # ---------------------------------------------------------------------------------
    # StoredBoard
    # ---------------------------------------------------------------------------------

    def load_tournament_stored_boards_by_round(
        self, tournament_id: int
    ) -> dict[int, list[StoredBoard]]:
        # Start from pairing's tournament index; the UNION adds unpaired team boards.
        self.execute(
            (
                'SELECT `board`.`id`, `board`.`white_player_id`, '
                '`board`.`black_player_id`, `board`.`index`, '
                '`board`.`last_result_update`, `board`.`team_board_id`, '
                '`board`.`fixed_number`, `paired_board`.`round` '
                'FROM ('
                '  SELECT `board_id`, MIN(`round`) AS `round` '
                '  FROM `pairing` '
                '  WHERE `tournament_id` = ? AND `board_id` IS NOT NULL '
                '  GROUP BY `board_id`'
                ') AS `paired_board` '
                'JOIN `board` ON `board`.`id` = `paired_board`.`board_id` '
                'UNION ALL '
                'SELECT `board`.`id`, `board`.`white_player_id`, '
                '`board`.`black_player_id`, `board`.`index`, '
                '`board`.`last_result_update`, `board`.`team_board_id`, '
                '`board`.`fixed_number`, `team_board`.`round` '
                'FROM `team_board` '
                'JOIN `board` ON `board`.`team_board_id` = `team_board`.`id` '
                'WHERE `team_board`.`tournament_id` = ? '
                'AND NOT EXISTS ('
                '  SELECT 1 FROM `pairing` '
                '  WHERE `pairing`.`tournament_id` = ? '
                '  AND `pairing`.`board_id` = `board`.`id`'
                ') '
                'ORDER BY `round`, `index`'
            ),
            (tournament_id, tournament_id, tournament_id),
        )
        stored_boards_by_round: dict[int, list[StoredBoard]] = {}
        assert self.cursor is not None
        for (
            board_id,
            white_player_id,
            black_player_id,
            index,
            last_result_update,
            team_board_id,
            fixed_number,
            round_,
        ) in self.cursor.fetchall():
            board = StoredBoard(
                id=board_id,
                white_player_id=white_player_id,
                black_player_id=black_player_id,
                index=index,
                last_result_update=self.load_optional_timestamp_from_database_field(
                    last_result_update
                ),
                team_board_id=team_board_id,
                fixed_number=fixed_number,
            )
            if round_ in stored_boards_by_round:
                stored_boards_by_round[round_].append(board)
            else:
                stored_boards_by_round[round_] = [board]
        return stored_boards_by_round

    def add_stored_board(self, stored_board: StoredBoard) -> int:
        fields = self._get_fields_dict(
            stored_board,
            [
                'white_player_id',
                'black_player_id',
                'index',
                'team_board_id',
                'fixed_number',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `board`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (board_id := self._last_inserted_id()):
            raise RuntimeError('Board insertion failed')
        return board_id

    def update_stored_board(self, stored_board: StoredBoard):
        fields = self._get_fields_dict(
            stored_board,
            [
                'white_player_id',
                'black_player_id',
                'index',
                'team_board_id',
                'fixed_number',
            ],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_board.id is not None
        self.execute(
            f'UPDATE `board` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_board.id,),
        )

    def delete_stored_board(self, board_id: int):
        self.execute('DELETE FROM `board` WHERE `id` = ?;', (board_id,))

    def update_board_last_result_update(
        self, board_id: int, clear: bool = False
    ) -> datetime | None:
        """Updates board timestamp"""

        if clear:
            self.execute(
                'UPDATE `board` SET `last_result_update` = NULL WHERE `id` = ?',
                (board_id,),
            )
            return None
        else:
            now = datetime.now()
            self.execute(
                'UPDATE `board` SET `last_result_update` = ? WHERE `id` = ?',
                (self.dump_optional_datetime_to_timestamp_field(now), board_id),
            )
            return now

    # ---------------------------------------------------------------------------------
    # StoredTeam
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_team(cls, row: dict[str, Any]) -> StoredTeam:
        return StoredTeam(
            id=row['id'],
            name=row['name'],
            tournament_id=row['tournament_id'],
            pairing_number=row['pairing_number'],
            captain_id=row['captain_id'],
            captain_name=row['captain_name'],
            group_id=row['group_id'],
            federation=row['federation'],
            check_in=cls.load_bool_from_database_field(row['check_in']),
        )

    def load_stored_teams(self) -> list[StoredTeam]:
        self.execute('SELECT * FROM `team` ORDER BY `name`')
        teams: list[StoredTeam] = [
            self._row_to_stored_team(row) for row in self.fetchall()
        ]
        teams_by_id: dict[int, StoredTeam] = {
            team.id: team for team in teams if team.id is not None
        }
        if teams_by_id:
            placeholders = ', '.join('?' for _ in teams_by_id)
            self.execute(
                'SELECT * FROM `team_round_lineup` '
                f'WHERE `team_id` IN ({placeholders}) '
                'ORDER BY `team_id`, `round`, `index`',
                tuple(teams_by_id.keys()),
            )
            for row in self.fetchall():
                entry = StoredTeamRoundLineupEntry(
                    team_id=row['team_id'],
                    round_=row['round'],
                    player_id=row['player_id'],
                    index=row['index'],
                )
                team = teams_by_id[entry.team_id]
                team.stored_round_lineups.setdefault(entry.round_, []).append(entry)
        return teams

    def add_stored_team(self, stored_team: StoredTeam) -> int:
        fields = self._get_fields_dict(
            stored_team,
            [
                'tournament_id',
                'name',
                'pairing_number',
                'captain_id',
                'captain_name',
                'group_id',
                'federation',
                'check_in',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `team`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (team_id := self._last_inserted_id()):
            raise RuntimeError('Team insertion failed')
        return team_id

    def update_stored_team(self, stored_team: StoredTeam):
        fields = self._get_fields_dict(
            stored_team,
            [
                'tournament_id',
                'name',
                'pairing_number',
                'captain_id',
                'captain_name',
                'group_id',
                'federation',
                'check_in',
            ],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_team.id is not None
        self.execute(
            f'UPDATE `team` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_team.id,),
        )

    def set_team_captain(
        self, team_id: int, captain_id: int | None, captain_name: str | None
    ):
        self.execute(
            'UPDATE `team` SET `captain_id` = ?, `captain_name` = ? WHERE `id` = ?',
            (captain_id, captain_name, team_id),
        )

    def set_team_check_in(self, team_id: int, check_in: bool):
        self.execute(
            'UPDATE `team` SET `check_in` = ? WHERE `id` = ?',
            (check_in, team_id),
        )

    def set_team_check_in_for_tournament(self, tournament_id: int, check_in: bool):
        self.execute(
            'UPDATE `team` SET `check_in` = ? WHERE `tournament_id` = ?',
            (check_in, tournament_id),
        )

    def delete_stored_team(self, team_id: int):
        self.execute('DELETE FROM `team` WHERE `id` = ?', (team_id,))

    def set_team_tournament(self, team_id: int, tournament_id: int | None):
        self.execute(
            'UPDATE `team` SET `tournament_id` = ? WHERE `id` = ?',
            (tournament_id, team_id),
        )

    def set_team_pairing_number(self, team_id: int, pairing_number: int | None):
        self.execute(
            'UPDATE `team` SET `pairing_number` = ? WHERE `id` = ?',
            (pairing_number, team_id),
        )

    def set_team_group(self, team_id: int, group_id: int | None):
        self.execute(
            'UPDATE `team` SET `group_id` = ? WHERE `id` = ?',
            (group_id, team_id),
        )

    @staticmethod
    def _row_to_stored_team_group(row: dict[str, Any]) -> StoredTeamGroup:
        return StoredTeamGroup(id=row['id'], name=row['name'])

    def load_stored_team_groups(self) -> list[StoredTeamGroup]:
        self.execute('SELECT * FROM `team_group` ORDER BY `name`')
        return [self._row_to_stored_team_group(row) for row in self.fetchall()]

    def add_stored_team_group(self, name: str) -> int:
        self.execute('INSERT INTO `team_group`(`name`) VALUES (?)', (name,))
        if not (group_id := self._last_inserted_id()):
            raise RuntimeError('Team group insertion failed')
        return group_id

    def update_stored_team_group(self, group_id: int, name: str):
        self.execute(
            'UPDATE `team_group` SET `name` = ? WHERE `id` = ?',
            (name, group_id),
        )

    def delete_stored_team_group(self, group_id: int):
        # Detach the group from any team first, so deletion is correct
        # even on databases whose ``team.group_id`` FK isn't enforced
        # (e.g. manually-migrated files without the ON DELETE SET NULL).
        self.execute(
            'UPDATE `team` SET `group_id` = NULL WHERE `group_id` = ?',
            (group_id,),
        )
        self.execute('DELETE FROM `team_group` WHERE `id` = ?', (group_id,))

    def set_player_team(
        self, player_id: int, team_id: int | None, team_index: int | None
    ):
        """Set a player's team membership and within-team order index."""
        self.execute(
            'UPDATE `player` SET `team_id` = ?, `team_index` = ? WHERE `id` = ?',
            (team_id, team_index, player_id),
        )

    def reorder_team_players(self, team_id: int, ordered_player_ids: list[int]):
        """Renumber team_index for the given team's players in supplied order."""
        rows = [
            (team_id, index, player_id)
            for index, player_id in enumerate(ordered_player_ids)
        ]
        self.executemany(
            'UPDATE `player` SET `team_id` = ?, `team_index` = ? WHERE `id` = ?',
            rows,
        )

    # ---------------------------------------------------------------------------------
    # StoredTeamRoundLineupEntry
    # ---------------------------------------------------------------------------------

    def replace_team_round_lineup(
        self,
        team_id: int,
        round_: int,
        entries: list[StoredTeamRoundLineupEntry],
    ):
        """Replace the entire lineup of a team for a round."""
        self.execute(
            'DELETE FROM `team_round_lineup` WHERE `team_id` = ? AND `round` = ?',
            (team_id, round_),
        )
        if not entries:
            return
        self.executemany(
            'INSERT INTO `team_round_lineup`'
            '(`team_id`, `round`, `player_id`, `index`) VALUES (?, ?, ?, ?)',
            [(team_id, round_, entry.player_id, entry.index) for entry in entries],
        )

    def delete_team_round_lineup(self, team_id: int, round_: int):
        self.execute(
            'DELETE FROM `team_round_lineup` WHERE `team_id` = ? AND `round` = ?',
            (team_id, round_),
        )

    # ---------------------------------------------------------------------------------
    # StoredTeamBoard
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_team_board(cls, row: dict[str, Any]) -> StoredTeamBoard:
        return StoredTeamBoard(
            id=row['id'],
            tournament_id=row['tournament_id'],
            round_=row['round'],
            team_a_id=row['team_a_id'],
            team_b_id=row['team_b_id'],
            index=row['index'],
            last_result_update=cls.load_optional_timestamp_from_database_field(
                row['last_result_update']
            ),
            bye_type=row['bye_type'],
        )

    def load_tournament_stored_team_boards_by_round(
        self, tournament_id: int
    ) -> dict[int, list[StoredTeamBoard]]:
        self.execute(
            'SELECT * FROM `team_board` WHERE `tournament_id` = ? '
            'ORDER BY `round`, `index` IS NULL, `index`',
            (tournament_id,),
        )
        result: dict[int, list[StoredTeamBoard]] = {}
        for row in self.fetchall():
            team_board = self._row_to_stored_team_board(row)
            result.setdefault(team_board.round_, []).append(team_board)
        return result

    def add_stored_team_board(self, stored_team_board: StoredTeamBoard) -> int:
        fields = self._get_fields_dict(
            stored_team_board,
            ['tournament_id', 'team_a_id', 'team_b_id', 'index', 'bye_type'],
        ) | {'round': stored_team_board.round_}
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `team_board`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (team_board_id := self._last_inserted_id()):
            raise RuntimeError('Team board insertion failed')
        return team_board_id

    def update_stored_team_board(self, stored_team_board: StoredTeamBoard):
        fields = self._get_fields_dict(
            stored_team_board,
            ['tournament_id', 'team_a_id', 'team_b_id', 'index', 'bye_type'],
        ) | {'round': stored_team_board.round_}
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_team_board.id is not None
        self.execute(
            f'UPDATE `team_board` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_team_board.id,),
        )

    def delete_stored_team_board(self, team_board_id: int):
        self.execute('DELETE FROM `team_board` WHERE `id` = ?', (team_board_id,))

    def find_stored_team_bye(self, team_id: int, round_: int) -> StoredTeamBoard | None:
        """Return the bye ``team_board`` row (``team_b_id`` ``None``)
        for the given team and round, or ``None`` if the team isn't
        currently flagged for a bye that round."""
        self.execute(
            'SELECT * FROM `team_board` WHERE `team_a_id` = ? AND '
            '`round` = ? AND `team_b_id` IS NULL',
            (team_id, round_),
        )
        row = self.fetchone()
        return self._row_to_stored_team_board(row) if row else None

    def delete_stored_team_boards_for_round(self, tournament_id: int, round_: int):
        self.execute(
            'DELETE FROM `team_board` WHERE `tournament_id` = ? AND `round` = ?',
            (tournament_id, round_),
        )

    def update_team_board_last_result_update(
        self, team_board_id: int, clear: bool = False
    ) -> datetime | None:
        if clear:
            self.execute(
                'UPDATE `team_board` SET `last_result_update` = NULL WHERE `id` = ?',
                (team_board_id,),
            )
            return None
        now = datetime.now()
        self.execute(
            'UPDATE `team_board` SET `last_result_update` = ? WHERE `id` = ?',
            (self.dump_optional_datetime_to_timestamp_field(now), team_board_id),
        )
        return now

    # ---------------------------------------------------------------------------------
    # StoredTeamPairingBlock
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_team_pairing_block(
        cls, row: dict[str, Any]
    ) -> StoredTeamPairingBlock:
        return StoredTeamPairingBlock(
            id=row['id'],
            tournament_id=row['tournament_id'],
            round_=row['round'],
            team_a_id=row['team_a_id'],
            team_b_id=row['team_b_id'],
            reason=row['reason'],
        )

    def load_tournament_stored_team_pairing_blocks(
        self, tournament_id: int
    ) -> list[StoredTeamPairingBlock]:
        self.execute(
            'SELECT * FROM `team_pairing_block` WHERE `tournament_id` = ?',
            (tournament_id,),
        )
        return [self._row_to_stored_team_pairing_block(row) for row in self.fetchall()]

    def add_stored_team_pairing_block(
        self, stored_block: StoredTeamPairingBlock
    ) -> int:
        fields = self._get_fields_dict(
            stored_block,
            ['tournament_id', 'team_a_id', 'team_b_id', 'reason'],
        ) | {'round': stored_block.round_}
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `team_pairing_block`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (block_id := self._last_inserted_id()):
            raise RuntimeError('Team pairing block insertion failed')
        return block_id

    def delete_stored_team_pairing_block(self, block_id: int):
        self.execute('DELETE FROM `team_pairing_block` WHERE `id` = ?', (block_id,))

    def delete_tournament_stored_team_pairing_blocks(
        self, tournament_id: int, round_: int | None = None
    ):
        if round_ is None:
            self.execute(
                'DELETE FROM `team_pairing_block` WHERE `tournament_id` = ?',
                (tournament_id,),
            )
        else:
            self.execute(
                'DELETE FROM `team_pairing_block` '
                'WHERE `tournament_id` = ? AND `round` = ?',
                (tournament_id, round_),
            )

    # ---------------------------------------------------------------------------------
    # StoredTeamPointAdjustment
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_team_point_adjustment(
        cls, row: dict[str, Any]
    ) -> StoredTeamPointAdjustment:
        return StoredTeamPointAdjustment(
            id=row['id'],
            tournament_id=row['tournament_id'],
            team_id=row['team_id'],
            round_=row['round'],
            mp_delta=row['mp_delta'],
            gp_delta=row['gp_delta'],
            reason=row['reason'],
        )

    def load_tournament_stored_team_point_adjustments(
        self, tournament_id: int
    ) -> list[StoredTeamPointAdjustment]:
        self.execute(
            'SELECT * FROM `team_point_adjustment` WHERE `tournament_id` = ?',
            (tournament_id,),
        )
        return [
            self._row_to_stored_team_point_adjustment(row) for row in self.fetchall()
        ]

    def set_stored_team_point_adjustment(
        self,
        tournament_id: int,
        team_id: int,
        round_: int,
        mp_delta: float,
        gp_delta: float,
        reason: str | None,
    ):
        """Upsert a (team, round) manual adjustment. A row with nothing
        to record (both deltas zero and no reason) is removed."""
        if not mp_delta and not gp_delta and not reason:
            self.execute(
                'DELETE FROM `team_point_adjustment` '
                'WHERE `tournament_id` = ? AND `team_id` = ? AND `round` = ?',
                (tournament_id, team_id, round_),
            )
            return
        self.execute(
            'INSERT INTO `team_point_adjustment` '
            '(`tournament_id`, `team_id`, `round`, `mp_delta`, `gp_delta`, `reason`) '
            'VALUES (?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(`tournament_id`, `team_id`, `round`) DO UPDATE SET '
            '`mp_delta` = excluded.`mp_delta`, '
            '`gp_delta` = excluded.`gp_delta`, '
            '`reason` = excluded.`reason`',
            (tournament_id, team_id, round_, mp_delta, gp_delta, reason),
        )

    @classmethod
    def _row_to_stored_player_point_adjustment(
        cls, row: dict[str, Any]
    ) -> StoredPlayerPointAdjustment:
        return StoredPlayerPointAdjustment(
            id=row['id'],
            tournament_id=row['tournament_id'],
            player_id=row['player_id'],
            round_=row['round'],
            delta=row['delta'],
            reason=row['reason'],
        )

    def load_tournament_stored_player_point_adjustments(
        self, tournament_id: int
    ) -> list[StoredPlayerPointAdjustment]:
        self.execute(
            'SELECT * FROM `player_point_adjustment` WHERE `tournament_id` = ?',
            (tournament_id,),
        )
        return [
            self._row_to_stored_player_point_adjustment(row) for row in self.fetchall()
        ]

    def set_stored_player_point_adjustment(
        self,
        tournament_id: int,
        player_id: int,
        round_: int,
        delta: float,
        reason: str | None,
    ):
        """Upsert a (player, round) manual adjustment. A row with nothing
        to record (no delta and no reason) is removed."""
        if not delta and not reason:
            self.execute(
                'DELETE FROM `player_point_adjustment` '
                'WHERE `tournament_id` = ? AND `player_id` = ? AND `round` = ?',
                (tournament_id, player_id, round_),
            )
            return
        self.execute(
            'INSERT INTO `player_point_adjustment` '
            '(`tournament_id`, `player_id`, `round`, `delta`, `reason`) '
            'VALUES (?, ?, ?, ?, ?) '
            'ON CONFLICT(`tournament_id`, `player_id`, `round`) DO UPDATE SET '
            '`delta` = excluded.`delta`, '
            '`reason` = excluded.`reason`',
            (tournament_id, player_id, round_, delta, reason),
        )

    # ---------------------------------------------------------------------------------
    # StoredProhibitedPairingGroup
    # ---------------------------------------------------------------------------------

    def load_tournament_stored_prohibited_pairing_groups(
        self, tournament_id: int
    ) -> list[StoredProhibitedPairingGroup]:
        self.execute(
            'SELECT * FROM `prohibited_pairing_group` WHERE `tournament_id` = ? '
            'ORDER BY `round` IS NOT NULL, `round`, `id`',
            (tournament_id,),
        )
        groups: list[StoredProhibitedPairingGroup] = []
        groups_by_id: dict[int, StoredProhibitedPairingGroup] = {}
        for row in self.fetchall():
            group = StoredProhibitedPairingGroup(
                id=row['id'],
                tournament_id=row['tournament_id'],
                round_=row['round'],
                is_hard=self.load_bool_from_database_field(row['is_hard']),
                protect_rank=row['protect_rank'],
            )
            groups.append(group)
            if group.id is not None:
                groups_by_id[group.id] = group
        if groups_by_id:
            placeholders = ', '.join('?' for _ in groups_by_id)
            self.execute(
                'SELECT * FROM `prohibited_pairing_group_member` '
                f'WHERE `group_id` IN ({placeholders})',
                tuple(groups_by_id.keys()),
            )
            for row in self.fetchall():
                groups_by_id[row['group_id']].member_ids.append(row['member_id'])
        return groups

    def _add_stored_prohibited_pairing_group(
        self,
        tournament_id: int,
        round_: int | None,
        is_hard: bool,
        member_ids: list[int],
        protect_rank: int | None = None,
    ) -> int:
        self.execute(
            'INSERT INTO `prohibited_pairing_group` '
            '(`tournament_id`, `round`, `is_hard`, `protect_rank`) '
            'VALUES (?, ?, ?, ?)',
            (tournament_id, round_, 1 if is_hard else 0, protect_rank),
        )
        group_id = self._last_inserted_id()
        if not group_id:
            raise RuntimeError('Prohibited pairing group insertion failed')
        for member_id in member_ids:
            self.execute(
                'INSERT OR IGNORE INTO `prohibited_pairing_group_member` '
                '(`group_id`, `member_id`) VALUES (?, ?)',
                (group_id, member_id),
            )
        return group_id

    def replace_manual_prohibited_pairing_groups(
        self,
        tournament_id: int,
        groups: list[tuple[bool, list[int]]],
    ):
        """Replace the tournament's manual template groups (``round``
        NULL). Each group is ``(is_hard, member_ids)``."""
        self.execute(
            'DELETE FROM `prohibited_pairing_group` '
            'WHERE `tournament_id` = ? AND `round` IS NULL',
            (tournament_id,),
        )
        for is_hard, member_ids in groups:
            self._add_stored_prohibited_pairing_group(
                tournament_id, None, is_hard, member_ids
            )

    def replace_round_prohibited_pairing_snapshot(
        self,
        tournament_id: int,
        round_: int,
        groups: list[tuple[bool, list[int]]],
        protect_rank: int | None = None,
    ):
        """Replace the immutable per-round snapshot for ``round_``.
        ``protect_rank`` is the soft-relaxation cutoff for the round,
        stored on every row so the export can regenerate the applied set."""
        self.delete_round_prohibited_pairing_snapshot(tournament_id, round_)
        for is_hard, member_ids in groups:
            self._add_stored_prohibited_pairing_group(
                tournament_id, round_, is_hard, member_ids, protect_rank
            )

    def delete_round_prohibited_pairing_snapshot(self, tournament_id: int, round_: int):
        self.execute(
            'DELETE FROM `prohibited_pairing_group` '
            'WHERE `tournament_id` = ? AND `round` = ?',
            (tournament_id, round_),
        )

    # ---------------------------------------------------------------------------------
    # StoredFamily
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_family(cls, row: dict[str, Any]) -> StoredFamily:
        return StoredFamily(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            public=cls.load_bool_from_database_field(row['public']),
            tournament_id=row['tournament_id'],
            input_exit_button=cls.load_bool_or_none_from_database_field(
                row['input_exit_button']
            ),
            players_show_unpaired=cls.load_bool_or_none_from_database_field(
                row['players_show_unpaired']
            ),
            players_player_format=row.get('players_player_format', None),
            players_board_format=row.get('players_board_format', None),
            players_opponent_format=row.get('players_opponent_format', None),
            ranking_crosstable=cls.load_bool_from_database_field(
                row['ranking_crosstable']
            ),
            ranking_round=row['ranking_round'],
            ranking_min_points=row['ranking_min_points'],
            ranking_max_points=row['ranking_max_points'],
            columns=row['columns'],
            font_size=row['font_size'],
            menu_text=row['menu_text'],
            timer_id=row['timer_id'],
            first=row['first'],
            last=row['last'],
            parts=row['parts'],
            number=row['number'],
            fixed_board_order=row.get('fixed_board_order'),
            message_default=cls.load_bool_from_database_field(row['message_default']),
            message_text=row['message_text'],
            last_update=cls.load_datetime_from_database_field(row['last_update']),
        )

    def get_stored_family(self, family_id: int) -> StoredFamily | None:
        self.execute(
            'SELECT * FROM `family` WHERE `id` = ?',
            (family_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_family(row)
        return None

    def load_stored_families(self) -> Iterator[StoredFamily]:
        self.execute(
            'SELECT * FROM `family` ORDER BY `uniq_id`',
            (),
        )
        yield from map(self._row_to_stored_family, self.fetchall())

    def _write_stored_family(
        self,
        stored_family: StoredFamily,
    ) -> StoredFamily:
        fields: list[str] = [
            'uniq_id',
            'name',
            'type',
            'public',
            'tournament_id',
            'columns',
            'font_size',
            'menu_text',
            'timer_id',
            'input_exit_button',
            'players_show_unpaired',
            'players_player_format',
            'players_board_format',
            'players_opponent_format',
            'ranking_crosstable',
            'ranking_round',
            'ranking_min_points',
            'ranking_max_points',
            'first',
            'last',
            'parts',
            'number',
            'fixed_board_order',
            'message_default',
            'message_text',
            'last_update',
        ]
        params: list = [
            stored_family.uniq_id,
            stored_family.name,
            stored_family.type,
            stored_family.public,
            stored_family.tournament_id,
            stored_family.columns,
            stored_family.font_size,
            stored_family.menu_text,
            stored_family.timer_id,
            stored_family.input_exit_button,
            stored_family.players_show_unpaired,
            stored_family.players_player_format,
            stored_family.players_board_format,
            stored_family.players_opponent_format,
            stored_family.ranking_crosstable,
            stored_family.ranking_round,
            stored_family.ranking_min_points,
            stored_family.ranking_max_points,
            stored_family.first,
            stored_family.last,
            stored_family.parts,
            stored_family.number,
            stored_family.fixed_board_order,
            stored_family.message_default,
            stored_family.message_text,
            self.now_as_database_timestamp(),
        ]
        if stored_family.id is None:
            protected_fields = [f'`{f}`' for f in fields]
            self.execute(
                f'INSERT INTO `family`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params),
            )
            family_id: int | None = self._last_inserted_id()
            if family_id is None:
                raise RuntimeError('Family insertion failed')
            fetched_stored_family = self.get_stored_family(family_id)
        else:
            field_sets = [f'`{f}` = ?' for f in fields]
            params += [stored_family.id]
            self.execute(
                f'UPDATE `family` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params),
            )
            fetched_stored_family = self.get_stored_family(stored_family.id)
        if fetched_stored_family is None:
            raise RuntimeError('Family write failed')
        return fetched_stored_family

    def add_stored_family(
        self,
        stored_family: StoredFamily,
    ) -> StoredFamily:
        assert stored_family.id is None, f'stored_family.id={stored_family.id}'
        return self._write_stored_family(stored_family)

    def update_stored_family(
        self,
        stored_family: StoredFamily,
    ) -> StoredFamily:
        assert stored_family.id is not None
        return self._write_stored_family(stored_family)

    def delete_stored_family(self, family_id: int):
        self.execute('DELETE FROM `family` WHERE `id` = ?;', (family_id,))

    # ---------------------------------------------------------------------------------
    # StoredScreen
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_screen(cls, row: dict[str, Any]) -> StoredScreen:
        return StoredScreen(
            id=row['id'],
            uniq_id=row['uniq_id'],
            name=row['name'],
            type=row['type'],
            public=cls.load_bool_from_database_field(row['public']),
            columns=row['columns'],
            font_size=row['font_size'],
            menu_text=row['menu_text'],
            timer_id=row['timer_id'],
            input_exit_button=cls.load_bool_or_none_from_database_field(
                row['input_exit_button']
            ),
            players_show_unpaired=cls.load_bool_or_none_from_database_field(
                row['players_show_unpaired']
            ),
            players_player_format=row['players_player_format'],
            players_board_format=row['players_board_format'],
            players_opponent_format=row['players_opponent_format'],
            results_limit=row['results_limit'],
            results_max_age=row['results_max_age'],
            results_tournament_ids=cls.load_json_from_database_field(
                row['results_tournament_ids']
            ),
            ranking_crosstable=cls.load_bool_from_database_field(
                row['ranking_crosstable']
            ),
            ranking_round=row['ranking_round'],
            ranking_min_points=row['ranking_min_points'],
            ranking_max_points=row['ranking_max_points'],
            background_image=row['background_image'],
            background_color=row['background_color'],
            message_default=cls.load_bool_from_database_field(row['message_default']),
            message_text=row['message_text'],
            plugin_data=cls.load_json_from_database_field(row['plugin_data'], {}),
            last_update=cls.load_datetime_from_database_field(row['last_update']),
        )

    def get_stored_screen(self, screen_id: int) -> StoredScreen | None:
        self.execute(
            'SELECT * FROM `screen` WHERE `id` = ?',
            (screen_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_screen(row)
        return None

    def load_stored_screens(self) -> Iterator[StoredScreen]:
        self.execute(
            'SELECT * FROM `screen` ORDER BY `uniq_id`',
            (),
        )
        stored_screens = [self._row_to_stored_screen(row) for row in self.fetchall()]
        if not stored_screens:
            return

        self.execute('SELECT * FROM `screen_set` ORDER BY `screen_id`, `order`')
        stored_screen_sets_by_screen_id: dict[int, list[StoredScreenSet]] = defaultdict(
            list
        )
        for row in self.fetchall():
            stored_screen_set = self._row_to_stored_screen_set(row)
            stored_screen_sets_by_screen_id[stored_screen_set.screen_id].append(
                stored_screen_set
            )

        for stored_screen in stored_screens:
            assert stored_screen.id is not None
            stored_screen.stored_screen_sets = stored_screen_sets_by_screen_id.get(
                stored_screen.id, []
            )
            yield stored_screen

    def _set_stored_screen_last_update(self, screen_id: int):
        self.execute(
            'UPDATE `screen` SET `last_update` = ? WHERE `id` = ?',
            (
                self.now_as_database_timestamp(),
                screen_id,
            ),
        )

    def _write_stored_screen(
        self,
        stored_screen: StoredScreen,
    ) -> StoredScreen:
        fields: list[str] = [
            'uniq_id',
            'name',
            'type',
            'public',
            'input_exit_button',
            'players_show_unpaired',
            'players_player_format',
            'players_board_format',
            'players_opponent_format',
            'columns',
            'font_size',
            'menu_text',
            'timer_id',
            'results_limit',
            'results_max_age',
            'results_tournament_ids',
            'ranking_crosstable',
            'ranking_round',
            'ranking_min_points',
            'ranking_max_points',
            'background_image',
            'background_color',
            'message_default',
            'message_text',
            'plugin_data',
            'last_update',
        ]
        params: list = [
            stored_screen.uniq_id,
            stored_screen.name,
            stored_screen.type,
            stored_screen.public,
            stored_screen.input_exit_button
            if stored_screen.type in ('input', 'check-in')
            else None,
            stored_screen.players_show_unpaired
            if stored_screen.type == 'players'
            else None,
            stored_screen.players_player_format
            if stored_screen.type == 'players'
            else None,
            stored_screen.players_board_format
            if stored_screen.type == 'players'
            else None,
            stored_screen.players_opponent_format
            if stored_screen.type == 'players'
            else None,
            stored_screen.columns,
            stored_screen.font_size,
            stored_screen.menu_text if stored_screen.type != 'image' else None,
            stored_screen.timer_id,
            stored_screen.results_limit if stored_screen.type == 'results' else None,
            stored_screen.results_max_age if stored_screen.type == 'results' else None,
            self.dump_to_json_database_field(stored_screen.results_tournament_ids, [])
            if stored_screen.type == 'results'
            else None,
            stored_screen.ranking_crosstable
            if stored_screen.type == 'ranking'
            else False,
            stored_screen.ranking_round if stored_screen.type == 'ranking' else None,
            stored_screen.ranking_min_points
            if stored_screen.type == 'ranking'
            else None,
            stored_screen.ranking_max_points
            if stored_screen.type == 'ranking'
            else None,
            stored_screen.background_image if stored_screen.type == 'image' else None,
            stored_screen.background_color if stored_screen.type == 'image' else None,
            stored_screen.message_default,
            stored_screen.message_text,
            self.dump_to_json_database_field(stored_screen.plugin_data, {}),
            self.now_as_database_timestamp(),
        ]
        if stored_screen.id is None:
            protected_fields = [f'`{f}`' for f in fields]
            self.execute(
                f'INSERT INTO `screen`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params),
            )
            screen_id = self._last_inserted_id()
            if screen_id is None:
                raise RuntimeError('Screen insertion failed')
            fetched_stored_screen = self.get_stored_screen(screen_id=screen_id)
        else:
            field_sets = [f'`{f}` = ?' for f in fields]
            params += [stored_screen.id]
            self.execute(
                f'UPDATE `screen` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params),
            )
            fetched_stored_screen = self.get_stored_screen(screen_id=stored_screen.id)
        if fetched_stored_screen is None:
            raise RuntimeError('Screen write failed')
        return fetched_stored_screen

    def add_stored_screen(
        self,
        stored_screen: StoredScreen,
    ) -> StoredScreen:
        assert stored_screen.id is None, f'stored_screen.id={stored_screen.id}'
        return self._write_stored_screen(stored_screen)

    def update_stored_screen(
        self,
        stored_screen: StoredScreen,
    ) -> StoredScreen:
        assert stored_screen.id is not None
        return self._write_stored_screen(stored_screen)

    def delete_stored_screen(self, screen_id: int):
        self.execute('DELETE FROM `screen` WHERE `id` = ?;', (screen_id,))

    # ---------------------------------------------------------------------------------
    # StoredScreenSet
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_screen_set(cls, row: dict[str, Any]) -> StoredScreenSet:
        return StoredScreenSet(
            id=row['id'],
            screen_id=row['screen_id'],
            tournament_id=row['tournament_id'],
            order=row['order'],
            name=row['name'],
            fixed_boards_str=row['fixed_boards_str'],
            first=row['first'],
            last=row['last'],
            fixed_board_order=row.get('fixed_board_order'),
            last_update=cls.load_datetime_from_database_field(row['last_update']),
        )

    def get_stored_screen_set(self, screen_set_id: int) -> StoredScreenSet | None:
        self.execute(
            'SELECT * FROM `screen_set` WHERE `id` = ?',
            (screen_set_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_screen_set(row)
        return None

    def get_stored_screen_next_set_order(self, screen_id: int) -> int:
        self.execute(
            'SELECT MAX(`order`) AS order_max FROM `screen_set` WHERE `screen_id` = ?',
            (screen_id,),
        )
        row: dict[str, Any] = self.fetchone()
        return (row['order_max'] if row['order_max'] else 0) + 1

    def load_stored_screen_sets(self, screen_id: int) -> Iterator[StoredScreenSet]:
        self.execute(
            'SELECT * FROM `screen_set` WHERE `screen_id` = ? ORDER BY `order`',
            (screen_id,),
        )
        yield from map(self._row_to_stored_screen_set, self.fetchall())

    def reorder_stored_screen_sets(
        self,
        screen_id: int,
        screen_set_ids: list[int],
    ):
        order: int = 1
        for screen_set_id in screen_set_ids:
            self.execute(
                'UPDATE `screen_set` SET `order` = ?, `last_update` = ? WHERE `id` = ?',
                (
                    order,
                    self.now_as_database_timestamp(),
                    screen_set_id,
                ),
            )
            order += 1
        self._set_stored_screen_last_update(screen_id)

    def _write_stored_screen_set(
        self,
        stored_screen_set: StoredScreenSet,
    ) -> StoredScreenSet:
        fields: list[str] = [
            'screen_id',
            'tournament_id',
            'name',
            'order',
            'fixed_boards_str',
            'first',
            'last',
            'fixed_board_order',
            'last_update',
        ]
        params: list = [
            stored_screen_set.screen_id,
            stored_screen_set.tournament_id,
            stored_screen_set.name,
            stored_screen_set.order,
            stored_screen_set.fixed_boards_str,
            stored_screen_set.first,
            stored_screen_set.last,
            stored_screen_set.fixed_board_order,
            self.now_as_database_timestamp(),
        ]
        if stored_screen_set.id is None:
            protected_fields = [f'`{f}`' for f in fields]
            self.execute(
                f'INSERT INTO `screen_set`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params),
            )
            screen_set_id: int | None = self._last_inserted_id()
            if screen_set_id is None:
                raise RuntimeError('Screen set insertion failed')
            fetched_stored_screen_set = self.get_stored_screen_set(
                screen_set_id=screen_set_id
            )
        else:
            field_sets = [f'`{f}` = ?' for f in fields]
            params += [stored_screen_set.id]
            self.execute(
                f'UPDATE `screen_set` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params),
            )
            fetched_stored_screen_set = self.get_stored_screen_set(
                screen_set_id=stored_screen_set.id
            )
        if fetched_stored_screen_set is None:
            raise RuntimeError('Screen set write failed')
        return fetched_stored_screen_set

    def clone_stored_screen_set(
        self,
        screen_set_id: int,
        screen_id: int,
    ) -> StoredScreenSet:
        stored_screen_set = self.get_stored_screen_set(screen_set_id)
        assert stored_screen_set is not None
        stored_screen_set.id = None
        stored_screen_set.screen_id = screen_id
        stored_screen_set.order = self.get_stored_screen_next_set_order(
            stored_screen_set.screen_id
        )
        new_stored_screen_set: StoredScreenSet = self._write_stored_screen_set(
            stored_screen_set
        )
        return new_stored_screen_set

    def add_stored_screen_set(
        self,
        screen_id: int,
        tournament_id: int,
    ) -> StoredScreenSet:
        stored_screen_set: StoredScreenSet = StoredScreenSet(
            id=None,
            screen_id=screen_id,
            tournament_id=tournament_id,
            order=self.get_stored_screen_next_set_order(screen_id),
            name=None,
            fixed_boards_str=None,
            first=None,
            last=None,
        )
        return self._write_stored_screen_set(stored_screen_set)

    def update_stored_screen_set(
        self,
        stored_screen_set: StoredScreenSet,
    ) -> StoredScreenSet:
        assert stored_screen_set.id is not None
        return self._write_stored_screen_set(stored_screen_set)

    def delete_stored_screen_set(self, screen_set_id: int, screen_id: int):
        order: int = 1
        for stored_screen_set in self.load_stored_screen_sets(screen_id):
            self.execute(
                'UPDATE `screen_set` SET `order` = ?, `last_update` = ? WHERE `id` = ?',
                (
                    order,
                    self.now_as_database_timestamp(),
                    stored_screen_set.id,
                ),
            )
            order += 1
        self._set_stored_screen_last_update(screen_id)
        self.execute('DELETE FROM `screen_set` WHERE `id` = ?;', (screen_set_id,))

    # ---------------------------------------------------------------------------------
    # StoredRotator
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_rotator(cls, row: dict[str, Any]) -> StoredRotator:
        return StoredRotator(
            id=row['id'],
            name=row['name'],
            public=cls.load_bool_from_database_field(row['public']),
            delay=row['delay'],
            message_default=cls.load_bool_from_database_field(row['message_default']),
            message_text=row['message_text'],
            timer_id=row['timer_id'],
        )

    def load_stored_rotators(self) -> list[StoredRotator]:
        self.execute('SELECT * FROM `rotator` ORDER BY `name`')
        stored_rotators: list[StoredRotator] = []
        for row in self.fetchall():
            stored_rotator = self._row_to_stored_rotator(row)
            stored_rotator.stored_rotating_screens = (
                self.load_rotator_stored_rotating_screens(row['id'])
            )
            stored_rotators.append(stored_rotator)
        return stored_rotators

    def add_stored_rotator(self, stored_rotator: StoredRotator) -> int:
        fields: dict[str, Any] = self._get_fields_dict(
            stored_rotator,
            [
                'name',
                'public',
                'delay',
                'message_default',
                'message_text',
                'timer_id',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `rotator`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (rotator_id := self._last_inserted_id()):
            raise RuntimeError('Insertion failed')
        return rotator_id

    def update_stored_rotator(self, stored_rotator: StoredRotator):
        fields: dict[str, Any] = self._get_fields_dict(
            stored_rotator,
            [
                'name',
                'public',
                'delay',
                'message_default',
                'message_text',
                'timer_id',
            ],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_rotator.id is not None
        self.execute(
            f'UPDATE `rotator` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_rotator.id,),
        )

    def delete_stored_rotator(self, rotator_id: int):
        self.execute('DELETE FROM `rotator` WHERE `id` = ?;', (rotator_id,))

    # ---------------------------------------------------------------------------------
    # StoredRotatingScreen
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_rotating_screen(
        cls, row: dict[str, Any]
    ) -> StoredRotatingScreen:
        return StoredRotatingScreen(
            id=row['id'],
            rotator_id=row['rotator_id'],
            screen_id=row['screen_id'],
            family_id=row['family_id'],
            index=row['index'],
        )

    def load_rotator_stored_rotating_screens(
        self, rotator_id: int
    ) -> list[StoredRotatingScreen]:
        self.execute(
            'SELECT * FROM `rotating_screen` WHERE `rotator_id` = ? ORDER BY `index`',
            (rotator_id,),
        )
        return [self._row_to_stored_rotating_screen(row) for row in self.fetchall()]

    def add_stored_rotating_screen(
        self,
        stored_rotating_screen: StoredRotatingScreen,
    ):
        fields = self._get_fields_dict(
            stored_rotating_screen,
            [
                'rotator_id',
                'screen_id',
                'family_id',
                'index',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `rotating_screen`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (rotating_screen_id := self._last_inserted_id()):
            raise RuntimeError('Insertion failed')
        return rotating_screen_id

    def update_stored_rotating_screen(
        self, stored_rotating_screen: StoredRotatingScreen
    ):
        self.execute(
            'UPDATE `rotating_screen` SET `index` = ? WHERE `id` = ?',
            (stored_rotating_screen.index, stored_rotating_screen.id),
        )

    def delete_stored_rotating_screen(self, rotating_screen_id: int):
        self.execute(
            'DELETE FROM `rotating_screen` WHERE `id` = ?',
            (rotating_screen_id,),
        )

    # ---------------------------------------------------------------------------------
    # StoredMenu
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_menu(cls, row: dict[str, Any]) -> StoredMenu:
        return StoredMenu(
            id=row['id'],
            name=row['name'],
            default_type=row['default_type'],
            submenu_mode=row['submenu_mode'],
        )

    def load_stored_menus(self) -> list[StoredMenu]:
        self.execute('SELECT * FROM `menu` ORDER BY `name`')
        stored_menus: list[StoredMenu] = []
        for row in self.fetchall():
            stored_menu = self._row_to_stored_menu(row)
            stored_menu.stored_menu_items = self.load_menu_stored_menu_items(row['id'])
            stored_menus.append(stored_menu)
        return stored_menus

    def add_stored_menu(self, stored_menu: StoredMenu) -> int:
        fields: dict[str, Any] = self._get_fields_dict(
            stored_menu,
            ['name', 'default_type', 'submenu_mode'],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `menu`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (menu_id := self._last_inserted_id()):
            raise RuntimeError('Insertion failed')
        return menu_id

    def update_stored_menu(self, stored_menu: StoredMenu):
        fields: dict[str, Any] = self._get_fields_dict(
            stored_menu,
            ['name', 'default_type', 'submenu_mode'],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_menu.id is not None
        self.execute(
            f'UPDATE `menu` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_menu.id,),
        )

    def delete_stored_menu(self, menu_id: int):
        self.execute('DELETE FROM `menu` WHERE `id` = ?;', (menu_id,))

    # ---------------------------------------------------------------------------------
    # StoredMenuItem
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_menu_item(cls, row: dict[str, Any]) -> StoredMenuItem:
        return StoredMenuItem(
            id=row['id'],
            menu_id=row['menu_id'],
            screen_id=row['screen_id'],
            family_id=row['family_id'],
            screen_type=row['screen_type'],
            index=row['index'],
        )

    def load_menu_stored_menu_items(self, menu_id: int) -> list[StoredMenuItem]:
        self.execute(
            'SELECT * FROM `menu_item` WHERE `menu_id` = ? ORDER BY `index`',
            (menu_id,),
        )
        return [self._row_to_stored_menu_item(row) for row in self.fetchall()]

    def add_stored_menu_item(self, stored_menu_item: StoredMenuItem):
        fields = self._get_fields_dict(
            stored_menu_item,
            ['menu_id', 'screen_id', 'family_id', 'screen_type', 'index'],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `menu_item`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (menu_item_id := self._last_inserted_id()):
            raise RuntimeError('Insertion failed')
        return menu_item_id

    def update_stored_menu_item(self, stored_menu_item: StoredMenuItem):
        self.execute(
            'UPDATE `menu_item` SET `index` = ? WHERE `id` = ?',
            (stored_menu_item.index, stored_menu_item.id),
        )

    def delete_stored_menu_item(self, menu_item_id: int):
        self.execute(
            'DELETE FROM `menu_item` WHERE `id` = ?',
            (menu_item_id,),
        )

    # ---------------------------------------------------------------------------------
    # StoredDisplayController
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_display_controller(
        cls, row: dict[str, Any]
    ) -> StoredDisplayController:
        return StoredDisplayController(
            id=row['id'],
            name=row['name'],
            screen_id=row['screen_id'],
            rotator_id=row['rotator_id'],
            public=cls.load_bool_from_database_field(row['public']),
        )

    def get_stored_display_controller(
        self, display_controller_id: int
    ) -> StoredDisplayController | None:
        self.execute(
            'SELECT * FROM `display_controller` WHERE `id` = ?',
            (display_controller_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_display_controller(row)
        return None

    def load_stored_display_controllers(
        self,
    ) -> Iterator[StoredDisplayController]:
        self.execute(
            'SELECT * FROM `display_controller` ORDER BY `name`',
            (),
        )
        yield from map(self._row_to_stored_display_controller, self.fetchall())

    def _write_stored_display_controller(
        self,
        stored_display_controller: StoredDisplayController,
    ) -> StoredDisplayController:
        fields: list[str] = [
            'name',
            'public',
            'screen_id',
            'rotator_id',
            'last_update',
        ]
        params: list = [
            stored_display_controller.name,
            stored_display_controller.public,
            stored_display_controller.screen_id,
            stored_display_controller.rotator_id,
            self.now_as_database_timestamp(),
        ]
        if stored_display_controller.id is None:
            protected_fields = [f'`{f}`' for f in fields]
            self.execute(
                f'INSERT INTO `display_controller`({", ".join(protected_fields)}) VALUES ({", ".join(["?"] * len(fields))})',
                tuple(params),
            )
            display_controller_id: int | None = self._last_inserted_id()
            if display_controller_id is None:
                raise RuntimeError('Display controller insertion failed')
            fetched_stored_display_controller = self.get_stored_display_controller(
                display_controller_id
            )
        else:
            field_sets = [f'`{f}` = ?' for f in fields]
            params += [stored_display_controller.id]
            self.execute(
                f'UPDATE `display_controller` SET {", ".join(field_sets)} WHERE `id` = ?',
                tuple(params),
            )
            fetched_stored_display_controller = self.get_stored_display_controller(
                stored_display_controller.id
            )
        if fetched_stored_display_controller is None:
            raise RuntimeError('Display controller write failed')
        return fetched_stored_display_controller

    def add_stored_display_controller(
        self,
        stored_display_controller: StoredDisplayController,
    ) -> StoredDisplayController:
        assert stored_display_controller.id is None
        return self._write_stored_display_controller(stored_display_controller)

    def update_stored_display_controller(
        self,
        stored_display_controller: StoredDisplayController,
    ) -> StoredDisplayController:
        assert stored_display_controller.id is not None
        return self._write_stored_display_controller(stored_display_controller)

    def delete_stored_display_controller(self, display_controller_id: int):
        self.execute(
            'DELETE FROM `display_controller` WHERE `id` = ?;', (display_controller_id,)
        )

    # ---------------------------------------------------------------------------------
    # StoredPrizeGroup
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_prize_group(cls, row: dict[str, Any]) -> StoredPrizeGroup:
        return StoredPrizeGroup(
            id=row['id'],
            tournament_id=row['tournament_id'],
            name=row['name'],
        )

    def load_tournament_stored_prize_groups(
        self, tournament_id: int
    ) -> list[StoredPrizeGroup]:
        self.execute(
            'SELECT * FROM `prize_group` WHERE `tournament_id` = ? ORDER BY `id`',
            (tournament_id,),
        )
        stored_prize_groups = [
            self._row_to_stored_prize_group(row) for row in self.fetchall()
        ]
        if not stored_prize_groups:
            return []

        self.execute(
            'SELECT `prize_category`.* FROM `prize_category` '
            'JOIN `prize_group` '
            'ON `prize_category`.`prize_group_id` = `prize_group`.`id` '
            'WHERE `prize_group`.`tournament_id` = ? '
            'ORDER BY `prize_category`.`id`',
            (tournament_id,),
        )
        stored_prize_categories = [
            self._row_to_stored_prize_category(row) for row in self.fetchall()
        ]

        self.execute(
            'SELECT `prize_criterion`.* FROM `prize_criterion` '
            'JOIN `prize_category` '
            'ON `prize_criterion`.`prize_category_id` = `prize_category`.`id` '
            'JOIN `prize_group` '
            'ON `prize_category`.`prize_group_id` = `prize_group`.`id` '
            'WHERE `prize_group`.`tournament_id` = ? '
            'ORDER BY `prize_criterion`.`id`',
            (tournament_id,),
        )
        criteria_by_category: dict[int, list[StoredPrizeCriterion]] = {}
        for row in self.fetchall():
            criterion = self._row_to_stored_prize_criterion(row)
            criteria_by_category.setdefault(criterion.prize_category_id, []).append(
                criterion
            )

        self.execute(
            'SELECT `prize`.* FROM `prize` '
            'JOIN `prize_category` '
            'ON `prize`.`prize_category_id` = `prize_category`.`id` '
            'JOIN `prize_group` '
            'ON `prize_category`.`prize_group_id` = `prize_group`.`id` '
            'WHERE `prize_group`.`tournament_id` = ? '
            'ORDER BY `prize`.`id`',
            (tournament_id,),
        )
        prizes_by_category: dict[int, list[StoredPrize]] = {}
        for row in self.fetchall():
            prize = self._row_to_stored_prize(row)
            prizes_by_category.setdefault(prize.prize_category_id, []).append(prize)

        categories_by_group: dict[int, list[StoredPrizeCategory]] = {}
        for category in stored_prize_categories:
            assert category.id is not None
            category.stored_prize_criteria = criteria_by_category.get(category.id, [])
            category.stored_prizes = prizes_by_category.get(category.id, [])
            categories_by_group.setdefault(category.prize_group_id, []).append(category)

        for prize_group in stored_prize_groups:
            assert prize_group.id is not None
            prize_group.stored_prize_categories = categories_by_group.get(
                prize_group.id, []
            )
        return stored_prize_groups

    def add_stored_prize_group(self, stored_prize_group: StoredPrizeGroup) -> int:
        fields = self._get_fields_dict(stored_prize_group, ['tournament_id', 'name'])
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `prize_group`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (prize_group_id := self._last_inserted_id()):
            raise RuntimeError('Prize group insertion failed')
        return prize_group_id

    def update_stored_prize_group(self, stored_prize_group: StoredPrizeGroup):
        fields = self._get_fields_dict(stored_prize_group, ['tournament_id', 'name'])
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_prize_group.id is not None
        self.execute(
            f'UPDATE `prize_group` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_prize_group.id,),
        )

    def delete_stored_prize_group(self, prize_group_id: int):
        self.execute('DELETE FROM `prize_group` WHERE `id` = ?;', (prize_group_id,))

    # ---------------------------------------------------------------------------------
    # StoredPrizeCategory
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_prize_category(cls, row: dict[str, Any]) -> StoredPrizeCategory:
        return StoredPrizeCategory(
            id=row['id'],
            prize_group_id=row['prize_group_id'],
            name=row['name'],
            prize_sharing=row['prize_sharing'],
            sharing_threshold=row['sharing_threshold'],
            is_main=cls.load_bool_from_database_field(row['is_main']),
            index=row['index'],
            ranking_basis=row['ranking_basis'],
        )

    def load_prize_group_stored_prize_categories(
        self, prize_group_id: int
    ) -> list[StoredPrizeCategory]:
        self.execute(
            'SELECT * FROM `prize_category` WHERE `prize_group_id` = ?',
            (prize_group_id,),
        )
        stored_prize_categories: list[StoredPrizeCategory] = []
        for row in self.fetchall():
            prize_category = self._row_to_stored_prize_category(row)
            assert prize_category.id is not None
            prize_category.stored_prize_criteria = (
                self.load_prize_category_stored_prize_criteria(prize_category.id)
            )
            prize_category.stored_prizes = self.load_prize_category_stored_prizes(
                prize_category.id
            )
            stored_prize_categories.append(prize_category)
        return stored_prize_categories

    def add_stored_prize_category(
        self,
        stored_prize_category: StoredPrizeCategory,
    ) -> int:
        fields = self._get_fields_dict(
            stored_prize_category,
            [
                'prize_group_id',
                'name',
                'prize_sharing',
                'sharing_threshold',
                'is_main',
                'index',
                'ranking_basis',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `prize_category`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (prize_category_id := self._last_inserted_id()):
            raise RuntimeError('Prize category insertion failed')
        return prize_category_id

    def update_stored_prize_category(
        self,
        stored_prize_category: StoredPrizeCategory,
    ):
        fields = self._get_fields_dict(
            stored_prize_category,
            [
                'prize_group_id',
                'name',
                'prize_sharing',
                'sharing_threshold',
                'is_main',
                'ranking_basis',
            ],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_prize_category.id is not None
        self.execute(
            f'UPDATE `prize_category` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_prize_category.id,),
        )

    def update_stored_prize_category_index(self, prize_category_id: int, index: int):
        self.execute(
            'UPDATE `prize_category` SET `index` = ? WHERE `id` = ?',
            (index, prize_category_id),
        )

    def delete_stored_prize_category(self, prize_category_id: int):
        self.execute(
            'DELETE FROM `prize_category` WHERE `id` = ?;', (prize_category_id,)
        )

    # ---------------------------------------------------------------------------------
    # StoredPrizeCriterion
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_prize_criterion(
        cls, row: dict[str, Any]
    ) -> StoredPrizeCriterion:
        return StoredPrizeCriterion(
            id=row['id'],
            prize_category_id=row['prize_category_id'],
            type=row['type'],
            options=cls.load_json_from_database_field(row['options']),
        )

    def load_prize_category_stored_prize_criteria(
        self, prize_category_id: int
    ) -> list[StoredPrizeCriterion]:
        self.execute(
            'SELECT * FROM `prize_criterion` WHERE `prize_category_id` = ?',
            (prize_category_id,),
        )
        return [self._row_to_stored_prize_criterion(row) for row in self.fetchall()]

    def add_stored_prize_criterion(
        self,
        stored_prize_criterion: StoredPrizeCriterion,
    ) -> int:
        fields = self._get_fields_dict(
            stored_prize_criterion, ['prize_category_id', 'type']
        ) | {
            'options': self.dump_to_json_database_field(stored_prize_criterion.options)
        }
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `prize_criterion`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (prize_criterion_id := self._last_inserted_id()):
            raise RuntimeError('Prize criterion insertion failed')
        return prize_criterion_id

    def update_stored_prize_criterion(
        self,
        stored_prize_criterion: StoredPrizeCriterion,
    ):
        fields = self._get_fields_dict(
            stored_prize_criterion, ['prize_category_id', 'type']
        ) | {
            'options': self.dump_to_json_database_field(stored_prize_criterion.options)
        }
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_prize_criterion.id is not None
        self.execute(
            f'UPDATE `prize_criterion` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_prize_criterion.id,),
        )

    def delete_stored_prize_criterion(self, prize_criterion_id: int):
        self.execute(
            'DELETE FROM `prize_criterion` WHERE `id` = ?;', (prize_criterion_id,)
        )

    # ---------------------------------------------------------------------------------
    # StoredPrize
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_prize(cls, row: dict[str, Any]) -> StoredPrize:
        return StoredPrize(
            id=row['id'],
            prize_category_id=row['prize_category_id'],
            type=row['type'],
            value=row['value'],
            description=row['description'],
            complementary_value=row['complementary_value'],
        )

    def load_prize_category_stored_prizes(
        self, prize_category_id: int
    ) -> list[StoredPrize]:
        self.execute(
            'SELECT * FROM `prize` WHERE `prize_category_id` = ?',
            (prize_category_id,),
        )
        return [self._row_to_stored_prize(row) for row in self.fetchall()]

    def add_stored_prize(
        self,
        stored_prize: StoredPrize,
    ) -> int:
        fields = self._get_fields_dict(
            stored_prize,
            [
                'prize_category_id',
                'type',
                'value',
                'description',
                'complementary_value',
            ],
        )
        fields_str = ', '.join(f'`{f}`' for f in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `prize`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        if not (prize_id := self._last_inserted_id()):
            raise RuntimeError('Prize entry insertion failed')
        return prize_id

    def update_stored_prize(
        self,
        stored_prize: StoredPrize,
    ):
        fields = self._get_fields_dict(
            stored_prize,
            [
                'prize_category_id',
                'type',
                'value',
                'description',
                'complementary_value',
            ],
        )
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_prize.id is not None
        self.execute(
            f'UPDATE `prize` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_prize.id,),
        )

    def delete_stored_prize(self, prize_id: int):
        self.execute('DELETE FROM `prize` WHERE `id` = ?;', (prize_id,))

    # ---------------------------------------------------------------------------------
    # StoredAccount
    # ---------------------------------------------------------------------------------

    @classmethod
    def _row_to_stored_account(cls, row: dict[str, Any]) -> StoredAccount:
        return StoredAccount(
            id=row['id'],
            active=cls.load_bool_from_database_field(row['active']),
            first_name=row['first_name'],
            last_name=row['last_name'],
            fide_id=row['fide_id'],
            fide_arbiter_title=row['fide_arbiter_title'],
            password_hash=row['password_hash'],
            mail=row['mail'],
            phone=row['phone'],
            plugin_data=cls.load_json_from_database_field(row['plugin_data'], {}),
        )

    def get_stored_account(self, account_id: int) -> StoredAccount | None:
        self.execute(
            'SELECT * FROM `account` WHERE `id` = ?',
            (account_id,),
        )
        row: dict[str, Any]
        if row := self.fetchone():
            return self._row_to_stored_account(row)
        return None

    def load_stored_accounts(self) -> list[StoredAccount]:
        self.execute('SELECT * FROM `account`')
        stored_accounts = [self._row_to_stored_account(row) for row in self.fetchall()]
        if not stored_accounts:
            return []

        self.execute(
            'SELECT * FROM `account_permission` '
            'ORDER BY `account_id`, `access_level`, `tournament_id`'
        )
        permission_ids: dict[tuple[int, str], list[int] | None] = {}
        for row in self.fetchall():
            key = (row['account_id'], row['access_level'])
            if row['tournament_id'] is None:
                permission_ids[key] = None
            elif (tournament_ids := permission_ids.setdefault(key, [])) is not None:
                tournament_ids.append(row['tournament_id'])
        permissions_by_account: dict[int, list[StoredPermission]] = defaultdict(list)
        for (account_id, access_level), tournament_ids in permission_ids.items():
            permissions_by_account[account_id].append(
                StoredPermission(account_id, access_level, tournament_ids)
            )

        self.execute(
            'SELECT * FROM `account_role` '
            'ORDER BY `account_id`, `role`, `tournament_id`'
        )
        role_ids: dict[tuple[int, str], list[int] | None] = {}
        for row in self.fetchall():
            key = (row['account_id'], row['role'])
            if row['tournament_id'] is None:
                role_ids[key] = None
            elif (tournament_ids := role_ids.setdefault(key, [])) is not None:
                tournament_ids.append(row['tournament_id'])
        roles_by_account: dict[int, list[StoredRole]] = defaultdict(list)
        for (account_id, role), tournament_ids in role_ids.items():
            roles_by_account[account_id].append(
                StoredRole(account_id, role, tournament_ids)
            )

        for stored_account in stored_accounts:
            assert stored_account.id is not None
            stored_account.stored_permissions = permissions_by_account.get(
                stored_account.id, []
            )
            stored_account.stored_roles = roles_by_account.get(stored_account.id, [])
        return stored_accounts

    def add_stored_account(self, stored_account: StoredAccount) -> int:
        fields = self._get_fields_dict(
            stored_account,
            [
                'active',
                'first_name',
                'last_name',
                'fide_id',
                'fide_arbiter_title',
                'password_hash',
                'mail',
                'phone',
            ],
        ) | {
            'plugin_data': self.dump_to_json_database_field(
                stored_account.plugin_data, {}
            ),
        }
        if stored_account.id:
            fields |= {'id': stored_account.id}
        fields_str = ', '.join(f'`{field}`' for field in fields)
        values_str = ', '.join(['?'] * len(fields))
        self.execute(
            f'INSERT INTO `account`({fields_str}) VALUES ({values_str})',
            tuple(fields.values()),
        )
        account_id: int | None = self._last_inserted_id()
        if account_id is None:
            raise RuntimeError('Account insertion failed')
        return account_id

    def update_stored_account(self, stored_account: StoredAccount) -> StoredAccount:
        fields = self._get_fields_dict(
            stored_account,
            [
                'active',
                'first_name',
                'last_name',
                'fide_id',
                'fide_arbiter_title',
                'password_hash',
                'mail',
                'phone',
            ],
        ) | {
            'plugin_data': self.dump_to_json_database_field(
                stored_account.plugin_data, {}
            ),
        }
        field_sets = ', '.join(f'`{f}` = ?' for f in fields)
        assert stored_account.id is not None
        self.execute(
            f'UPDATE `account` SET {field_sets} WHERE `id` = ?',
            tuple(fields.values()) + (stored_account.id,),
        )
        fetched_stored_account = self.get_stored_account(account_id=stored_account.id)
        if fetched_stored_account is None:
            raise RuntimeError('Account write failed')
        return fetched_stored_account

    def delete_stored_account(self, account_id: int):
        self.execute('DELETE FROM `account` WHERE `id` = ?;', (account_id,))

    # ---------------------------------------------------------------------------------
    # StoredRole
    # ---------------------------------------------------------------------------------

    def load_account_stored_roles(self, account_id: int) -> list[StoredRole]:
        self.execute(
            'SELECT * from `account_role` WHERE `account_id` = ?',
            (account_id,),
        )
        tournament_ids_by_role: dict[str, list[int]] = defaultdict(list)
        for row in self.fetchall():
            role = row['role']
            tournament_id = row['tournament_id']
            tournament_ids_by_role[role].append(tournament_id)
        return [
            StoredRole(account_id, role, tournament_ids or None)
            for role, tournament_ids in tournament_ids_by_role.items()
        ]

    def delete_stored_roles(
        self,
        account_id: int | None = None,
        role: str | None = None,
        tournament_ids: list[int] | None = None,
    ) -> None:
        """Delete stored roles, optionally filtered by account, role, and/or tournaments."""
        conditions: list[str] = []
        params: list = []

        if account_id is not None:
            conditions.append('`account_id` = ?')
            params.append(account_id)

        if role is not None:
            conditions.append('`role` = ?')
            params.append(role)

        if tournament_ids:
            placeholders = ', '.join('?' for _ in tournament_ids)
            conditions.append(f'`tournament_id` IN ({placeholders})')
            params.extend(tournament_ids)

        # Don’t allow deleting everything by mistake
        if not conditions:
            raise ValueError('At least one condition must be provided to delete roles.')

        sql = f'DELETE FROM `account_role` WHERE {" AND ".join(conditions)}'
        self.execute(sql, tuple(params))

    def add_stored_roles(
        self,
        account_id: int,
        role: str,
        tournament_ids: Sequence[int] | None = None,
    ) -> None:
        # For roles that aren't bound to a tournament
        ids: Sequence[int | None]
        if tournament_ids is None:
            ids = [None]
        else:
            ids = tournament_ids

        rows = [(account_id, role, tid) for tid in ids]
        self.executemany(
            'INSERT INTO `account_role` (`account_id`, `role`, `tournament_id`) '
            'VALUES (?, ?, ?)',
            rows,
        )

    # ---------------------------------------------------------------------------------
    # StoredPermission
    # ---------------------------------------------------------------------------------

    def load_account_stored_permissions(
        self, account_id: int
    ) -> list[StoredPermission]:
        self.execute(
            'SELECT * from `account_permission` WHERE `account_id` = ?',
            (account_id,),
        )
        tournament_ids_by_access_level: dict[str, list[int]] = defaultdict(list)
        for row in self.fetchall():
            access_level = row['access_level']
            tournament_id = row['tournament_id']
            if not tournament_id:
                tournament_ids_by_access_level[access_level] = []
                continue
            tournament_ids_by_access_level[access_level].append(tournament_id)
        return [
            StoredPermission(account_id, access_level, tournament_ids or None)
            for access_level, tournament_ids in tournament_ids_by_access_level.items()
        ]

    def delete_stored_permission(self, stored_permission: StoredPermission):
        self.execute(
            'DELETE FROM `account_permission` '
            'WHERE `account_id` = ? AND `access_level` = ?',
            (stored_permission.account_id, stored_permission.access_level),
        )

    def add_stored_permission(self, stored_permission: StoredPermission):
        inserted_values: list[int] | list[None]
        if stored_permission.tournament_ids:
            inserted_values = stored_permission.tournament_ids
        else:
            inserted_values = [None]
        for tournament_id in inserted_values:
            fields = {
                'account_id': stored_permission.account_id,
                'access_level': stored_permission.access_level,
                'tournament_id': tournament_id,
            }
            fields_str = ', '.join(f'`{f}`' for f in fields)
            values_str = ', '.join(['?'] * len(fields))
            self.execute(
                f'INSERT INTO `account_permission`({fields_str}) VALUES ({values_str})',
                tuple(fields.values()),
            )
