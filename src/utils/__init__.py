import re
import subprocess
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from functools import lru_cache, cache
from math import floor
from subprocess import CompletedProcess
from typing import Callable, Iterable, Protocol, Hashable, Collection, TYPE_CHECKING

import iso4217parse
import pycountry
from babel.numbers import format_currency, format_decimal, get_decimal_symbol
from text_unidecode import unidecode

if TYPE_CHECKING:
    from data.tournament import Tournament
    from database.sqlite.event.event_store import StoredTournament


class Utils:
    """Class containing the utils functions"""

    EMAIL_REGEX = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}$'

    PERFORMANCE_TABLE: list[int] = [
        0,
        7,
        14,
        21,
        29,
        36,
        43,
        50,
        57,
        65,
        72,
        80,
        87,
        95,
        102,
        110,
        117,
        125,
        133,
        141,
        149,
        158,
        166,
        175,
        184,
        193,
        202,
        211,
        220,
        230,
        240,
        251,
        262,
        273,
        284,
        296,
        309,
        322,
        336,
        351,
        366,
        383,
        401,
        422,
        444,
        470,
        501,
        538,
        589,
        677,
        800,
    ]

    DIFFERENCE_TO_PROBABILITY_TABLE = [
        (0, 3, 0.50),
        (4, 10, 0.51),
        (11, 17, 0.52),
        (18, 25, 0.53),
        (26, 32, 0.54),
        (33, 39, 0.55),
        (40, 46, 0.56),
        (47, 53, 0.57),
        (54, 61, 0.58),
        (62, 68, 0.59),
        (69, 76, 0.60),
        (77, 83, 0.61),
        (84, 91, 0.62),
        (92, 98, 0.63),
        (99, 106, 0.64),
        (107, 113, 0.65),
        (114, 121, 0.66),
        (122, 129, 0.67),
        (130, 137, 0.68),
        (138, 145, 0.69),
        (146, 153, 0.70),
        (154, 162, 0.71),
        (163, 170, 0.72),
        (171, 179, 0.73),
        (180, 188, 0.74),
        (189, 197, 0.75),
        (198, 206, 0.76),
        (207, 215, 0.77),
        (216, 225, 0.78),
        (226, 235, 0.79),
        (236, 245, 0.80),
        (246, 256, 0.81),
        (257, 267, 0.82),
        (268, 278, 0.83),
        (279, 290, 0.84),
        (291, 302, 0.85),
        (303, 315, 0.86),
        (316, 328, 0.87),
        (329, 344, 0.88),
        (345, 357, 0.89),
        (358, 374, 0.90),
        (375, 391, 0.91),
        (392, 411, 0.92),
        (412, 432, 0.93),
        (433, 456, 0.94),
        (457, 484, 0.95),
        (485, 517, 0.96),
        (518, 559, 0.97),
        (560, 619, 0.98),
        (620, 735, 0.99),
        (736, 1000, 1.00),
    ]

    @classmethod
    def win_probability(cls, diff: int) -> float:
        probability = next(
            (
                p
                for start, end, p in cls.DIFFERENCE_TO_PROBABILITY_TABLE
                if start <= abs(diff) <= end
            ),
            cls.DIFFERENCE_TO_PROBABILITY_TABLE[-1][2],
        )

        return probability if diff < 0 else 1 - probability

    @classmethod
    @lru_cache(maxsize=32)
    def performance_bonus(cls, fractional_score: float) -> int:
        percent = 100 * fractional_score
        index = floor(abs(50 - percent))
        bonus = cls.PERFORMANCE_TABLE[index]
        if fractional_score < 0.5:
            bonus *= -1
        return bonus

    @staticmethod
    def round_ranking(num: float | Decimal) -> int:
        lowest_int = int(num)
        if num - lowest_int >= 0.5:
            return lowest_int + 1
        return lowest_int

    @staticmethod
    def points_str(points: float | None, plus_sign: bool = False) -> str:
        if points is None:
            return ''
        if plus_sign:
            points_str = f'{points:+.2f}'
        else:
            points_str = f'{points:.2f}'
        # Drop the leading zero of a bare fraction, so half a point reads
        # ½ rather than 0½ — on either side of zero, since a penalty can
        # take a score below it.
        if points and -1 < points < 1:
            points_str = points_str.replace('0.', '.', 1)
        for old, new in {
            '.00': '',
            '.25': '¼',
            '.50': '½',
            '.75': '¾',
        }.items():
            points_str = points_str.replace(old, new)
        return points_str

    @classmethod
    def points_delta_str(cls, delta: float | None) -> str:
        return cls.points_str(delta, plus_sign=True)

    @staticmethod
    def currency_value_str(value: float, currency: str) -> str:
        from common.i18n import get_locale

        locale = get_locale()
        formatted_value = format_currency(value, currency, locale=locale)
        if value.is_integer():
            formatted_value = formatted_value.replace(
                f'{get_decimal_symbol(locale)}00', ''
            )
        return formatted_value

    @staticmethod
    def localized_number(number: float) -> str:
        from common.i18n import get_locale

        return format_decimal(number, locale=get_locale())

    @staticmethod
    @cache
    def get_country_currency(alpha_3_country_code: str) -> str | None:
        country = pycountry.countries.get(alpha_3=alpha_3_country_code)
        if not country:
            return None
        currencies = iso4217parse.by_country(country.alpha_2)
        if not currencies:
            return None
        return currencies[0].alpha3

    country_codes_by_federation = {
        'FRA': ['FR', 'RE', 'PM', 'NC', 'GF', 'GP', 'MQ'],
    }

    @classmethod
    def get_federation_from_alpha_2_country_code(
        cls,
        alpha_2_country_code: str,
    ) -> str | None:
        from common.sharly_chess_config import SharlyChessConfig

        for federation, country_codes in cls.country_codes_by_federation.items():
            if alpha_2_country_code in country_codes:
                return federation
        country = pycountry.countries.get(alpha_2=alpha_2_country_code)
        if country and country.alpha_3 in SharlyChessConfig().federations:
            return country.alpha_3
        return None

    @classmethod
    def ordinal_integer(cls, value: int) -> str:
        from common.i18n import get_locale, _

        locale = get_locale()
        affix_fn: Callable[[int], tuple[str, str]]
        match locale:
            case 'en':
                affix_fn = cls._ordinal_affix_en
            case 'fr':
                affix_fn = cls._ordinal_affix_fr
            case _:
                raise NotImplementedError(
                    f'no ordinal affix function for locale {locale}'
                )
        prefix, suffix = affix_fn(value)
        return _('{prefix}{int_value}<sup>{suffix}</sup>').format(
            prefix=prefix, int_value=value, suffix=suffix
        )

    @staticmethod
    @cache
    def _ordinal_affix_en(value: int) -> tuple[str, str]:
        suffix = 'th'
        if not 11 <= value <= 13:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, suffix)
        return '', suffix

    @staticmethod
    @cache
    def _ordinal_affix_fr(value: int) -> tuple[str, str]:
        return '', 'er' if value == 1 else 'e'

    @staticmethod
    def name_to_uniq_id(name: str) -> str:
        name = unidecode(name).lower()
        name = re.sub(r' \((\d+)\)$', r'-\1', name)
        return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)

    @classmethod
    def get_unused_item_uniq_id(
        cls, base_uniq_id: str, used_uniq_ids: Iterable[str]
    ) -> str:
        """Returns the first unused uniq_id in a list looking like base_uniq_id:
        base_uniq_id, or base_uniq_id-2, or base_uniq_id-n+1...

        Matching is case-insensitive: a uniq_id maps to a database file name, and
        those live on case-insensitive filesystems, so ``foo`` and ``Foo`` are the
        same slot."""
        base_uniq_id = cls.name_to_uniq_id(base_uniq_id)
        index = 1
        uniq_id = base_uniq_id
        if matches := re.match(r'^(.*)-(\d+)$', base_uniq_id):
            base_uniq_id = matches.group(1)
            index = int(matches.group(2))
            uniq_id = f'{base_uniq_id}-{index}'
        used = {str(used_id).casefold() for used_id in used_uniq_ids}
        while uniq_id.casefold() in used:
            index += 1
            uniq_id = f'{base_uniq_id}-{index}'
        return uniq_id

    @staticmethod
    def get_unused_item_name(base_name: str, used_names: Iterable[str]) -> str:
        """Returns the first unused name in a list looking like base_name:
        base_name, or base_name (2), or base_name (n+1)..."""
        index = 1
        name = base_name
        if matches := re.match(r'^(.*) \((\d+)\)$', base_name):
            base_name = matches.group(1)
            index = int(matches.group(2))
            name = f'{base_name} ({index})'
        while name in used_names:
            index += 1
            name = f'{base_name} ({index})'
        return name

    @staticmethod
    def run_process(cmd: list, **kwargs) -> CompletedProcess:
        """Run a subprocess without showing a console window on Windows."""
        if sys.platform == 'win32':
            # Prevent flashing console windows when app is packaged with PyInstaller (--windowed)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs.setdefault('startupinfo', startupinfo)
            kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
        return subprocess.run(cmd, **kwargs)

    @staticmethod
    def concat_dicts[K, V](dict_list: list[dict[K, V]]) -> dict[K, V]:
        return {key: value for dict_ in dict_list for key, value in dict_.items()}

    @staticmethod
    def age_in_months(start: datetime) -> int:
        """Get the age of a datetime expressed in months."""
        end = datetime.now()
        return (
            12 * (end.year - start.year)
            + (end.month - start.month)
            - (1 if end.day < start.day else 0)
        )

    @staticmethod
    def reset_cached_properties(obj: object, *property_names: str):
        for property_name in property_names:
            if property_name in obj.__dict__:
                del obj.__dict__[property_name]

    @staticmethod
    def tournament_results_modified_since(
        tournament: 'Tournament | StoredTournament',
        ref_datetime: datetime,
    ) -> bool:
        return ref_datetime < max(
            tournament.last_update,
            tournament.last_player_update or datetime.min,
            tournament.last_pairing_update or datetime.min,
        )

    @staticmethod
    def get_rating_range_label(min_rating: int | None, max_rating: int | None) -> str:
        from common.i18n import _

        prefix = ''
        suffix = ''
        if max_rating:
            if max_rating % 10 == 9:
                suffix = f' < {max_rating + 1}'
            else:
                suffix = f' ≤ {max_rating}'
            if min_rating:
                if min_rating % 10 == 1:
                    prefix = f'{min_rating - 1} < '
                else:
                    prefix = f'{min_rating} ≤ '
        elif min_rating:
            if min_rating % 10 == 1:
                suffix = f' > {min_rating - 1}'
            else:
                suffix = f' ≥ {min_rating}'
        return f'{prefix}{_("Rating")}{suffix}'

    @staticmethod
    def truncate_middle(text: str, max_length: int) -> str:
        """Shortens `text` by taking characters out of its middle.

        Names that differ only at their end — "… - Open A" and "… - Open B" —
        are told apart by keeping both ends, which the end ellipsis CSS offers
        cannot do.
        """
        if max_length < 2 or len(text) <= max_length:
            return text
        kept = max_length - 1
        head = (kept + 1) // 2
        return f'{text[:head]}…{text[len(text) - (kept - head) :]}'


class SupportsEquals(Protocol):
    def __eq__(self, other: object) -> bool: ...


class CoreMapper[OuterType: Hashable, CoreType: SupportsEquals](ABC):
    """Class mapping non-application values to objects of the core.
    Example: map values of a database to their representation."""

    @staticmethod
    @abstractmethod
    def _core_object_by_outer_value() -> dict[OuterType, CoreType]:
        """Objects from the core mapped by outer value.
        Every possible value should be represented."""

    @classmethod
    def get_core_object(cls, outer_value: OuterType) -> CoreType:
        """Retrieve the core object associated to the outer value."""
        return cls._core_object_by_outer_value()[outer_value]

    @classmethod
    def get_outer_value(cls, core_object: CoreType) -> OuterType | None:
        """Get an outer value from a core object.
        Returns None if the core object does not exist as an outer value."""
        return next(
            (
                outer_value
                for outer_value, mapped_core_object in cls._core_object_by_outer_value().items()
                if mapped_core_object == core_object
            ),
            None,
        )

    @classmethod
    def core_objects(cls) -> Collection[CoreType]:
        return cls._core_object_by_outer_value().values()

    @classmethod
    def outer_values(cls) -> Collection[OuterType]:
        return cls._core_object_by_outer_value().keys()
