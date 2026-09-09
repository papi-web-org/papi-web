from dataclasses import dataclass, field
from html import escape
from datetime import date
from functools import cached_property
from typing import TYPE_CHECKING

from common.i18n import _, ngettext
from database.sqlite.event.event_store import BaseStoredEvent
from plugins.manager import plugin_manager
from plugins.utils import Plugin
from utils.enum import EventType

if TYPE_CHECKING:
    from data.tag import Tag


@dataclass
class EventMetadata(BaseStoredEvent):
    """Class containing the metadata of an event required
    for display on the event selection pages."""

    start_date: date = field(default_factory=date.today)
    stop_date: date = field(default_factory=date.today)
    tournament_count: int = 0
    player_count: int = 0
    team_count: int = 0
    timer_count: int = 0
    screen_count: int = 0
    family_count: int = 0
    rotator_count: int = 0
    # False for a placeholder standing in for an event whose file exists but
    # could not be opened (locked, file sync, permissions…). Such an event is
    # listed but not accessible, similarly to an event with a disabled plugin.
    accessible: bool = True

    @property
    def is_team_event(self) -> bool:
        return self.event_type == EventType.TEAM

    @property
    def tags(self) -> list['Tag']:
        """The tags of the event; unknown ids are ignored (see data.tag)."""
        from common.sharly_chess_config import SharlyChessConfig

        return SharlyChessConfig().resolve_tags(self.tag_ids)

    @property
    def plugins(self) -> list[Plugin]:
        return [
            plugin_manager.plugins_by_id[plugin_id]
            for plugin_id in self.enabled_plugins
        ]

    @cached_property
    def are_all_plugins_enabled(self) -> bool:
        return all(plugin.is_enabled for plugin in self.plugins)

    @property
    def uninstalled_plugins(self) -> list[Plugin]:
        """The plugins the event uses that are not installed, which make it
        inaccessible until they are."""
        return [plugin for plugin in self.plugins if not plugin.is_enabled]

    @property
    def inaccessible_tooltip_message(self) -> str:
        """Why the event can not be opened."""
        if not self.accessible:
            return _(
                'This event exists on the server but could not be opened. It '
                'may be locked by another program, by file synchronisation '
                '(OneDrive, Google Drive, DropBox, etc.) or by antivirus '
                'software.'
            )
        plugins = self.uninstalled_plugins
        heading = ngettext(
            'This event needs this plugin, which is not installed:',
            'This event needs these plugins, which are not installed:',
            len(plugins),
        )
        footer = ngettext(
            'Install it from the Plugins section to open the event.',
            'Install them from the Plugins section to open the event.',
            len(plugins),
        )
        names = ''.join(f'<li>{escape(plugin.name)}</li>' for plugin in plugins)
        # Tooltips centre their text, which a list is not read well in.
        return (
            f'<div class="text-start">{heading}'
            f'<ul class="mb-1 ps-3">{names}</ul>'
            f'{footer}</div>'
        )

    @property
    def plugins_tooltip_message(self) -> str:
        tooltip_message = '<div class="mt-1"></div>'
        for plugin in self.plugins:
            classes = 'text-center mb-1'
            styles = 'line-height: 1.1;'
            if not plugin.is_enabled:
                classes += ' tooltip-danger fw-bold'
                content = _('{plugin} (disabled)').format(plugin=plugin.name)
            else:
                content = plugin.name
            tooltip_message += (
                f'<div class="{classes}" style="{styles}">{content}</div>'
            )
        return tooltip_message
