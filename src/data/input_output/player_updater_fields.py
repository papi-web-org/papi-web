import copy
from abc import ABC, abstractmethod

from common.i18n import _
from data.player import Player
from database.sqlite.event.event_store import StoredPlayer
from utils.entity import IdentifiableEntity
from utils.enum import TournamentRating, PlayerRatingType
from utils.types import PlayerRating


class PlayerUpdaterField(IdentifiableEntity, ABC):
    @abstractmethod
    def is_updated(self, player: Player, match_player: Player) -> bool:
        """Check if the field is updated in the match player compared to the source player."""

    @abstractmethod
    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        """Update the source player from the match player's value."""

    @abstractmethod
    def get_string_value(self, player: Player) -> str:
        """Get the string value from a player. Used to generate the cell content and tooltip."""

    @property
    def cell_template(self) -> str:
        """Template of the cell of the field in the player update modal."""
        return ''

    @property
    def cell_classes(self) -> str:
        """CSS classes to apply to the cell."""
        return 'text-center'

    def get_composed_string_value(self, _player: Player, match_player: Player) -> str:
        """Get the value tha will would result from the update as a string."""
        return self.get_string_value(match_player)

    def get_cell_content(self, player: Player, match_player: Player) -> str:
        """Get the content of the cell. Only used if no cell template is defined."""
        return self.get_composed_string_value(player, match_player)

    def updated_tooltip_message(self, player: Player, match_player: Player) -> str:
        """Message of the tooltip displayed on the cell if the field has been updated."""
        src_value = self.get_string_value(player)
        match_value = self.get_composed_string_value(player, match_player)
        if src_value in ('', '-'):
            return _('Set to <b>{value}</b>').format(value=match_value)
        if match_value in ('', '-'):
            return _('Delete <b>{value}</b>').format(value=src_value)
        return _('Replace <b>{old}</b> by <b>{new}</b>').format(
            old=src_value, new=match_value
        )


class FideIDUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'fide_id'

    @staticmethod
    def static_name() -> str:
        return 'FIDE'

    def get_string_value(self, player: Player) -> str:
        return str(player.fide_id or '-')

    def is_updated(self, player: Player, match_player: Player) -> bool:
        return bool(match_player.fide_id) and player.fide_id != match_player.fide_id

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.fide_id = match_stored_player.fide_id

    @property
    def cell_classes(self) -> str:
        return 'text-start'


class TitleUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'title'

    @staticmethod
    def static_name() -> str:
        return ''

    def get_string_value(self, player: Player) -> str:
        return player.title.short_name

    def is_updated(self, src_player: Player, match_player: Player) -> bool:
        return src_player.title != match_player.title

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.title = match_stored_player.title


class WomenTitleUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'women_title'

    @staticmethod
    def static_name() -> str:
        return ''

    def get_string_value(self, player: Player) -> str:
        return player.women_title.short_name

    def is_updated(self, src_player: Player, match_player: Player) -> bool:
        return src_player.women_title != match_player.women_title

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.women_title = match_stored_player.women_title


class NameUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'name'

    @staticmethod
    def static_name() -> str:
        return _('Name')

    def get_string_value(self, player: Player) -> str:
        return player.full_name

    def is_updated(self, src_player: Player, match_player: Player) -> bool:
        return (src_player.first_name, src_player.last_name) != (
            match_player.first_name,
            match_player.last_name,
        )

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.last_name = match_stored_player.last_name
        stored_player.first_name = match_stored_player.first_name

    @property
    def cell_classes(self) -> str:
        return 'text-start'


class CategoryUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'category'

    @staticmethod
    def static_name() -> str:
        return _('Category')

    def get_string_value(self, player: Player) -> str:
        return player.date_or_year_of_birth_str

    def get_cell_content(self, player: Player, match_player: Player) -> str:
        yob = match_player.year_of_birth
        if not yob:
            return ''
        return f'{yob} {match_player.category.name}'

    def is_updated(self, player: Player, match_player: Player) -> bool:
        src_date = player.date_of_birth
        src_year = player.year_of_birth
        match_date = match_player.date_of_birth
        match_year = match_player.year_of_birth
        if not match_date and not match_year:
            return False
        if not src_date and not src_year:
            return True
        if src_date and match_date:
            return src_date != match_date
        return bool(match_date) or src_year != match_year

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.year_of_birth = match_stored_player.year_of_birth
        stored_player.date_of_birth = match_stored_player.date_of_birth


