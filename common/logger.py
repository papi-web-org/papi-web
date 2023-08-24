from logging import Logger, getLogger, StreamHandler
from colorlog import ColoredFormatter

logger: Logger = getLogger()


# https://github.com/borntyping/python-colorlog
def configure_logger(level: int):
    # basicConfig(level=level, format='%(levelname)-8s %(message)s')
    handler: StreamHandler = StreamHandler()
    handler.setFormatter(ColoredFormatter(
        fmt='%(log_color)s%(levelname)-8s %(message)s%(reset)s',
        datefmt=None,
        reset=True,
        log_colors={
            'DEBUG': 'white',  # 'cyan',
            'INFO': 'light_white',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_light_white',
        },
        secondary_log_colors={},
        style='%',
    ))
    logger.addHandler(handler)
    logger.setLevel(level)


def get_logger() -> Logger:
    return logger
