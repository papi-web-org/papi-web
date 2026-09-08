import locale
import logging
import os
import re
import subprocess
import sys
from copy import copy
from typing import Optional, overload, TYPE_CHECKING

import jinja2
import litestar
import uvicorn
from packaging.version import Version

from common import (
    SHARLY_CHESS_VERSION,
    TEST_ENV,
    enable_experimental_features,
)
from common.i18n import (
    DEFAULT_LOCALE,
    _,
    locales,
    normalize_bcp47_to_locale,
    read_macos_global_prefs,
    set_locale,
    get_locale,
)
from common.logger import set_logging_config, get_logger
from common.network import find_lan_interfaces, LOCALHOST_IP
from common.singleton import Singleton
from plugins.manager import plugin_manager
from utils.date_formatter import DateFormatter
from utils.enum import Result, Extension
from database.sqlite.config.config_database import ConfigDatabase
from database.sqlite.config.config_store import StoredConfig
from utils.date_time import DateFormatterManager
from utils.program_variables import ProgramVar

if TYPE_CHECKING:
    from data.player import Federation
    from data.player_categories import PlayerCategorySet
    from data.tag import Tag
    from data.tie_breaks.sets import TieBreakSet

logger: logging.Logger = get_logger()


class SharlyChessConfig(metaclass=Singleton):
    """The configuration for the application, read from the database."""

    def __init__(self):
        self.web_port: int | None = None
        self._stored_config: StoredConfig | None = None
        self._date_formatter: DateFormatter | None = None
        self._federations_by_locale: dict[str, dict[str, str]] = {}

    @staticmethod
    def _get_system_user_locale() -> str | None:
        """Returns the locale used by the user at system-level,
        if known by the i18n stuff (otherwise returns None)."""
        if TEST_ENV:
            return 'en_GB'
        if sys.platform == 'win32':  # pragma: py-not-win32
            import ctypes

            windll = ctypes.windll.kernel32
            try:
                # Locale ID → Windows locale name → Python locale key
                # locale.windows_locale maps LCIDs to names like 'en_GB'
                system_user_locale = locale.windows_locale[
                    windll.GetUserDefaultUILanguage()
                ]
                logger.info('User locale (Windows): %s', system_user_locale)
                return system_user_locale
            except Exception as e:
                logger.debug('Failed to get Windows UI language: %s', e)
                # fall through to generic fallback below

        elif sys.platform == 'darwin':
            prefs = read_macos_global_prefs()
            lang_list = prefs.get('AppleLanguages') or []
            apple_locale = prefs.get('AppleLocale')

            if lang_list:
                loc = normalize_bcp47_to_locale(str(lang_list[0]))
                logger.info('User locale (macOS AppleLanguages): %s', loc)
                return loc

            if apple_locale:
                loc = normalize_bcp47_to_locale(str(apple_locale))
                logger.info('User locale (macOS AppleLocale): %s', loc)
                return loc

            # last-ditch: `defaults read -g AppleLanguages`
            try:
                proc = subprocess.run(
                    ['defaults', 'read', '-g', 'AppleLanguages'],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                # Output is Apple’s property list textual representation; pick first token in quotes
                import re

                m = re.search(r'"([^"]+)"', proc.stdout)
                if m:
                    loc = normalize_bcp47_to_locale(m.group(1))
                    logger.info('User locale (macOS defaults fallback): %s', loc)
                    return loc
            except Exception as e:
                logger.debug('macOS defaults fallback failed: %s', e)

        # Linux / other: rely on locale module / env
        try:
            # Ensure LC_CTYPE is initialized from environment
            locale.setlocale(locale.LC_CTYPE, '')
        except Exception:
            pass

        lang = (
            os.environ.get('LC_ALL')
            or os.environ.get('LC_MESSAGES')
            or os.environ.get('LANG')
            or ''
        )

        if lang:
            # LANG often looks like 'en_GB.UTF-8' → strip encoding
            loc = lang.split('.', 1)[0]
            logger.info('User locale (env): %s', loc)
            return loc

        # Final fallback: locale.getlocale()
        try:
            loc_tuple = locale.getlocale()  # (language_code, encoding)
            if loc_tuple and loc_tuple[0]:
                logger.info('User locale (locale.getlocale): %s', loc_tuple[0])
                return loc_tuple[0]
        except Exception:
            pass

        logger.info('User locale: unknown')
        return None

    @staticmethod
    def _get_user_locale(system_user_locale: str | None) -> str:
        """Returns the locale to set in Sharly Chess."""
        setup_locale = ProgramVar.LOCALE.read_value()
        if setup_locale:
            return setup_locale
        if system_user_locale is not None:
            user_locale: str = system_user_locale[:2]
            if user_locale in locales:
                return user_locale
            logger.warning(
                'Unknown locale: %s (%s by default)', user_locale, DEFAULT_LOCALE
            )
        return DEFAULT_LOCALE

    def load_and_set_env(self):
        with ConfigDatabase() as config_database:
            stored_config: StoredConfig = config_database.load_stored_config()
        if not stored_config.locale:
            system_user_locale: str | None = self._get_system_user_locale()
            stored_config.locale = self._get_user_locale(system_user_locale)
            with ConfigDatabase(write=True) as config_database:
                config_database.update_stored_config(stored_config)
        if TEST_ENV:
            stored_config.federation = SharlyChessConfig.tests_federation
        assert stored_config.locale is not None
        set_locale(stored_config.locale)
        set_logging_config(
            console_log_level=stored_config.console_log_level,
            console_color=stored_config.console_color,
            console_show_date=stored_config.console_show_date,
            console_show_level=stored_config.console_show_level,
        )
        self._date_formatter = DateFormatterManager().get_object(
            stored_config.date_formatter
        )
        enable_experimental_features(stored_config.experimental)
        plugin_manager.reload_register()
        self._stored_config = stored_config

    @property
    def stored_config(self) -> StoredConfig:
        if not self._stored_config:
            self.load_and_set_env()
            assert self._stored_config is not None
        return self._stored_config

    @property
    def force_edit(self) -> bool:
        return self.stored_config.force_edit and not TEST_ENV

    @property
    def console_log_level(self) -> int:
        return self.stored_config.console_log_level or self.default_console_log_level

    @property
    def console_log_level_str(self) -> str:
        return self.console_log_levels[self.console_log_level]

    @property
    def console_color(self) -> bool:
        return self.stored_config.console_color

    @property
    def console_show_date(self) -> bool:
        return self.stored_config.console_show_date

    @property
    def console_show_level(self) -> bool:
        return self.stored_config.console_show_level

    @property
    def experimental(self) -> bool:
        return self.stored_config.experimental

    @property
    def experimental_features(self) -> list[str]:
        return []

    @property
    def launch_browser(self) -> bool:
        return self.stored_config.launch_browser and not TEST_ENV

    @property
    def check_beta_versions(self) -> bool:
        return self.stored_config.check_beta_versions

    @property
    def last_notified_version(self) -> Version | None:
        stored_value = self.stored_config.last_notified_version
        if not stored_value:
            return None
        return Version(stored_value)

    @property
    def federation(self) -> Optional['Federation']:
        from data.player import Federation

        if self.stored_config.federation is not None:
            return Federation(self.stored_config.federation)
        else:
            return None

    @property
    def locale(self) -> str:
        return self.stored_config.locale or DEFAULT_LOCALE

    @property
    def date_formatter(self) -> DateFormatter:
        assert self._date_formatter is not None
        return self._date_formatter

    @property
    def default_player_category_set(self) -> 'PlayerCategorySet':
        from data.player_categories import PlayerCategorySet, EVEN_PRESET_CATEGORIES

        return PlayerCategorySet(
            id=-1,
            name=_('U8-U20 / 50+ / 65+'),
            categories=copy(EVEN_PRESET_CATEGORIES),
            is_default=True,
        )

    @property
    def player_category_sets(self) -> list['PlayerCategorySet']:
        from data.player_categories import (
            PlayerCategory,
            PlayerCategorySet,
            ODD_PRESET_CATEGORIES,
        )

        return [
            self.default_player_category_set,
            PlayerCategorySet(
                id=-2,
                name=_('U7-U19 / 50+ / 65+'),
                categories=copy(ODD_PRESET_CATEGORIES),
                is_default=True,
            ),
        ] + [
            PlayerCategorySet(
                id=stored_set.id or 0,
                name=stored_set.name,
                categories=sorted(
                    PlayerCategory.from_id(category_id)
                    for category_id in stored_set.categories
                ),
            )
            for stored_set in self.stored_config.stored_player_category_sets
        ]

    @property
    def tags(self) -> list['Tag']:
        """The event tags defined for this installation, in the order the
        user arranged them in — the order they are listed in everywhere."""
        from data.tag import Tag

        return [
            Tag(id=stored_tag.id or 0, name=stored_tag.name, color=stored_tag.color)
            for stored_tag in self.stored_config.stored_tags
        ]

    @property
    def tags_by_id(self) -> dict[int, 'Tag']:
        return {tag.id: tag for tag in self.tags}

    def resolve_tags(self, tag_ids: list[int]) -> list['Tag']:
        """The tags matching `tag_ids`, in the same order as :attr:`tags`. Ids
        that no longer resolve (a deleted tag, or an event imported from
        another installation) are ignored."""
        wanted = set(tag_ids)
        return [tag for tag in self.tags if tag.id in wanted]

    @property
    def custom_tie_break_sets(self) -> list['TieBreakSet']:
        from data.tie_breaks.sets import TieBreakSet, TieBreakSetSource
        from database.sqlite.event.event_store import StoredTieBreak

        sets: list['TieBreakSet'] = []
        for stored_set in self.stored_config.stored_tie_break_sets:
            stored_tie_breaks = [
                StoredTieBreak(
                    id=None,
                    tournament_id=0,
                    type=item['type'],
                    options=item.get('options', {}),
                    index=index,
                )
                for index, item in enumerate(stored_set.stored_tie_breaks)
            ]
            sets.append(
                TieBreakSet(
                    key=f'custom:{stored_set.id}',
                    name=stored_set.name,
                    source=TieBreakSetSource.CUSTOM,
                    pairing_system_id=stored_set.pairing_system_id,
                    stored_tie_breaks=stored_tie_breaks,
                    custom_set_id=stored_set.id,
                )
            )
        return sets

    # The port used by the Uvicorn web server.
    web_host: str = '0.0.0.0'

    # The ports the web server tries to start on, tried one after the other.
    web_ports: list[int] = (
        ([80, 81, 8080, 8081] if sys.platform != 'linux' else [8080, 8081])
        if not TEST_ENV
        else [9000]
    )

    """ The accepted console log levels. """
    console_log_levels: dict[int, str] = {
        logging.DEBUG: 'DEBUG',
        logging.INFO: 'INFO',
        logging.WARNING: 'WARNING',
        logging.ERROR: 'ERROR',
    }

    # The default console log level, used by default.
    default_console_log_level: int = logging.INFO

    default_pairing_variation_id = 'SWISS_STANDARD'

    """ The URL of the project. """
    web_url: str = 'https://sharly-chess.com'

    """ The URL of the donation website. """
    donate_url: str = 'https://donations.sharly-chess.com'

    """ The contact email. """
    mail: str = 'contact@sharly-chess.com'

    version = SHARLY_CHESS_VERSION

    en_copyright: str = '© Sharly Chess project 2013-2026'

    def localized_copyright(
        self,
        locale: str | None = None,
    ) -> str:
        """The localized copyright of the application."""
        return _(f'© {self.project} 2013-2026', locale=locale)

    @property
    def copyright(self) -> str:
        """The copyright of the application."""
        return self.localized_copyright()

    @property
    def project(self) -> str:
        """The project of the application."""
        return _('Sharly Chess project')

    uniq_id_regex = re.compile(r'^[0-9a-zA-Z_\-]+$')

    # The versions of the libraries for which the version can be easily extracted.
    litestar_version: Version = Version(litestar.__version__.formatted(short=True))
    jinja2_version: Version = Version(jinja2.__version__)
    uvicorn_version: Version = Version(uvicorn.__version__)

    # Other library versions, set manually and checked.
    bootstrap_version = Version('5.3.3')
    bootstrap_icons_version = Version('1.11.3')
    bootstrap5_toggle_version = Version('5.3.3')
    htmx_version = Version('2.0.4')
    htmx_remove_me_version = Version('2.0.0')
    htmx_multi_swap_version = Version('2.0.0')
    htmx_ws_version = Version('2.0.3')
    jquery_version = Version('3.7.1')
    progressbar_js_version = Version('1.1.1')
    sortable_version = Version('1.15.6')
    selectable_version = Version('0.22.0')
    morphdom_version = Version('2.7.4')
    select2_version = Version('4.0.13')
    select2_bootstrap_theme_version = Version('1.3.0')
    air_datepicker_version = Version('3.6.0')

    @property
    def event_database_ext(self) -> Extension:
        return Extension.EVENT_DB

    @overload
    def app_url(self, ip: str) -> str: ...

    @overload
    def app_url(self, ip: None) -> None: ...

    def app_url(self, ip: str | None) -> str | None:
        """Returns the URL of the application for the given IP."""
        if ip is None:
            return None
        return f'http://{ip}{f":{self.web_port}" if self.web_port != 80 else ""}'

    @property
    def lan_ifaces(self) -> list[dict[str, str]]:
        """[{ip, iface, type, label}]"""
        try:
            data = find_lan_interfaces()
            logger.debug('LAN ifaces: %s', data)
            return data
        except Exception as e:
            logger.debug('find_lan_interfaces failed: %s', e)
            return []

    @property
    def lan_ips(self) -> list[str]:
        return [d['ip'] for d in self.lan_ifaces]

    @property
    def local_ip(self) -> str:
        """Returns the local IP (localhost) of the server (with arbiter access)."""
        return LOCALHOST_IP

    @property
    def lan_urls(self) -> list[str]:
        return [self.app_url(ip_info['ip']) for ip_info in self.lan_ifaces]

    @property
    def local_url(self) -> str:
        """The local URL of the application (with arbiter access)."""
        return self.app_url(self.local_ip)

    # The default number of illegal moves to record.
    default_record_illegal_moves: int = 0

    # The default colors for the timers.
    default_timer_colors: dict[int, str] = {
        1: '#00FF00',
        2: '#FF7700',
        3: '#FF0000',
    }

    # The default delays for the timers.
    default_timer_delays: dict[int, int] = {
        1: 15,
        2: 5,
        3: 10,
    }

    # The default text colour for the alert messages.
    default_message_color: str = '#FF0000'

    # The default background colour for the alert messages.
    default_message_background_color: str = '#FFFF00'

    # The default delay between pages on rotators (in seconds).
    default_rotator_delay: int = 1 if TEST_ENV else 15

    # The delay before checking if a user screen page has changed.
    user_screen_update_delay: int = 1 if TEST_ENV else 10

    # The error background image.
    error_background_image: str = '/static/images/sharly-chess-error.png'

    # The default event background colour.
    default_background_color: str = '#ffffff'

    # The default background colour for arbiter pages.
    admin_background_color: str = ''

    # The default background colour for user pages.
    user_background_color: str = default_background_color

    # The maximum number of results shown on results screens (0 = no limit).
    default_results_screen_limit: int = 0

    # The age of the oldest results shown on results screens (in minutes).
    default_results_screen_max_age: int = 60

    # The default first board number for tournaments.
    default_first_board_number: int = 1

    # The default result for players paired bye.
    default_paired_bye_result: Result = Result.WIN

    # The default maximum number of byes for a player in a tournament.
    default_max_byes: int = 1

    # The default last rounds of tournaments where byes are not allowed anymore.
    default_last_rounds_no_byes: int = 3

    default_prize_currency = 'EUR'

    # The test federation, used not to need to set the federation when entering the application
    tests_federation: str = 'FID'

    # The federation used when the application runs without its window, where
    # the federation is chosen otherwise.
    default_federation: str = 'FID'

    @property
    def federations(self) -> dict[str, str]:
        """Get the federation names. To avoid translating all
        the names multiple times the values are stored by locale."""
        locale_ = get_locale()
        if locale_ not in self._federations_by_locale:
            self._federations_by_locale[locale_] = self._get_localized_federations()
        return self._federations_by_locale[locale_]

    @staticmethod
    def _get_localized_federations() -> dict[str, str]:
        return {
            'NON': _('None *** FEDERATION'),
            'FID': _('International Chess Federation'),
            'AFG': _('Afghanistan'),
            'AHO': _('Netherlands Antilles'),
            'ALB': _('Albania'),
            'ALG': _('Algeria'),
            'AND': _('Andorra'),
            'ANG': _('Angola'),
            'ANT': _('Antigua and Barbuda'),
            'ARG': _('Argentina'),
            'ARM': _('Armenia'),
            'ARU': _('Aruba'),
            'AUS': _('Australia'),
            'AUT': _('Austria'),
            'AZE': _('Azerbaijan'),
            'BAH': _('Bahamas'),
            'BAN': _('Bangladesh'),
            'BAR': _('Barbados'),
            'BDI': _('Burundi'),
            'BEL': _('Belgium'),
            'BER': _('Bermuda'),
            'BHU': _('Bhutan'),
            'BIH': _('Bosnia & Herzegovina'),
            'BIZ': _('Belize'),
            'BLR': _('Belarus'),
            'BOL': _('Bolivia'),
            'BOT': _('Botswana'),
            'BRA': _('Brazil'),
            'BRN': _('Bahrain'),
            'BRU': _('Brunei Darussalam'),
            'BUL': _('Bulgaria'),
            'BUR': _('Burkina Faso'),
            'CAF': _('Central African Republic'),
            'CAM': _('Cambodia'),
            'CAN': _('Canada'),
            'CAY': _('Cayman Islands'),
            'CHA': _('Chad'),
            'CHI': _('Chile'),
            'CHN': _('China'),
            'CIV': _('Cote d’Ivoire'),
            'CMR': _('Cameroon'),
            'COD': _('Democratic Republic of the Congo'),
            'COL': _('Colombia'),
            'COM': _('Comoros Islands'),
            'CPV': _('Cape Verde'),
            'CRC': _('Costa Rica'),
            'CRO': _('Croatia'),
            'CUB': _('Cuba'),
            'CUR': _('Curacao'),
            'CYP': _('Cyprus'),
            'CZE': _('Czech Republic'),
            'DEN': _('Denmark'),
            'DJI': _('Djibouti'),
            'DMA': _('Dominica'),
            'DOM': _('Dominican Republic'),
            'ECU': _('Ecuador'),
            'EGY': _('Egypt'),
            'ENG': _('England'),
            'ERI': _('Eritrea'),
            'ESA': _('El Salvador'),
            'ESP': _('Spain'),
            'EST': _('Estonia'),
            'ETH': _('Ethiopia'),
            'FAI': _('Faroe Islands'),
            'FIJ': _('Fiji'),
            'FIN': _('Finland'),
            'FRA': _('France'),
            'GAB': _('Gabon'),
            'GAM': _('Gambia'),
            'GCI': _('Guernsey'),
            'GEO': _('Georgia'),
            'GEQ': _('Equatorial Guinea'),
            'GER': _('Germany'),
            'GHA': _('Ghana'),
            'GRE': _('Greece'),
            'GRL': _('Groenland'),
            'GRN': _('Grenada'),
            'GUA': _('Guatemala'),
            'GUI': _('Guinea'),
            'GUM': _('Guam'),
            'GUY': _('Guyana'),
            'HAI': _('Haiti'),
            'HKG': _('Hong Kong, China'),
            'HON': _('Honduras'),
            'HUN': _('Hungary'),
            'INA': _('Indonesia'),
            'IND': _('India'),
            'IOM': _('Isle of Man'),
            'IRI': _('Iran'),
            'IRL': _('Ireland'),
            'IRQ': _('Iraq'),
            'ISL': _('Iceland'),
            'ISR': _('Israel'),
            'ISV': _('US Virgin Islands'),
            'ITA': _('Italy'),
            'IVB': _('British Virgin Islands'),
            'JAM': _('Jamaica'),
            'JCI': _('Jersey'),
            'JOR': _('Jordan'),
            'JPN': _('Japan'),
            'KAZ': _('Kazakhstan'),
            'KEN': _('Kenya'),
            'KGZ': _('Kyrgyzstan'),
            'KIR': _('Kiribati'),
            'KOR': _('South Korea'),
            'KOS': _('Kosovo'),
            'KSA': _('Saudi Arabia'),
            'KUW': _('Kuwait'),
            'LAO': _('Laos'),
            'LAT': _('Latvia'),
            'LBA': _('Libya'),
            'LBN': _('Lebanon'),
            'LBR': _('Liberia'),
            'LCA': _('Saint Lucia'),
            'LES': _('Lesotho'),
            'LIE': _('Liechtenstein'),
            'LTU': _('Lithuania'),
            'LUX': _('Luxembourg'),
            'MAC': _('Macau, China'),
            'MAD': _('Madagascar'),
            'MAR': _('Morocco'),
            'MAS': _('Malaysia'),
            'MAW': _('Malawi'),
            'MDA': _('Moldova'),
            'MDV': _('Maldives'),
            'MEX': _('Mexico'),
            'MGL': _('Mongolia'),
            'MHL': _('Marshall Islands'),
            'MKD': _('North Macedonia'),
            'MLI': _('Mali'),
            'MLT': _('Malta'),
            'MNC': _('Monaco'),
            'MNE': _('Montenegro'),
            'MOZ': _('Mozambique'),
            'MRI': _('Mauritius'),
            'MTN': _('Mauritania'),
            'MYA': _('Myanmar'),
            'NAM': _('Namibia'),
            'NCA': _('Nicaragua'),
            'NCL': _('New Caledonia'),
            'NED': _('Netherlands'),
            'NEP': _('Nepal'),
            'NGR': _('Nigeria'),
            'NIG': _('Niger'),
            'NOR': _('Norway'),
            'NRU': _('Nauru'),
            'NZL': _('New Zealand'),
            'OMA': _('Oman'),
            'PAK': _('Pakistan'),
            'PAN': _('Panama'),
            'PAR': _('Paraguay'),
            'PER': _('Peru'),
            'PHI': _('Philippines'),
            'PLE': _('Palestine'),
            'PLW': _('Palau'),
            'PNG': _('Papua New Guinea'),
            'POL': _('Poland'),
            'POR': _('Portugal'),
            'PUR': _('Puerto Rico'),
            'QAT': _('Qatar'),
            'ROU': _('Romania'),
            'RSA': _('South Africa'),
            'RUS': _('Russia'),
            'RWA': _('Rwanda'),
            'SCO': _('Scotland'),
            'SEN': _('Senegal'),
            'SEY': _('Seychelles'),
            'SGP': _('Singapore'),
            'SKN': _('Saint Kitts and Nevis'),
            'SLE': _('Sierra Leone'),
            'SLO': _('Slovenia'),
            'SMR': _('San Marino'),
            'SOL': _('Solomon Islands'),
            'SOM': _('Somalia'),
            'SRB': _('Serbia'),
            'SRI': _('Sri Lanka'),
            'SSD': _('South Sudan'),
            'STP': _('Sao Tome and Principe'),
            'SUD': _('Sudan'),
            'SUI': _('Switzerland'),
            'SUR': _('Suriname'),
            'SVK': _('Slovakia'),
            'SWE': _('Sweden'),
            'SWZ': _('Eswatini'),
            'SYR': _('Syria'),
            'TAN': _('Tanzania'),
            'TGA': _('Tonga'),
            'THA': _('Thailand'),
            'TJK': _('Tajikistan'),
            'TKM': _('Turkmenistan'),
            'TLS': _('Timor-Leste'),
            'TOG': _('Togo'),
            'TPE': _('Chinese Taipei'),
            'TTO': _('Trinidad & Tobago'),
            'TUN': _('Tunisia'),
            'TUR': _('Turkiye'),
            'UAE': _('United Arab Emirates'),
            'UGA': _('Uganda'),
            'UKR': _('Ukraine'),
            'URU': _('Uruguay'),
            'USA': _('United States of America'),
            'UZB': _('Uzbekistan'),
            'VAN': _('Vanuatu'),
            'VEN': _('Venezuela'),
            'VIE': _('Vietnam'),
            'VIN': _('Saint Vincent and the Grenadines'),
            'WLS': _('Wales'),
            'YEM': _('Yemen'),
            'ZAM': _('Zambia'),
            'ZIM': _('Zimbabwe'),
        }