class GenderPlayerUpdater(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'gender'

    @staticmethod
    def static_name() -> str:
        return _('Gender')

    def is_updated(self, player: Player, match_player: Player) -> bool:
        return player.gender != match_player.gender

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.gender = match_stored_player.gender

    def get_string_value(self, player: Player) -> str:
        return player.gender.name

    def get_cell_content(self, player: Player, match_player: Player) -> str:
        return match_player.gender.short_name


class RatingUpdaterField(PlayerUpdaterField, ABC):
    def __init__(self, rating_types: list[PlayerRatingType] | None = None):
        self.rating_types = rating_types or list(PlayerRatingType)

    @staticmethod
    @abstractmethod
    def tournament_rating() -> TournamentRating:
        """Type of tournament rating this field is applied to."""

    @classmethod
    def static_id(cls) -> str:
        return f'rating_{cls.tournament_rating().form_key}'

    @classmethod
    def static_name(cls) -> str:
        return cls.tournament_rating().short_name

    @property
    def _with_k_factor(self) -> bool:
        return PlayerRatingType.FIDE in self.rating_types

    def is_updated(self, player: Player, match_player: Player) -> bool:
        src_ratings = player.ratings[self.tournament_rating()]
        match_ratings = match_player.ratings[self.tournament_rating()]
        if self._with_k_factor and src_ratings.k_factor != match_ratings.k_factor:
            return True
        return any(
            src_ratings.get_type_value(rt) != match_ratings.get_type_value(rt)
            for rt in self.rating_types
        )

    def updated_tooltip_message(self, player: Player, match_player: Player) -> str:
        message = super().updated_tooltip_message(player, match_player)
        src_ratings = player.ratings[self.tournament_rating()]
        match_ratings = match_player.ratings[self.tournament_rating()]
        if (
            PlayerRatingType.FIDE in self.rating_types
            and src_ratings.fide is not None
            and match_ratings.fide is None
        ):
            message += f' ({_("FIDE rating lost")})'
        return message

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        tr = self.tournament_rating().value
        src_ratings = PlayerRating.from_stored_value(stored_player.ratings.get(tr, {}))
        match_ratings = PlayerRating.from_stored_value(
            match_stored_player.ratings.get(tr, {})
        )
        for rating_type in self.rating_types:
            src_ratings.set_value_from_type(
                match_ratings.get_type_value(rating_type), rating_type
            )
        if self._with_k_factor:
            src_ratings.k_factor = match_ratings.k_factor
        stored_player.ratings[tr] = src_ratings.stored_value

    def _format_ratings(self, ratings: PlayerRating) -> str:
        if self._with_k_factor and ratings.k_factor is not None:
            return f'{ratings} (K{ratings.k_factor})'
        return str(ratings)

    def get_string_value(self, player: Player) -> str:
        return self._format_ratings(player.ratings[self.tournament_rating()])

    def get_composed_string_value(self, _player: Player, match_player: Player) -> str:
        ratings = copy.deepcopy(_player.ratings[self.tournament_rating()])
        match_ratings = match_player.ratings[self.tournament_rating()]
        for rating_type in self.rating_types:
            ratings.set_value_from_type(
                match_ratings.get_type_value(rating_type), rating_type
            )
        if self._with_k_factor:
            ratings.k_factor = match_ratings.k_factor
        return self._format_ratings(ratings)


class StandardRatingUpdaterField(RatingUpdaterField):
    @staticmethod
    def tournament_rating() -> TournamentRating:
        return TournamentRating.STANDARD


class RapidRatingUpdaterField(RatingUpdaterField):
    @staticmethod
    def tournament_rating() -> TournamentRating:
        return TournamentRating.RAPID


class BlitzRatingUpdaterField(RatingUpdaterField):
    @staticmethod
    def tournament_rating() -> TournamentRating:
        return TournamentRating.BLITZ


class FederationUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'federation'

    @staticmethod
    def static_name() -> str:
        return _('Fed. *** FEDERATION COLUMN HEADER')

    def is_updated(self, player: Player, match_player: Player) -> bool:
        return player.federation != match_player.federation

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.federation = match_stored_player.federation

    def get_string_value(self, player: Player) -> str:
        return player.federation.name


class ClubUpdaterField(PlayerUpdaterField):
    @staticmethod
    def static_id() -> str:
        return 'club'

    @staticmethod
    def static_name() -> str:
        return _('Club')

    def is_updated(self, player: Player, match_player: Player) -> bool:
        return player.club != match_player.club

    def update_player(
        self, stored_player: StoredPlayer, match_stored_player: StoredPlayer
    ):
        stored_player.club = match_stored_player.club

    def get_string_value(self, player: Player) -> str:
        return player.club.name

    @property
    def cell_classes(self) -> str:
        return 'text-start'
