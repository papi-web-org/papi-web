import copy
from functools import cached_property
from pathlib import Path
from typing import Any, TypeVar, TYPE_CHECKING, Optional

from apluggy import PluginManager  # type: ignore

from common import APP_NAME
from plugins.hookspec import AppHookSpecs
from plugins.utils import Plugin

if TYPE_CHECKING:
    from data.event import Event

TPlugin = TypeVar('TPlugin', bound=Plugin[Any])


class AppPluginManager(PluginManager):
    """
    Our own custom subclass of PluginManager. We do this to add several convenience methods
    we use elsewhere in our application.
    """

    @cached_property
    def plugins_by_id(self) -> dict[str, Plugin]:
        from plugins.chess_results.chess_results import ChessResultsPlugin
        from plugins.ffe.ffe import FfePlugin
        from plugins.chessevent.chessevent import ChessEventPlugin
        from plugins.handicap_games.handicap_games import (
            HandicapGamesPlugin,
        )
        from plugins.fra_schools.fra_schools import FRASchoolsPlugin
        from plugins.sce.sce import SCEPlugin
        from plugins.chess960.chess960 import Chess960Plugin
        from plugins.custom_upload.custom_upload import CustomUploadPlugin

        plugins = [
            SCEPlugin(),
            ChessResultsPlugin(),
            FfePlugin(),
            ChessEventPlugin(),
            FRASchoolsPlugin(),
            HandicapGamesPlugin(),
            Chess960Plugin(),
            CustomUploadPlugin(),
        ]
        return {plugin.id: plugin for plugin in plugins}

    @property
    def all_plugins(self) -> list[Plugin]:
        return list(self.plugins_by_id.values())

    @property
    def enabled_plugins(self) -> list[Plugin]:
        return [plugin for plugin in self.all_plugins if plugin.is_enabled]

    def get_plugins_with_dependencies(self, plugins: list[Plugin]) -> list[Plugin]:
        plugins_with_dependencies: list[Plugin] = []
        while plugins:
            plugin = plugins.pop()
            if plugin in plugins_with_dependencies:
                continue
            plugins_with_dependencies.append(plugin)
            for dependency in plugin.depends_on_plugins:
                if dependency not in plugins_with_dependencies:
                    plugins.append(dependency)
        return plugins_with_dependencies

    def get_event_enablable_plugins(self, federation: str) -> list[Plugin]:
        return [
            plugin
            for plugin in self.enabled_plugins
            if plugin.can_be_enabled_for_event(federation)
        ]

    @property
    def templates_paths(self) -> list[Path]:
        return [
            plugin.templates_path
            for plugin in self.all_plugins
            if plugin.templates_path.exists()
        ]

    @property
    def locale_paths(self) -> list[Path]:
        return [
            plugin.locale_path
            for plugin in self.all_plugins
            if plugin.locale_path.exists()
        ]

    @property
    def static_paths(self) -> list[Path]:
        return [
            plugin.static_path
            for plugin in self.all_plugins
            if plugin.static_path.exists()
        ]

    def load_register(self):
        for plugin in self.enabled_plugins:
            self.register(plugin, plugin.id)

    def reload_register(self):
        for plugin in self.all_plugins:
            was_enabled = plugin.is_enabled
            plugin.reload_context()
            is_enabled = plugin.is_enabled
            if is_enabled and not was_enabled:
                plugin.on_enable()
                self.register(plugin, plugin.id)
            elif not is_enabled and was_enabled:
                self.unregister(plugin, plugin.id)

    def enable_dependencies(self):
        from database.sqlite.config.config_database import ConfigDatabase

        enabled_with_dependencies = self.get_plugins_with_dependencies(
            self.enabled_plugins
        )
        with ConfigDatabase(True) as database:
            for plugin in enabled_with_dependencies:
                if plugin.is_enabled:
                    continue
                stored_plugin = copy.copy(plugin.context.stored_plugin)
                stored_plugin.is_enabled = True
                database.update_stored_plugin(stored_plugin)
        self.reload_register()

    def enable_missing_plugins(self, enabled_plugin_ids: list[str]) -> list['Plugin']:
        from database.sqlite.config.config_database import ConfigDatabase

        requested_plugins = [
            self.plugins_by_id[plugin_id]
            for plugin_id in enabled_plugin_ids
            if not self.plugins_by_id[plugin_id].is_enabled
        ]
        plugins_to_enable = [
            plugin
            for plugin in self.get_plugins_with_dependencies(requested_plugins)
            if not plugin.is_enabled
        ]
        if not plugins_to_enable:
            return []
        with ConfigDatabase(True) as database:
            for plugin in plugins_to_enable:
                stored_plugin = copy.copy(plugin.context.stored_plugin)
                stored_plugin.is_enabled = True
                database.update_stored_plugin(stored_plugin)
        self.reload_register()
        return plugins_to_enable

    def disable_plugin(self, plugin: Plugin):
        from database.sqlite.config.config_database import ConfigDatabase

        if not plugin.is_enabled:
            return
        with ConfigDatabase(True) as database:
            stored_plugin = copy.copy(plugin.context.stored_plugin)
            stored_plugin.is_enabled = False
            database.update_stored_plugin(stored_plugin)
        self.reload_register()

    def set_event_is_enabled_by_default(self, plugin: Plugin, is_enabled: bool):
        from database.sqlite.config.config_database import ConfigDatabase

        with ConfigDatabase(True) as database:
            stored_plugin = copy.copy(plugin.context.stored_plugin)
            stored_plugin.default_event_is_enabled = is_enabled
            database.update_stored_plugin(stored_plugin)
        plugin.reload_context()

    def hook_for_event(self, event: Optional['Event'], hook_name: str):
        remove_plugins = []
        if event:
            # event.enabled_plugins (not the raw stored list) so plugins
            # that don't support the event's type stay out of the hooks.
            event_plugin_ids = {plugin.id for plugin in event.enabled_plugins}
            remove_plugins = [
                plugin
                for plugin in self.enabled_plugins
                if plugin.id not in event_plugin_ids
            ]
        return self.subset_hook_caller(hook_name, remove_plugins)

    def hook_for_plugins(self, hook_name: str, plugins: list['Plugin']):
        return self.subset_hook_caller(
            hook_name,
            remove_plugins=[
                plugin for plugin in self.enabled_plugins if plugin not in plugins
            ],
        )


_plugin_manager = None


def get_plugin_manager() -> AppPluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = AppPluginManager(APP_NAME)
        _plugin_manager.add_hookspecs(AppHookSpecs)
        for plugin in _plugin_manager.all_plugins:
            if plugin.hookspecs:
                _plugin_manager.add_hookspecs(plugin.hookspecs)
        _plugin_manager.load_register()
        _plugin_manager.enable_dependencies()
    return _plugin_manager


# Create a lazy proxy object
# This is to avoid circular imports
class LazyPluginManager:
    def __getattr__(self, name):
        return getattr(get_plugin_manager(), name)


plugin_manager: AppPluginManager = LazyPluginManager()  # type: ignore[assignment]
