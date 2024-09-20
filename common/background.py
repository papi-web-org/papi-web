import base64
from logging import Logger
from pathlib import Path

import validators

from common import get_logger
from common.papi_web_config import PapiWebConfig

logger: Logger = get_logger()


def inline_image_url(image: str, ) -> str:
    """
    Return a true URL or
    :param image: an already true-URL (absolute or relative starting by '/') or the path of a custom file
    (a path relative to /custom is expected)
    :return: a true URL (data-inline if a file path is provided)
    """
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
