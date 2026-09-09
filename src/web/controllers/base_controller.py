import tempfile
from collections.abc import Callable, Mapping
from itertools import cycle
from math import isfinite
import re
import time
from datetime import datetime, date
from logging import Logger
from pathlib import Path
from typing import Any

from httpdate.httpdate import httpdate_to_unixtime, unixtime_to_httpdate
from litestar.datastructures import UploadFile
from litestar.plugins.htmx import HTMXRequest, HTMXTemplate
from litestar.controller import Controller
from litestar.response import Template
from typing_extensions import TYPE_CHECKING

from common import check_rgb_str, DEVEL_ENV
from common.exception import FormError
from common.i18n import (
    set_locale,
    locales,
    _,
)
from common.i18n.utils import (
    locale_localized_name,
    locale_flag_url,
)
from common.logger import get_logger
from common.sharly_chess_config import SharlyChessConfig
from data.access_levels.client_tracker import ClientTracker
from data.player import Federation, Club
from utils import Utils
from utils.date_time import format_date, format_date_range, format_datetime
from web.messages import Message

if TYPE_CHECKING:
    from web.session import BoolSessionVariable

logger: Logger = get_logger()


class WebContext:
    """
    The basic web context, inherited by all the web contexts of the application.
    Web contexts are used by controllers to get the context of the request based on the payload data received.
    """

    def __init__(self, request: HTMXRequest, reload_client: bool = False):
        from web.utils import RequestUtils
        from web.session import SessionLocale

        self.request: HTMXRequest = request
        self.client = RequestUtils.get_client(request, reload_client)
        # sets the session locale to the thread
        set_locale(SessionLocale(request).get())
        if request.client:
            # tracks the visit of the client
            ClientTracker().track_client(request.client.host)
        else:
            logger.warning('Request with no client!')

    @property
    def background_color(self) -> str:
        """
        Override this method to make the background colour different from the default.
        :return:
        """
        return SharlyChessConfig.default_background_color

    @property
    def background_info(self) -> dict[str, str]:
        """
        The information returned by this method is passed to the template engine so the client applies the page
        background colour.
        This method should not be overridden (instead override background_color()).
        :return: a dict with a color.
        """
        return {
            'color': self.background_color,
        }

    @property
    def theme(self) -> str:
        """
        Override this method to change the theme
        :return:
        """
        return 'light'

    @staticmethod
    def flatten_list_data(data: Mapping[str, str | list[str]]) -> dict[str, str]:
        return {
            key: value if isinstance(value, str) else ';'.join(value)
            for key, value in data.items()
        }

    @classmethod
    async def normalize_multipart_data(cls, data: dict[str, Any]) -> dict[str, str]:
        normalized_data: dict[str, str] = {}
        for key, value in data.items():
            if isinstance(value, UploadFile):
                file_path = Path(tempfile.mkdtemp()) / value.filename
                file_path.write_bytes(await value.read())
                normalized_data[key] = str(file_path)
            else:
                normalized_data[key] = cls.value_to_form_data(value)
        return normalized_data

    @classmethod
    def form_data_to_value[T](
        cls,
        data: dict[str, str],
        field: str,
        expected_type: T,
    ) -> T | None:
        type_functions: dict[type, Callable] = {
            str: cls.form_data_to_str,
            int: cls.form_data_to_int,
            float: cls.form_data_to_float,
            bool: cls.form_data_to_bool,
            date: cls.form_data_to_date,
            list[int]: cls.form_data_to_list_int,
            list[str]: cls.form_data_to_list_str,
            Path: cls.form_data_to_path,
        }
        for type_, function in type_functions.items():
            if expected_type in (type_, type_ | None):
                return function(data, field)
        raise ValueError(f'Unsupported type: {expected_type}')

    @staticmethod
    def form_data_to_str(
        data: dict[str, str] | None, field: str, empty_value: str | None = None
    ) -> str | None:
        """Transforms given `data`'s value in `field` into a stripped
        str. If it is empty, returns `empty_value`."""
        if data is None:
            return empty_value
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    @staticmethod
    def form_data_to_int(
        data: dict[str, str] | None,
        field: str,
        empty_value: int | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int | None:
        """Transforms `data`'s value in `field` into a base-10 integer.
        If the value is empty, returns `empty_value`.
        If it is not empty but is not in base-10 integer format, raises
        a `ValueError.
        If `minimum` is not `None`, and the value is not greater or equal to
        `minimum`, raise `ValueError`."""
        if data is None:
            return empty_value
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        int_val = int(data[field])
        if minimum is not None and int_val < minimum:
            raise ValueError(f'{int_val} < {minimum}')
        if maximum is not None and int_val > maximum:
            raise ValueError(f'{int_val} > {maximum}')
        return int_val

    @staticmethod
    def form_data_to_float(
        data: dict[str, str] | None,
        field: str,
        empty_value: float | None = None,
        minimum: float | None = None,
    ) -> float | None:
        if data is None:
            return empty_value
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().replace(',', '.')
        if not data[field]:
            return empty_value
        float_val = float(data[field])
        if minimum is not None and float_val < minimum:
            raise ValueError(f'{float_val} < {minimum}')
        return float_val

    @staticmethod
    def form_data_to_bool(data: dict[str, str] | None, field: str) -> bool:
        if data is None:
            return False
        if field not in data:
            data[field] = 'off'
        return data[field] in ('true', 'on')

    @staticmethod
    def form_data_to_bool_or_none(
        data: dict[str, str] | None, field: str
    ) -> bool | None:
        if data is None or not data.get(field, None):
            return None
        return data[field] in ('true', 'on')

    @staticmethod
    def form_data_to_list_int(
        data: dict[str, str], field: str, empty_value: list[int] | None = None
    ) -> list[int]:
        if field not in data or not data[field]:
            return empty_value or []
        return [int(element) for element in data[field].split(';')]

    @staticmethod
    def form_data_to_list_str(
        data: dict[str, str], field: str, empty_value: list[str] | None = None
    ) -> list[str]:
        if field not in data or not data[field]:
            return empty_value or []
        return [element.strip() for element in data[field].split(';')]

    @staticmethod
    def form_data_to_path(data: dict[str, str], field: str) -> Path | None:
        if field not in data or not data[field]:
            return None
        return Path(data[field])

    @staticmethod
    def form_data_to_rgb(
        data: dict[str, str] | None, field: str, empty_value: str | None = None
    ) -> str | None:
        if data is None:
            return empty_value
        data[field] = data.get(field, '').strip().lower()
        if not data[field]:
            return empty_value
        return check_rgb_str(data[field])

    @staticmethod
    def form_data_to_date(data: dict[str, str], field: str) -> date | None:
        data[field] = data.get(field, '').strip()
        if not data[field]:
            return None
        formatter = SharlyChessConfig().date_formatter
        try:
            return datetime.strptime(data[field], formatter.python_format).date()
        except ValueError:
            raise FormError(
                _('Invalid format (expected: {format}).').format(
                    format=formatter.humanized_format
                )
            )

    @staticmethod
    def form_data_to_datetime(data: dict[str, str], field: str) -> datetime | None:
        data[field] = data.get(field, '').strip()
        formatter = SharlyChessConfig().date_formatter
        if not data[field]:
            return None
        try:
            return datetime.strptime(data[field], formatter.datetime_python_format)
        except ValueError:
            raise FormError(
                _('Invalid format (expected: {format}).').format(
                    format=formatter.datetime_humanized_format
                )
            )

    @staticmethod
    def form_data_to_date_range(
        data: dict[str, str], field: str
    ) -> tuple[date, date] | None:
        data[field] = data.get(field, '').strip()
        if not data[field]:
            return None
        formatter = SharlyChessConfig().date_formatter
        separator = formatter.range_separator
        date_format = formatter.python_format
        if separator not in data[field]:
            try:
                date_ = datetime.strptime(data[field], date_format).date()
                return date_, date_
            except ValueError:
                raise FormError(
                    _('Invalid format (expected: {format}).').format(
                        format=formatter.humanized_format
                    )
                )
        start_date_str, stop_date_str = data[field].split(separator, 1)
        try:
            start_date = datetime.strptime(start_date_str, date_format).date()
            stop_date = datetime.strptime(stop_date_str, date_format).date()
        except ValueError:
            raise FormError(
                _('Invalid format (expected: {format}).').format(
                    format=formatter.range_humanized_format
                )
            )
        if start_date > stop_date:
            return stop_date, start_date
        return start_date, stop_date

    @classmethod
    def form_data_to_mail(cls, data: dict[str, str] | None, field: str) -> str | None:
        if data is None:
            return None
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return None
        if re.match(Utils.EMAIL_REGEX, data[field]):
            return data[field]
        raise ValueError(f'data[{field}]=[{data[field]}] (mail expected)')

    @classmethod
    def value_to_form_data(cls, value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bool):
            return 'on' if value else 'off'
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f'{value:.2f}'.rstrip('0').rstrip('.')
        if isinstance(value, datetime):
            return format_datetime(value)
        if isinstance(value, date):
            return format_date(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Federation):
            return str(value)
        if isinstance(value, Club):
            return str(value)
        if isinstance(value, list) or isinstance(value, set):
            return ';'.join(str(element) for element in value)
        raise ValueError(f'unknown type for value [{value}]')

    @classmethod
    def values_dict_to_form_data(cls, values_dict: dict[str, Any]) -> dict[str, str]:
        return {
            key: cls.value_to_form_data(value) for key, value in values_dict.items()
        }

    @staticmethod
    def value_to_datetime_form_data(value: float | datetime | None) -> str | None:
        if value is None:
            return ''
        if isinstance(value, float):
            return datetime.strftime(datetime.fromtimestamp(value), '%Y-%m-%d %H:%M')
        if isinstance(value, datetime):
            return datetime.strftime(value, '%Y-%m-%d %H:%M')
        raise ValueError(f'unknown type for value [{value}]')

    @staticmethod
    def value_to_date_form_data(value: date | None) -> str:
        if value is None:
            return ''
        return format_date(value)

    @staticmethod
    def value_to_date_range_form_data(
        start_date: date | None = None, stop_date: date | None = None
    ) -> str:
        if not start_date:
            return ''
        return format_date_range(start_date, stop_date)

    @staticmethod
    def resolve_add_other(
        data: dict[str, str], session_variable: 'BoolSessionVariable'
    ) -> bool:
        if 'add_other' in data:
            add_other = True
        elif 'create' in data:
            add_other = False
        else:
            return session_variable.get()
        session_variable.set(add_other)
        return add_other

    @property
    def template_context(self) -> dict[str, Any]:
        """
        This method is used by all controllers to get the parameters to pass the template for rendering.
        Override this method to pass more parameters to the template engine.
        :return: a dict containing named parameters.
        """
        from web.session import SessionLocale

        sharly_chess_config: SharlyChessConfig = SharlyChessConfig()
        now: float = time.time()
        locale_infos: dict[str, Any] = {}
        locale_options: dict[str, str] = {}
        for locale in locales:
            name: str = f'{locale_localized_name(locale)}'
            locale_infos[locale] = {
                'name': name,
                'flag_url': locale_flag_url(locale),
            }
            locale_options[locale] = name
        return {
            'DEVEL_ENV': DEVEL_ENV,
            'now': now,
            'now_http_date': unixtime_to_httpdate(int(now)),
            'sharly_chess_config': sharly_chess_config,
            'background_info': self.background_info,
            'theme': self.theme,
            'locale_infos': locale_infos,
            'locale_options': locale_options,
            'locale': SessionLocale(self.request).get(),
            'client': self.client,
            'user_agent': self.request.headers.get('User-Agent', ''),
            'utils': Utils,
            'has_app_window': self.has_app_window,
        }

    @property
    def has_app_window(self) -> bool:
        """Whether the application runs with a window of its own, which is
        where the settings and the plugins are managed then."""
        from gui.server_gui_toga import SharlyChessServerToga

        return SharlyChessServerToga.instance is not None


class BaseController(Controller):
    """
    The basic controller, inherited by all the controllers of the application.
    Controllers are used to handle web requests and respond to clients.
    """

    @staticmethod
    def _render_modal(
        template_name: str,
        template_context: dict[str, Any],
        keep_modal_opened: bool = False,
    ) -> HTMXTemplate:
        return HTMXTemplate(
            template_name=template_name,
            context=template_context,
            re_target='#modal-wrapper',
            re_swap='innerHTML',
            trigger_event=(
                'static_modal_opened' if keep_modal_opened else 'modal_opened'
            ),
            after='settle',
        )

    @staticmethod
    def render_messages(
        request: HTMXRequest,
    ) -> Template:
        return HTMXTemplate(
            template_name='common/messages.html',
            re_swap='afterbegin',
            re_target='#messages',
            context={
                'messages': Message.messages(request),
            },
        )

    @staticmethod
    def _render_empty_modal_and_messages(
        request: HTMXRequest, after_receive: bool = False
    ) -> HTMXTemplate:
        return HTMXTemplate(
            template_name='common/empty_modal_and_messages.html',
            context={'messages': Message.messages(request)},
            re_target='#modal-wrapper',
            trigger_event='close_modal',
            after='receive' if after_receive else 'settle',
        )

    IF_MODIFIED_SINCE_HEADER: str = 'If-Modified-Since'
    PRECISE_IF_MODIFIED_SINCE_HEADER: str = 'X-Sharly-Chess-If-Modified-Since'

    def get_if_modified_since(self, request: HTMXRequest) -> float | None:
        """
        Return the If-Modified-Since header value of the request.
        If no header found return None.
        If the date is invalid, log a warning and return None.
        Typical usage in a controller:
        if_modified_since: float | None = self.get_if_modified_since(request)
        if date is None or page_refresh_needed(web_context, date):
            return render(web_context)
        else:
            return Reswap(content=None, method='none', status_code=HTTP_304_NOT_MODIFIED)
        """
        precise_modified_since = request.headers.get(
            self.PRECISE_IF_MODIFIED_SINCE_HEADER
        )
        if precise_modified_since is not None:
            try:
                precise_timestamp = float(precise_modified_since)
                if isfinite(precise_timestamp):
                    return precise_timestamp
            except ValueError:
                pass
            logger.warning(
                'Invalid [%s] header [%s]',
                self.PRECISE_IF_MODIFIED_SINCE_HEADER,
                precise_modified_since,
            )
        try:
            http_modified_since = request.headers[self.IF_MODIFIED_SINCE_HEADER]
            logger.debug('%s=%s', self.IF_MODIFIED_SINCE_HEADER, http_modified_since)
            if_modified_since = httpdate_to_unixtime(http_modified_since)
            return if_modified_since
        except KeyError:
            return None
        except ValueError:
            logger.warning(
                'Invalid [%s] header [%s]',
                self.IF_MODIFIED_SINCE_HEADER,
                request.headers[self.IF_MODIFIED_SINCE_HEADER],
            )
            return None

    @staticmethod
    def set_locale(request: HTMXRequest, locale: str | None):
        if locale:
            # sets the locale to the current thread and stores it to the session
            if set_locale(locale):
                from web.session import SessionLocale

                SessionLocale(request).set(locale)

    @staticmethod
    def get_cycler(items: list[str]):
        iter_ = cycle(items)

        def cycler(reset: bool = False):
            nonlocal iter_
            if reset:
                iter_ = cycle(items)
            return next(iter_)

        return cycler
