import json
from datetime import datetime
from functools import partial
from logging import Logger
from typing import Any

from common import SharlyChessException
from common.logger import get_logger
from common.network import NetworkMonitor
from data.event import Event
from data.player import Player, TournamentPlayer
from data.tournament import Tournament
from database.sqlite.event.event_database import EventDatabase
from database.sqlite.event.event_store import StoredTournament
from plugins.sce import PLUGIN_NAME, SCE_BASE_URL
from plugins.sce.sce_data import (
    SCEEventPluginData,
    SCETournamentPluginData,
    SCEPlayerPluginData,
)
from plugins.sce.sce_event_status import (
    SCEEventStatus,
    NoInternetSCEEventStatus,
    InvalidRefreshTokenSCEEventStatus,
    NotConnectedSCEEventStatus,
)
from plugins.sce.sce_managers import (
    SCEEventStatusManager,
    SCESyncStatusManager,
    SCETournamentFailureStatusManager,
)
from plugins.sce.sce_sync_status import (
    SCESyncStatus,
    NeverSyncedSCESyncStatus,
    AuthFailureSCESyncStatus,
)
from plugins.sce.sce_tournament_status import (
    SCETournamentStatus,
    ModifiedSCETournamentStatus,
    PendingSCETournamentStatus,
    NotStartedSCETournamentStatus,
    NeverUploadedSCETournamentStatus,
    OngoingSCETournamentStatus,
    UpToDateSCETournamentStatus,
    AuthFailureSCETournamentStatus,
)
from plugins.utils import PluginUtils
from utils import Utils
from web.urls import build_get_url

logger: Logger = get_logger()

get_data = partial(PluginUtils.get_plugin_data, PLUGIN_NAME)


