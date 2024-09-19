from logging import Logger
from typing import Annotated

import validators
from litestar import post
from litestar.contrib.htmx.request import HTMXRequest
from litestar.enums import RequestEncodingType, MediaType
from litestar.params import Body

from common.background import BackgroundUtils
from common.logger import get_logger
from common.papi_web_config import PapiWebConfig
from web.controllers.index_controller import WebContext, AbstractController

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
            self.background['url'] = f'url({BackgroundUtils.inline_image_url(image)})'


class BackgroundController(AbstractController):
    """
    The /background URL is called with an image and a color parameter.
    The JSON response contains a color and a url parameter where url is generated from the image (inline data when a
    file in /custom is sent).
    """

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
