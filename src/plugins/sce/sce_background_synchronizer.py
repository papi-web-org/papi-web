import time
from datetime import datetime, timedelta
from threading import Timer

from common.logger import get_logger
from common.i18n import set_locale
from common.network import NetworkMonitor
from common.sharly_chess_config import SharlyChessConfig
from data.event import Event
from data.loader import EventLoader
from plugins.sce import SCE_SYNC_DELAY, SCE_CHECK_IN_OPEN_SYNC_DELAY
from plugins.sce.sce_session import SCESession
from plugins.sce.sce_sync_status import (
    SCESyncStatus,
    NetworkFailureSCESyncStatus,
    UnexpectedFailureSCESyncStatus,
    AuthFailureSCESyncStatus,
)
from plugins.sce.utils import SCEUtils
from web.channels import channels_plugin

logger = get_logger()

_ONGOING_EVENTS_UNIQ_IDS: set[str] = set()
_TIMEOUT_THREADS: dict[str, Timer] = {}


def is_sync_ongoing(event_uniq_id: str) -> bool:
    """Return True if a background sync is currently running for this event."""
    return event_uniq_id in _ONGOING_EVENTS_UNIQ_IDS


def is_sync_scheduled(event_uniq_id: str) -> bool:
    thread = _TIMEOUT_THREADS.get(event_uniq_id)
    return bool(thread and thread.is_alive())


def remove_scheduled_sync(event_uniq_id: str):
    thread = _TIMEOUT_THREADS.get(event_uniq_id)
    if thread and thread.is_alive():
        thread.cancel()


def _publish_upload_event(start: bool = False):
    if channels_plugin:
        channels_plugin.publish(
            {'event': f'upload-event{"-start" if start else ""}', 'data': ''}, ['ws']
        )


def _exit_with_status(event: Event, status: SCESyncStatus):
    plugin_data = SCEUtils.get_event_plugin_data(event)
    plugin_data.last_sync_attempt_status = status.id
    now = datetime.now()
    plugin_data.last_sync_attempt_at = now
    if status.update_last_sync_at:
        plugin_data.last_sync_at = now
    SCEUtils.update_event_plugin_data(event, plugin_data)


def sync_event(event_uniq_id: str):
    """Sync an event's player data with the SCE platform. Runs in a background thread."""
    set_locale(SharlyChessConfig().locale)

    _ONGOING_EVENTS_UNIQ_IDS.add(event_uniq_id)
    _publish_upload_event(start=True)
    # NOTE (Molrn) Ensures a minimum time for the thread
    # This prevents flashing and situations where both requests
    # triggered by the `upload-event` web socket are treated as one
    time.sleep(0.5)

    event: Event | None = None
    try:
        loader = EventLoader()
        if event_uniq_id not in loader.event_uniq_ids:
            return
        event = loader.load_event(event_uniq_id)
        if not NetworkMonitor.connected():
            _exit_with_status(event, NetworkFailureSCESyncStatus())
            return
        status = SCESession(event).sync_event()
        _exit_with_status(event, status)
    except Exception as e:
        logger.exception(e)
        if event:
            status: SCESyncStatus = UnexpectedFailureSCESyncStatus()
            if not SCEUtils.get_event_plugin_data(event).tokens:
                status = AuthFailureSCESyncStatus()
            _exit_with_status(event, status)
    finally:
        _ONGOING_EVENTS_UNIQ_IDS.discard(event_uniq_id)
        if event:
            plugin_data = SCEUtils.get_event_plugin_data(event)
            if plugin_data.auto_player_sync:
                schedule_sync(event)
        _publish_upload_event()


def schedule_sync(event: Event, force: bool = False):
    """Launch a background thread to upload this tournament's results."""
    if event.uniq_id in _ONGOING_EVENTS_UNIQ_IDS:
        return
    plugin_data = SCEUtils.get_event_plugin_data(event)
    last_attempt_at = plugin_data.last_sync_attempt_at
    wait_time = 0.1
    sync_delay = SCE_SYNC_DELAY
    for tournament in event.tournaments:
        tpd = SCEUtils.get_tournament_plugin_data(tournament)
        if tpd.id and tpd.check_in_open:
            sync_delay = SCE_CHECK_IN_OPEN_SYNC_DELAY
            break
    if (
        not force
        and last_attempt_at
        and datetime.now() < last_attempt_at + timedelta(minutes=sync_delay)
    ):
        elapsed = (datetime.now() - last_attempt_at).total_seconds()
        wait_time = max(sync_delay * 60 - elapsed, 0.1)

    remove_scheduled_sync(event.uniq_id)
    timer = Timer(
        wait_time,
        sync_event,
        args=(event.uniq_id,),
    )
    _TIMEOUT_THREADS[event.uniq_id] = timer
    timer.start()
