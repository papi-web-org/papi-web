from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, NamedTuple, Self


from common import TEST_ENV
from packaging.version import Version

from utils.entity import IdentifiableEntity
from utils.enum import EventType
from plugins import PLUGINS_DIR

if TYPE_CHECKING:
    from data.event import Event
    from data.event_metadata import EventMetadata
    from database.sqlite.event.event_database import EventDatabase
    from database.sqlite.event.event_store import (
        StoredEvent,
        StoredTournament,
        StoredPlayer,
    )
    from plugins.migration import PluginMigrationManager
    from web.controllers.base_controller import BaseController


class PluginUtils:
    @staticmethod
    def get_plugin_data(
        plugin_id: str,
        plugin_data: dict[str, dict] | None,
        field: str,
        default: Any = None,
    ):
        return (plugin_data or {}).get(plugin_id, {}).get(field, default)

    @staticmethod
    def _insert_on_condition[T](
        source_list: list[T],
        element: T,
        condition: Callable[[T], bool],
        after: bool = True,
    ):
        """Inserts *element* into the list *source_list*. The insert in made at
        the position of the first element matching *condition*.
        If *after* is True, element is inserted after the matched element,
        otherwise it is inserted before.
        """
        for index, match_element in enumerate(source_list):
            if condition(match_element):
                source_list.insert(index + after, element)
                return

    @classmethod
    def insert_on_equals[T](
        cls,
        source_list: list[T],
        element: T,
        match_element: T,
        after: bool = True,
    ):
        """Wrapper on insert_on_condition where the condition
        is an element being equal to *match_element*"""
        cls._insert_on_condition(
            source_list, element, lambda elem: elem == match_element, after
        )

    @classmethod
    def insert_on_isinstance[T](
        cls,
        source_list: list[T],
        element: T,
        match_type: type[T],
        after: bool = True,
    ):
        """Wrapper on insert_on_condition where the condition
        is an element being an instance of *insert_type*"""
        cls._insert_on_condition(
            source_list, element, lambda elem: isinstance(elem, match_type), after
        )

    @classmethod
    def insert_on_attr_equals[T](
        cls,
        source_list: list[T],
        element: T,
        attr_name: str,
        attr_value: Any,
        after: bool = True,
    ):
        """Wrapper on insert_on_condition where the condition
        is an element being an attribute of the element matching a value."""
        cls._insert_on_condition(
            source_list,
            element,
            lambda elem: getattr(elem, attr_name) == attr_value,
            after,
        )

    @staticmethod
    def _replace_on_condition[T](
        source_list: list[T],
        element: T,
        condition: Callable[[T], bool],
    ):
        """Replace with *element* first element of the
        list *source_list* matching the condition *condition*."""
        for index, match_element in enumerate(source_list):
            if condition(match_element):
                source_list[index] = element
                return

    @classmethod
    def replace_on_equals[T](
        cls,
        source_list: list[T],
        element: T,
        match_element: T,
    ):
        cls._replace_on_condition(
            source_list, element, lambda elem: elem == match_element
        )

    @classmethod
    def replace_on_isinstance[T](
        cls,
        source_list: list[T],
        element: T,
        match_type: type[T],
    ):
        cls._replace_on_condition(
            source_list, element, lambda elem: isinstance(elem, match_type)
        )


class PluginContext:
    def __init__(self, plugin: 'Plugin'):
        from database.sqlite.config.config_database import ConfigDatabase
        from database.sqlite.config.config_store import StoredPlugin

        self.stored_plugin: StoredPlugin
        with ConfigDatabase() as database:
            stored_plugin = database.load_stored_plugin(plugin.id)
        if not stored_plugin:
            with ConfigDatabase(True) as database:
                stored_plugin = StoredPlugin(
                    name=plugin.id,
                    is_enabled=plugin.default_is_enabled or TEST_ENV,
                )
                database.insert_stored_plugin(stored_plugin)
        self.stored_plugin = stored_plugin

    def get_raw_plugin_data(self) -> dict[str, Any]:
        return self.stored_plugin.plugin_data or {}


