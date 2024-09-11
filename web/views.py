from datetime import datetime
from logging import Logger
from pathlib import Path
from typing import Annotated

from litestar import get, Controller
from litestar.contrib.htmx.request import HTMXRequest
from litestar.contrib.htmx.response import HTMXTemplate
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Template, Redirect

from common import RGB, check_rgb_str
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from web.messages import Message
from web.urls import index_url

logger: Logger = get_logger()


class WebContext:
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        self.request = request
        self.data = data
        self.error: Redirect | Template | None = None

    @property
    def _background_url(self) -> str:
        return PapiWebConfig().default_background_url

    @property
    def _background_color(self) -> str:
        return PapiWebConfig().default_background_color

    @property
    def background_info(self) -> dict[str, str]:
        return {
            'url': self._background_url,
            'color': self._background_color,
        }

    @staticmethod
    def form_data_to_str(data: dict[str, str], field: str, empty_value: str | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        return data[field]

    def _form_data_to_str(self, field: str, empty_value: str | None = None) -> str | None:
        return self.form_data_to_str(self.data, field, empty_value)

    @staticmethod
    def form_data_to_int(
            data: dict[str, str], field: str, empty_value: int | None = None, minimum: int = None) -> int | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        int_val = int(data[field])
        if minimum is not None and int_val < minimum:
            raise ValueError(f'{int_val} < {minimum}')
        return int_val

    def _form_data_to_int(self, field: str, empty_value: int | None = None, minimum: int = None) -> int | None:
        return self.form_data_to_int(self.data, field, empty_value, minimum)

    @staticmethod
    def form_data_to_float(
            data: dict[str, str], field: str, empty_value: float | None = None, minimum: float = None) -> float | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip()
        if not data[field]:
            return empty_value
        float_val = float(data[field])
        if minimum is not None and float_val < minimum:
            raise ValueError(f'{float_val} < {minimum}')
        return float_val

    def _form_data_to_float(self, field: str, empty_value: str | None = None, minimum: float = None) -> float | None:
        return self.form_data_to_float(self.data, field, empty_value, minimum)

    @staticmethod
    def form_data_to_bool(data: dict[str, str], field: str, empty_value: bool | None = None) -> bool | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return data[field] in ['true', 'on', ]

    def _form_data_to_bool(self, field: str, empty_value: str | None = None) -> bool | None:
        return self.form_data_to_bool(self.data, field, empty_value)

    @staticmethod
    def form_data_to_rgb(data: dict[str, str], field: str, empty_value: RGB | None = None) -> str | None:
        data[field] = data.get(field, '')
        if data[field] is not None:
            data[field] = data[field].strip().lower()
        if not data[field]:
            return empty_value
        return check_rgb_str(data[field])

    def _form_data_to_rgb(self, field: str, empty_value: RGB | None = None) -> str | None:
        return self.form_data_to_rgb(self.data, field, empty_value)

    @staticmethod
    def value_to_form_data(value: str | int | bool | Path | None) -> str | None:
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bool):
            return 'on' if value else ''
        if isinstance(value, int):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        raise ValueError

    @staticmethod
    def value_to_datetime_form_data(value: float | None) -> str | None:
        if value is None:
            return ''
        return datetime.strftime(datetime.fromtimestamp(value), '%Y-%m-%dT%H:%M')

    def _redirect_error(self, errors: str | list[str]):
        self.error = AController.redirect_error(self.request, errors)

    @property
    def admin_auth(self) -> bool:
        if self.request.client.host == '127.0.0.1':
            return True
        return False


class AController(Controller):

    @staticmethod
    def redirect_error(request: HTMXRequest, errors: str | list[str]) -> Redirect:
        Message.error(request, errors)
        return Redirect(path=index_url(request))

    @staticmethod
    def _render_messages(request: HTMXRequest) -> Template:
        return HTMXTemplate(
            template_name='messages.html',
            re_swap='afterbegin',
            re_target='#messages',
            context={
                'messages': Message.messages(request),
            })


class IndexController(AController):

    @get(
        path='/',
        name='index'
    )
    async def index(self, request: HTMXRequest, ) -> Template:
        web_context: WebContext = WebContext(request, {})
        return HTMXTemplate(
            template_name="index.html",
            context={
                'papi_web_config': PapiWebConfig(),
                'admin_auth': web_context.admin_auth,
                'messages': Message.messages(request),
                'background_info': web_context.background_info,
            })

    @get(
        path='/favicon.ico',
        name='favicon'
    )
    async def favicon(self, request: HTMXRequest, ) -> Redirect:
        return Redirect(request.app.route_reverse('static', file_path='/images/papi-web.ico'))
