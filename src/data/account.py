from copy import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from common.i18n import _
from common.i18n.utils import normalized_key
from data.access_levels.access_levels import (
    AccessLevel,
    AdministrationAccessLevel,
    CheckInAccessLevel,
    ResultsEntryAccessLevel,
)
from data.access_levels.manager import AccessLevelManager
from data.player import Player
from database.sqlite.event.event_store import (
    StoredAccount,
    StoredPermission,
    StoredRole,
)
from plugins.utils import AccountPluginData
from plugins.manager import plugin_manager
from utils.enum import RoleType, FideArbiterTitle

if TYPE_CHECKING:
    from data.event import Event


#: Applied when a password is set or changed.  Accounts that already have a
#: shorter one keep it: a password good enough for a venue's own network is not
#: worth locking an arbiter out of a running event over.
MINIMUM_PASSWORD_LENGTH = 8


@dataclass
class Role:
    stored_role: StoredRole

    @property
    def role_type(self) -> RoleType:
        return RoleType(self.stored_role.role)

    @property
    def tournament_ids(self) -> set[int] | None:
        stored_tournament_ids = self.stored_role.tournament_ids
        return set(stored_tournament_ids) if stored_tournament_ids else None

    def tournaments_tooltip_message(self, event: 'Event') -> str:
        return ''.join(
            f'<div class="text-center text-nowrap">{name}</div>'
            for name in self.tournament_names(event)
        )

    def tournament_names(self, event: 'Event') -> list[str]:
        if not self.tournament_ids:
            return []
        return sorted(
            (
                event.tournaments_by_id[tournament_id].name
                for tournament_id in self.tournament_ids
            ),
            key=normalized_key,
        )


@dataclass
class Permission:
    stored_permission: StoredPermission
    inherited_by: AccessLevel | None = None

    @property
    def access_level(self) -> AccessLevel:
        return AccessLevelManager().get_object(self.stored_permission.access_level)

    @property
    def inherited(self) -> bool:
        return bool(self.inherited_by)

    @property
    def tournament_ids(self) -> set[int] | None:
        stored_tournament_ids = self.stored_permission.tournament_ids
        return set(stored_tournament_ids) if stored_tournament_ids else None

    def tournaments_tooltip_message(self, event: 'Event') -> str:
        return ''.join(
            f'<div class="text-center text-nowrap">{name}</div>'
            for name in self.tournament_names(event)
        )

    def tournament_names(self, event: 'Event') -> list[str]:
        if not self.tournament_ids:
            return []
        return sorted(
            (
                event.tournaments_by_id[tournament_id].name
                for tournament_id in self.tournament_ids
            ),
            key=normalized_key,
        )