class PluginData(ABC):
    @classmethod
    @abstractmethod
    def from_stored_value(cls, stored_value: dict[str, Any]) -> Self:
        """Initialize an object from its stored value."""

    @abstractmethod
    def to_stored_value(self) -> dict[str, Any]:
        """The value to store in the database."""

    @classmethod
    @abstractmethod
    def from_form_data(
        cls,
        data: dict[str, str],
        previous_object: Self | None = None,
        action: str | None = None,
    ) -> Self:
        """Initialize an object from form data."""

    @abstractmethod
    def to_form_data(self, action: str | None = None) -> dict[str, str]:
        """The values to use in a form."""


class AccountPluginData(PluginData, ABC):
    @classmethod
    @abstractmethod
    def from_stored_player(cls, stored_player: 'StoredPlayer') -> Self:
        """Initialize from a stored player (used for player search)."""


class Plugin[PD: PluginData](IdentifiableEntity, ABC):
    data_class: type[PD] | None = None

    def __init__(self):
        self.context: PluginContext = PluginContext(self)

    @property
    def dependencies(self) -> list[type['Plugin']]:
        """Types of the plugins that need to be enabled for this plugin to be enabled."""
        return []

    @property
    @abstractmethod
    def description(self) -> str:
        """Briefly describes the features of the plugin."""

    @property
    def doc_markdown(self) -> str | None:
        """Markdown detailing the features of the plugin, displayed on its page.
        None to only display *description*."""
        return None

    @property
    def doc_html(self) -> str | None:
        """*doc_markdown* rendered as HTML."""
        from utils.markdown import markdown_to_html

        markdown = self.doc_markdown
        return markdown_to_html(markdown) if markdown else None

    @property
    def doc_slug(self) -> str | None:
        """Slug of the page of the plugin on the documentation website,
        None when the plugin has no page there."""
        return None

    @property
    def keywords(self) -> list[str]:
        """Extra terms matched when searching for the plugin, on top of its
        name and description."""
        return []

    @property
    def search_text(self) -> str:
        """The text searched when filtering the list of plugins."""
        return ' '.join([self.name, self.description] + self.keywords).casefold()

    @property
    @abstractmethod
    def version(self) -> Version:
        """Version of the plugin."""

    @cached_property
    def base_migration_module(self) -> ModuleType | None:
        """Module containing the migration timeline of the module.
        None if the plugin does not have migrations."""
        return None

    @property
    def default_is_enabled(self) -> bool:
        """Defines if the plugin is enabled by default."""
        return False

    @property
    def default_event_is_enabled(self) -> bool:
        """Defines if the plugin is enabled by default at event level."""
        return False

    @property
    def event_is_enabled_by_default(self) -> bool:
        """Whether new events enable the plugin. The choice made in the Plugins
        section prevails over the default the plugin declares."""
        stored = self.context.stored_plugin.default_event_is_enabled
        return self.default_event_is_enabled if stored is None else stored

    @property
    def federation(self) -> str | None:
        """The federation for which the plugin can be enabled, or None for all"""
        return None

    @property
    def supported_event_types(self) -> list[EventType] | None:
        """The event types this plugin can be enabled for, or None when
        the plugin supports every event type."""
        return None

    def supports_event_type(self, event_type: EventType) -> bool:
        supported = self.supported_event_types
        return supported is None or event_type in supported

    def can_be_enabled_for_event(self, federation: str) -> bool:
        return not self.federation or self.federation == federation

    @property
    def depends_on_plugins(self) -> list['Plugin']:
        """Lists of the dependencies as plugins."""
        from plugins.manager import plugin_manager

        return [
            plugin_manager.plugins_by_id[plugin_type.static_id()]
            for plugin_type in self.dependencies
        ]

    @property
    def dependency_form_keys(self) -> list[str]:
        return [plugin.form_key for plugin in self.depends_on_plugins]

    @property
    def required_by_plugins(self) -> list['Plugin']:
        """List of all the plugins that have this plugin as dependency."""
        from plugins.manager import plugin_manager

        return [
            plugin
            for plugin in plugin_manager.all_plugins
            if self.__class__ in plugin.dependencies
        ]

    @property
    def required_by_enabled_plugins(self) -> list['Plugin']:
        """List of the enabled plugins that have this plugin as dependency,
        which prevent it from being disabled."""
        return [plugin for plugin in self.required_by_plugins if plugin.is_enabled]

    def used_by_events(
        self, events_metadata: list['EventMetadata']
    ) -> list['EventMetadata']:
        return [event for event in events_metadata if self.id in event.enabled_plugins]

    def used_by_events_count(self, events_metadata: list['EventMetadata']) -> int:
        return len(self.used_by_events(events_metadata))

    @abstractmethod
    def used_by_stored_tournament(
        self, stored_event: 'StoredEvent', stored_tournament: 'StoredTournament'
    ) -> bool:
        """Determines if the tournament uses the plugin or not."""

    def used_by_tournaments_count(self, event: 'Event') -> int:
        return sum(
            [
                self.used_by_stored_tournament(
                    event.stored_event, tournament.stored_tournament
                )
                for tournament in event.tournaments
            ]
        )

    @property
    def is_enabled(self) -> bool:
        assert self.context.stored_plugin is not None
        return self.context.stored_plugin.is_enabled

    @property
    def hookspecs(self) -> type | None:
        """Hook specs to add to the plugin manager."""
        return None

    @property
    def form_key(self) -> str:
        return f'plugin_{self.id}'

    @property
    def event_form_fields_template(self) -> str | None:
        """Template of the form containing the fields of the plugin at event level."""
        return None

    @property
    def event_form_script_template(self) -> str | None:
        """Template for a script to add to the configuration form."""
        return None

    @property
    def templates_path(self) -> Path:
        return PLUGINS_DIR / self.id / 'templates'

    @property
    def locale_path(self) -> Path:
        return PLUGINS_DIR / self.id / 'locale'

    @property
    def static_path(self) -> Path:
        return PLUGINS_DIR / self.id / 'static'

    @property
    def controllers(self) -> list[type['BaseController']]:
        """List of controllers for the plugin. Has to be passed this way instead
        of a hook as controllers are initialized at the start of the application."""
        return []

    def get_plugin_data(self) -> PD:
        raw_data = self.context.get_raw_plugin_data()
        if self.data_class is None:
            raise NotImplementedError(
                f'{self.__class__.__name__} must define data_class'
            )
        return self.data_class.from_stored_value(raw_data)

    def get_migration_manager(
        self, database: 'EventDatabase'
    ) -> 'PluginMigrationManager':
        from plugins.migration import PluginMigrationManager

        assert self.base_migration_module is not None
        return PluginMigrationManager(database, self.base_migration_module, self)

    def on_enable(self):
        """Method called when the plugin is enabled."""
        if self.base_migration_module is not None:
            self._migrate_all_events()

    def _migrate_all_events(self, target_migration: str | None = None):
        """Migrates all the event databases to migration."""
        from data.loader import EventLoader
        from database.sqlite.event.event_database import EventDatabase

        for uniq_id in EventLoader().event_uniq_ids:
            database = EventDatabase(uniq_id)
            if migration_manager := self.get_migration_manager(database):
                migration_manager.migrate(target_migration)

    def reload_context(self):
        self.context = PluginContext(self)

    def get_data(
        self,
        plugin_data: dict[str, dict] | None,
        field: str,
        default: Any = None,
    ) -> Any:
        return PluginUtils.get_plugin_data(self.id, plugin_data, field, default)


class ExtraStatisticsSection(NamedTuple):
    at: str
    title: str
    rows: dict[str, int]
    subtitle: str | None


class NavDataTransferItem(NamedTuple):
    """Class representing an upload item in the navigation bar."""

    key: str
    title: str
    icon_path: str
    modal_route_name: str
    has_upload_error: bool


class TournamentConnectionField(NamedTuple):
    """A plugin-supplied field describing a tournament's connection to an
    external service.

    ``label`` is the field name and ``template`` renders only its value (for
    instance the identifier and a link). These fields are grouped in the
    tournament card and list Transfer section.
    """

    label: str
    template: str
