import argparse
import sys

from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_VERSION
from ffe.ffe_engine import FFEEngine
from web.server_engine import ServerEngine
from logging import Logger
from logger import get_logger

logger: Logger = get_logger()

logger.info('Papi-web {} Copyright {}'.format(PAPI_WEB_VERSION, PAPI_WEB_COPYRIGHT))
parser = argparse.ArgumentParser()
parser.add_argument('-s', '--server', help='start the web server', action='store_true')
parser.add_argument('-f', '--ffe', help='run the FFE utilities', action='store_true')
args = parser.parse_args()
if args.server:
    se: ServerEngine = ServerEngine()
elif args.ffe:
    fe: FFEEngine = FFEEngine()
else:
    parser.print_help(sys.stderr)
