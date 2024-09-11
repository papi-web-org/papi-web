import base64
from logging import Logger
from pathlib import Path
from typing import Annotated

import validators
from litestar import post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.enums import RequestEncodingType, MediaType
from litestar.params import Body

from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from web.views import WebContext, AController

logger: Logger = get_logger()


class BackgroundWebContext(WebContext):
    def __init__(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ):
        super().__init__(request, data)
        field: str = 'url'
        url: str = self._form_data_to_str(field, '')
        if not url:
            logger.warning(f'Parameter [{field}] not found (data=[{data}]).')
            url = PapiWebConfig().error_background_url
        field: str = 'color'
        color: str = self._form_data_to_str(field, '')
        if not color:
            logger.warning(f'Parameter [{field}] not found (data=[{data}]).')
            color = PapiWebConfig().error_background_color
        if not (url.startswith('/') or validators.url(url)):
            url = self.inline_image_url(url)
        self.background: dict[str, str] = {
            'url': f'url({url})',
            'color': color,
        }

    @staticmethod
    def inline_image_url(url: str, ):
        if not url:
            return PapiWebConfig().default_background_url
        if url.startswith('/') or validators.url(url):
            return url
        file: Path = PapiWebConfig().custom_path / url
        try:
            with open(file, 'rb') as f:
                data: bytes = f.read()
            encoded_data: str = base64.b64encode(data).decode('utf-8')
            return f'data:image/{file.suffix};base64,{encoded_data}'
        except FileNotFoundError:
            logger.warning(f'Le fichier [{file}] n\'existe pas.')
            return PapiWebConfig().error_background_url


class BackgroundController(AController):

    @post(
        path='/background',
        name='background',
        media_type=MediaType.JSON
    )
    async def background(
            self, request: HTMXRequest,
            data: Annotated[dict[str, str], Body(media_type=RequestEncodingType.URL_ENCODED), ],
    ) -> dict[str, str]:
        return BackgroundWebContext(request, data).background