class SCEUtils:
    @staticmethod
    def get_event_plugin_data(event: Event) -> SCEEventPluginData:
        plugin_data = event.plugin_data[PLUGIN_NAME]
        assert isinstance(plugin_data, SCEEventPluginData)
        return plugin_data

    @staticmethod
    def get_tournament_plugin_data(tournament: Tournament) -> SCETournamentPluginData:
        plugin_data = tournament.plugin_data[PLUGIN_NAME]
        assert isinstance(plugin_data, SCETournamentPluginData)
        return plugin_data

    @staticmethod
    def get_player_plugin_data(player: Player) -> SCEPlayerPluginData:
        plugin_data = player.plugin_data[PLUGIN_NAME]
        assert isinstance(plugin_data, SCEPlayerPluginData)
        return plugin_data

    @staticmethod
    def update_event_plugin_data(
        event: Event,
        plugin_data: SCEEventPluginData,
        write: bool = True,
        write_stored_object: bool = False,
    ):
        event.stored_event.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()
        event.plugin_data[PLUGIN_NAME] = plugin_data
        if write:
            with EventDatabase(event.uniq_id, True) as database:
                if write_stored_object:
                    database.update_stored_event(event.stored_event)
                else:
                    database.execute(
                        "UPDATE info SET plugin_data = json_set(plugin_data,'$.sce', json(?))",
                        (json.dumps(plugin_data.to_stored_value()),),
                    )

    @classmethod
    def update_tournament_plugin_data(
        cls,
        tournament: Tournament,
        plugin_data: SCETournamentPluginData,
        write: bool = True,
        write_stored_object: bool = False,
    ):
        tournament.stored_tournament.plugin_data[PLUGIN_NAME] = (
            plugin_data.to_stored_value()
        )
        tournament.plugin_data[PLUGIN_NAME] = plugin_data
        if write:
            with EventDatabase(tournament.event.uniq_id, write=True) as database:
                if write_stored_object:
                    database.update_stored_tournament(tournament.stored_tournament)
                else:
                    cls.update_tournament_plugin_data_from_database(
                        tournament, plugin_data, database
                    )

    @classmethod
    def update_tournament_plugin_data_from_database(
        cls,
        tournament: Tournament,
        plugin_data: SCETournamentPluginData,
        database: EventDatabase,
    ):
        database.execute(
            'UPDATE tournament SET plugin_data = '
            "json_set(plugin_data,'$.sce', json(?)) WHERE id = ?",
            (json.dumps(plugin_data.to_stored_value()), tournament.id),
        )

    @classmethod
    def update_player_plugin_data(
        cls,
        player: Player,
        plugin_data: SCEPlayerPluginData,
        write: bool = True,
        write_stored_object: bool = False,
    ):
        player.stored_player.plugin_data[PLUGIN_NAME] = plugin_data.to_stored_value()
        player.plugin_data[PLUGIN_NAME] = plugin_data
        if write:
            with EventDatabase(player.event.uniq_id, write=True) as database:
                if write_stored_object:
                    database.update_stored_player(player.stored_player)
                else:
                    cls.update_player_plugin_data_from_database(
                        player, plugin_data, database
                    )

    @classmethod
    def update_player_plugin_data_from_database(
        cls,
        player: Player,
        plugin_data: SCEPlayerPluginData,
        database: EventDatabase,
    ):
        database.execute(
            'UPDATE player SET plugin_data = '
            "json_set(plugin_data,'$.sce', json(?)) WHERE id = ?",
            (json.dumps(plugin_data.to_stored_value()), player.id),
        )

    @classmethod
    def get_event_sce_tournaments(cls, event: Event) -> list[Tournament]:
        return [
            tournament
            for tournament in event.sorted_tournaments
            if cls.get_tournament_plugin_data(tournament).id
        ]

    @classmethod
    def get_tournament_by_sce_id(cls, event: Event, sce_id: str) -> Tournament:
        for tournament in event.tournaments:
            if cls.get_tournament_plugin_data(tournament).id == sce_id:
                return tournament
        raise ValueError('Tournament not found')

    @classmethod
    def get_optional_tournament_by_sce_id(
        cls, event: Event, sce_id: str
    ) -> Tournament | None:
        try:
            return cls.get_tournament_by_sce_id(event, sce_id)
        except ValueError:
            return None

    @staticmethod
    def merge_dicts(
        dict1: dict[str, Any],
        dict2: dict[str, Any],
        ref_dict: dict[str, Any],
        avoid_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Merge 2 dicts with the same keys into one, according to the values of a ref dict.
        In case of inequality between 2 fields, choose the one that is different from the ref.
        If both are different from the ref, raise a SharlyChessException as the dicts can't be merged."""
        if not avoid_keys:
            avoid_keys = []
        merged_dict: dict[str, Any] = {}
        for key, ref_value in ref_dict.items():
            if key in avoid_keys:
                continue
            value1 = dict1[key]
            value2 = dict2[key]
            if value1 == value2:
                merged_dict[key] = value1
            elif value1 == ref_value:
                merged_dict[key] = value2
            elif value2 == ref_value:
                merged_dict[key] = value1
            else:
                raise SharlyChessException(
                    f'Field [{key}] is not mergeable '
                    f'({value1=}, {value2=}, {ref_value=})'
                )
        return merged_dict

    @classmethod
    def resolve_tournament_upload_statuses(
        cls, tournament: Tournament
    ) -> list[SCETournamentStatus]:
        from plugins.sce.sce_background_uploader import (
            is_upload_ongoing,
            is_upload_queued,
            is_upload_scheduled,
        )

        plugin_data = cls.get_tournament_plugin_data(tournament)
        if not tournament.started:
            return [NotStartedSCETournamentStatus()]

        statuses: list[SCETournamentStatus] = []

        # Last upload failure
        if plugin_data.upload_failure_id:
            status = SCETournamentFailureStatusManager().get_object(
                plugin_data.upload_failure_id
            )
            statuses.append(status)

        is_modified = cls.tournament_modified_since_last_upload(tournament)
        # Current data status
        if not plugin_data.last_upload_at:
            statuses.append(NeverUploadedSCETournamentStatus())
        elif is_modified:
            statuses.append(ModifiedSCETournamentStatus())
        else:
            statuses.append(UpToDateSCETournamentStatus())

        # Next upload status
        if is_upload_ongoing(tournament):
            statuses.append(OngoingSCETournamentStatus())
        elif is_upload_queued(tournament) or (
            is_upload_scheduled(tournament) and is_modified
        ):
            statuses.append(PendingSCETournamentStatus())
        return statuses

    @classmethod
    def resolve_event_status(cls, event: Event) -> SCEEventStatus:
        plugin_data = cls.get_event_plugin_data(event)
        if not plugin_data.id or not plugin_data.status:
            return NotConnectedSCEEventStatus()
        if not NetworkMonitor.connected():
            return NoInternetSCEEventStatus()
        if not plugin_data.tokens:
            return InvalidRefreshTokenSCEEventStatus()

        return SCEEventStatusManager().get_object(plugin_data.status)

    @classmethod
    def resolve_last_sync_status(cls, event: Event) -> SCESyncStatus:
        plugin_data = cls.get_event_plugin_data(event)
        try:
            return SCESyncStatusManager().get_object(
                plugin_data.last_sync_attempt_status or ''
            )
        except KeyError:
            return NeverSyncedSCESyncStatus()

    @classmethod
    def clear_auth_error_statuses(cls, event: Event) -> None:
        """Clear the error states left by a lost authorization once the event has
        been re-authenticated, so the data transfer error badge disappears."""
        event_plugin_data = cls.get_event_plugin_data(event)
        if (
            event_plugin_data.last_sync_attempt_status
            == AuthFailureSCESyncStatus.static_id()
        ):
            event_plugin_data.last_sync_attempt_status = None
            cls.update_event_plugin_data(event, event_plugin_data)
        for tournament in event.tournaments:
            tournament_plugin_data = cls.get_tournament_plugin_data(tournament)
            if (
                tournament_plugin_data.upload_failure_id
                == AuthFailureSCETournamentStatus.static_id()
            ):
                tournament_plugin_data.upload_failure_id = None
                cls.update_tournament_plugin_data(tournament, tournament_plugin_data)

    @classmethod
    def resolve_tournament_auto_upload(cls, tournament: Tournament) -> bool:
        if not cls.get_event_plugin_data(tournament.event).auto_upload:
            return False
        return cls.get_tournament_plugin_data(tournament).auto_upload

    @classmethod
    def tournament_modified_since_last_upload(
        cls, tournament: Tournament | StoredTournament
    ) -> bool:
        last_upload = cls.get_tournament_last_upload(tournament)
        return not last_upload or Utils.tournament_results_modified_since(
            tournament, last_upload
        )

    @classmethod
    def get_tournament_last_upload(
        cls, tournament: Tournament | StoredTournament
    ) -> datetime | None:
        if isinstance(tournament, Tournament):
            plugin_data = cls.get_tournament_plugin_data(tournament)
        else:
            plugin_data = SCETournamentPluginData.from_stored_value(
                tournament.plugin_data.get(PLUGIN_NAME, {})
            )
        return plugin_data.last_upload_at

    @classmethod
    def event_public_url(cls, event: Event) -> str:
        slug = cls.get_event_plugin_data(event).slug
        return build_get_url(SCE_BASE_URL, f'/events/{slug}')

    @classmethod
    def event_private_url(cls, event: Event) -> str:
        pd = cls.get_event_plugin_data(event)
        return build_get_url(
            SCE_BASE_URL, f'/organizer/{pd.organiser_slug}/events/{pd.id}'
        )

    @classmethod
    def tournament_public_url(cls, tournament: Tournament) -> str:
        slug = cls.get_event_plugin_data(tournament.event).slug
        tournament_id = cls.get_tournament_plugin_data(tournament).id
        return build_get_url(
            SCE_BASE_URL, f'/events/{slug}/tournaments/{tournament_id}'
        )

    @classmethod
    def tournament_private_url(cls, tournament: Tournament) -> str:
        pd = cls.get_event_plugin_data(tournament.event)
        tournament_id = cls.get_tournament_plugin_data(tournament).id
        return build_get_url(
            SCE_BASE_URL,
            f'/organizer/{pd.organiser_slug}/events/'
            f'{pd.id}/tournaments/{tournament_id}',
        )

    @classmethod
    def get_local_player_duplicates(
        cls, tournament: Tournament
    ) -> list[TournamentPlayer]:
        return [
            player
            for player in tournament.tournament_players
            if SCEUtils.get_player_plugin_data(player).is_duplicated
        ]
