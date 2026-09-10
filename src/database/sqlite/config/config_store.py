"""
All the classes of this module are basic data classes stored in the config database.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StoredPlayerCategorySet:
    id: int | None
    name: str
    categories: list[str]


@dataclass
class StoredTieBreakSet:
    id: int | None
    name: str
    pairing_system_id: str
    stored_tie_breaks: list[dict[str, Any]]


@dataclass
class StoredTag:
    """A tag that events can be labelled with. Tags are global to the
    installation; events reference them by id."""

    id: int | None
    name: str
    color: str
    index: int = 0


@dataclass
class StoredConfig:
    force_edit: bool
    console_log_level: int | None
    console_color: bool
    console_show_date: bool
    console_show_level: bool
    experimental: bool
    launch_browser: bool
    check_beta_versions: bool
    last_notified_version: str | None
    date_formatter: str
    snapshot_enabled: bool
    snapshot_keep_milestones: int
    snapshot_keep_auto: int
    snapshot_max_total_mb: int
    snapshot_max_age_days: int
    #: Where the snapshots are written, None for the default directory.
    snapshot_dir: str | None = None
    federation: str | None = None
    locale: str | None = None
    stored_player_category_sets: list[StoredPlayerCategorySet] = field(
        default_factory=list[StoredPlayerCategorySet]
    )
    stored_tie_break_sets: list[StoredTieBreakSet] = field(
        default_factory=list[StoredTieBreakSet]
    )
    stored_tags: list[StoredTag] = field(default_factory=list[StoredTag])
    errors: dict[str, str] = field(default_factory=dict[str, str])


@dataclass
class StoredPlugin:
    name: str
    is_enabled: bool
    #: Whether new events enable the plugin, None for the default it declares.
    default_event_is_enabled: bool | None = None
    plugin_data: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=dict[str, dict[str, dict[str, Any]]]
    )


@dataclass
class StoredLocalSourceDatabase:
    name: str
    outdate_delay: str
    outdate_action: str
    updated_at: float | None = None
    errors: dict[str, str] = field(default_factory=dict[str, str])