class Account:
    """A data wrapper around a stored account.
    The class that represents an account."""

    ADMINISTRATOR_ID: int = 1
    ANONYMOUS_ID: int = 2

    def __init__(self, stored_account: StoredAccount):
        self.stored_account = stored_account
        self.plugin_data = self._get_plugin_data()

    # -------------------------------------------------------------------------
    # Plugin
    # -------------------------------------------------------------------------

    @staticmethod
    def plugin_data_class_by_plugin_id() -> dict[str, type[AccountPluginData]]:
        return {
            plugin_id: plugin_data_class
            for plugin_id, plugin_data_class in plugin_manager.hook.get_account_plugin_data_class()
        }

    def _get_plugin_data(self) -> dict[str, AccountPluginData]:
        return {
            plugin_id: plugin_data_class.from_stored_value(
                self.stored_account.plugin_data.get(plugin_id, {})
            )
            for plugin_id, plugin_data_class in self.plugin_data_class_by_plugin_id().items()
        }

    @property
    def id(self) -> int:
        assert self.stored_account.id is not None
        return self.stored_account.id

    @property
    def administrator(self) -> bool:
        """Returns True for the administrator account, False otherwise."""
        return self.id == self.ADMINISTRATOR_ID

    @property
    def anonymous(self) -> bool:
        """Returns True for the anonymous account, False otherwise."""
        return self.id == self.ANONYMOUS_ID

    @property
    def user_account(self) -> bool:
        """Returns True if a 'real' user account (not administrator or anonymous), False otherwise."""
        return self.id not in (
            self.ADMINISTRATOR_ID,
            self.ANONYMOUS_ID,
        )

    @property
    def first_name(self) -> str | None:
        """Returns the first name of the account."""
        if self.administrator:
            return None
        if self.anonymous:
            return None
        return self.stored_account.first_name

    @property
    def last_name(self) -> str:
        """Returns the last name of the account."""
        if self.administrator:
            return _('Administrator')
        if self.anonymous:
            return _('Anonymous')
        assert self.stored_account.last_name is not None
        return self.stored_account.last_name

    @property
    def fide_id(self) -> int | None:
        """Returns the fide id of the account."""
        return self.stored_account.fide_id

    @property
    def fide_arbiter_title(self) -> FideArbiterTitle:
        return FideArbiterTitle(self.stored_account.fide_arbiter_title or '')

    @property
    def full_name(self) -> str:
        return Player.player_full_name(self.first_name, self.last_name)

    @property
    def password_hash(self) -> str | None:
        """Returns the password hash of the account."""
        return self.stored_account.password_hash

    def update_password(self, new_hash: str):
        self.stored_account.password_hash = new_hash

    @property
    def mail(self) -> str | None:
        """Returns the mail of the account."""
        return self.stored_account.mail

    @property
    def phone(self) -> str | None:
        """Returns the phone of the account."""
        return self.stored_account.phone

    @property
    def roles(self) -> list[Role]:
        return sorted(
            (Role(stored_role) for stored_role in self.stored_account.stored_roles),
            key=lambda r: RoleType(r.stored_role.role).sort_order,
        )

    def get_role(self, role_type: RoleType) -> Role:
        for stored_role in self.stored_account.stored_roles:
            if stored_role.role == role_type.value:
                return Role(stored_role)
        return Role(
            StoredRole(
                self.id, role_type.value, [] if role_type.is_tournament_bound else None
            )
        )

    @property
    def active(self) -> bool:
        return self.stored_account.active

    @property
    def access_levels(self) -> list[AccessLevel]:
        return [permission.access_level for permission in self.permissions]

    @property
    def permissions(self) -> list[Permission]:
        return [
            Permission(stored_permission)
            for stored_permission in self.stored_account.stored_permissions
        ]

    @property
    def sorted_permissions(self) -> list[Permission]:
        access_level_ids = AccessLevelManager().ids()
        return sorted(
            self.permissions,
            key=lambda p: access_level_ids.index(p.stored_permission.access_level),
        )

    @property
    def fide_arbiter_str(self) -> str:
        """String representation of the account as a FIDE arbiter."""
        arbiter = self.last_name
        if self.first_name:
            arbiter += f', {self.first_name}'
        suffixes: list[str] = []
        title = self.fide_arbiter_title
        if title != FideArbiterTitle.NONE:
            suffixes.append(title.fide_acronym)
        if self.fide_id:
            suffixes.append(str(self.fide_id))
        if suffixes:
            arbiter += f' ({", ".join(suffixes)})'
        return arbiter

    def get_card_title(self, event: 'Event') -> str:
        card_title = self.full_name
        suffixes: list[str] = []
        title = self.fide_arbiter_title
        if title != FideArbiterTitle.NONE:
            suffixes.append(title.short_name)
        plugin_suffixes = plugin_manager.hook_for_event(
            event, 'get_account_card_title_suffix'
        )(account=self)
        suffixes += [suffix for suffix in plugin_suffixes if suffix]
        if suffixes:
            card_title += f' ({", ".join(suffixes)})'
        return card_title

    @property
    def edit_properties(self) -> bool:
        """Returns False if the account is locked (can not be updated or deleted)."""
        return not self.administrator and not self.anonymous

    @property
    def edit_permissions(self) -> bool:
        """Returns True if the permissions of the account can be updated."""
        return not self.administrator

    def get_permissions_by_access_level(
        self,
        with_inheritance: bool = True,
        avoid_access_level: AccessLevel | None = None,
    ) -> dict[AccessLevel, Permission]:
        """Returns all the permissions by access level, granted or inherited for the account."""
        permissions_by_access_level: dict[AccessLevel, Permission] = {}
        for permission in self.sorted_permissions:
            access_level = permission.access_level
            if avoid_access_level == access_level:
                continue
            permissions_by_access_level[access_level] = self._merge_permissions(
                permission,
                permissions_by_access_level.get(access_level, None),
            )
            if not with_inheritance:
                continue
            for sub_access_level in access_level.sub_access_levels():
                sub_stored_permission = copy(permission.stored_permission)
                sub_stored_permission.access_level = sub_access_level.id
                permissions_by_access_level[sub_access_level] = self._merge_permissions(
                    Permission(sub_stored_permission, inherited_by=access_level),
                    permissions_by_access_level.get(sub_access_level, None),
                )
        return {
            access_level: permissions_by_access_level[access_level]
            for access_level in AccessLevelManager().objects()
            if access_level in permissions_by_access_level
        }

    @staticmethod
    def _merge_permissions(
        permission1: Permission, permission2: Permission | None
    ) -> Permission:
        if not permission2:
            return permission1
        stored_permission = copy(permission1.stored_permission)
        stored_permission.tournament_ids = None
        if (
            permission1.tournament_ids is not None
            and permission2.tournament_ids is not None
        ):
            stored_permission.tournament_ids = list(
                permission1.tournament_ids | permission2.tournament_ids
            )
        return Permission(
            stored_permission,
            inherited_by=permission1.inherited_by or permission2.inherited_by,
        )

    def is_permission_redundant(self, permission: Permission) -> bool:
        """Checks if a permission is redundant,
        i.e. if the permissions would be the same if it wasn't there."""
        other_permission = self.get_permissions_by_access_level(
            avoid_access_level=permission.access_level
        ).get(permission.access_level, None)
        if not other_permission:
            return False
        if permission.tournament_ids and other_permission.tournament_ids:
            return permission.tournament_ids.issubset(other_permission.tournament_ids)
        return bool(permission.tournament_ids)

    def __str__(self) -> str:
        return f'Account(id={self.id}, full_name={self.full_name})'

    def __repr__(self):
        return f'{self.__class__.__name__}(stored_account={self.stored_account!r})'

    # Accounts are stored at event-level, the methods below provide event-free
    # instances that can be used when no events are available (welcome page, ...)

    @classmethod
    def predefined_administrator_account(cls) -> 'Account':
        return cls(
            StoredAccount(
                id=cls.ADMINISTRATOR_ID,
                active=True,
                first_name=None,
                last_name=None,
                stored_permissions=[
                    StoredPermission(
                        cls.ADMINISTRATOR_ID, AdministrationAccessLevel.static_id()
                    ),
                ],
                stored_roles=[],
            )
        )

    @classmethod
    def predefined_anonymous_account(cls) -> 'Account':
        return cls(
            StoredAccount(
                id=cls.ANONYMOUS_ID,
                active=True,
                first_name=None,
                last_name=None,
                stored_permissions=[
                    StoredPermission(cls.ANONYMOUS_ID, CheckInAccessLevel.static_id()),
                    StoredPermission(
                        cls.ANONYMOUS_ID, ResultsEntryAccessLevel.static_id()
                    ),
                ],
            )
        )
