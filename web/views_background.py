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
        field: str = 'image'
        image: str = self._form_data_to_str(field, '')
        field: str = 'color'
        color: str = self._form_data_to_str(field, '')
        if not color:
            logger.warning(f'Parameter [{field}] not found (data=[{data}]).')
            color = PapiWebConfig.default_background_color
        self.background: dict[str, str] = {
            'color': color,
        }
        if not image:
            self.background['url'] = ''
        elif image.startswith('/') or validators.url(image):
            self.background['url'] = f'url({image})'
        else:
            self.background['url'] = f'url({self.inline_image_url(image)})'

    @staticmethod
    def inline_image_url(image: str, ):
        if not image:
            return PapiWebConfig.default_background_image
        if image.startswith('/') or validators.url(image):
            return image
        file: Path = PapiWebConfig.custom_path / image
        try:
            with open(file, 'rb') as f:
                data: bytes = f.read()
            encoded_data: str = base64.b64encode(data).decode('utf-8')
            return f'data:image/{file.suffix};base64,{encoded_data}'
        except FileNotFoundError:
            logger.warning(f'Le fichier [{file}] n\'existe pas.')
            return PapiWebConfig.error_background_image


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
