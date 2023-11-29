import argparse
import sys
from logging import Logger
import os

from chessevent.chessevent_engine import ChessEventEngine
from common.papi_web_config import PAPI_WEB_COPYRIGHT, PAPI_WEB_VERSION
from ffe.ffe_engine import FFEEngine
from test.test_engine import TestEngine
from web.server_engine import ServerEngine
from common.logger import get_logger

try:
    logger: Logger = get_logger()

    logger.info(f'Papi-web {PAPI_WEB_VERSION} Copyright {PAPI_WEB_COPYRIGHT}')
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--server', help='start the web server', action='store_true')
    parser.add_argument('-f', '--ffe', help='run the FFE utilities', action='store_true')
    parser.add_argument('-c', '--chessevent', help='download Papi files from Chess Event', action='store_true')
    parser.add_argument('--path', default='.')
    parser.add_argument('-t', '--test', help='test the configuration', action='store_true')
    args = parser.parse_args()
    os.chdir(args.path)

    if args.server:
        se: ServerEngine = ServerEngine()
    elif args.ffe:
        fe: FFEEngine = FFEEngine()
    elif args.chessevent:
        ce: ChessEventEngine = ChessEventEngine()
    elif args.test:
        te: TestEngine = TestEngine()
    else:
        parser.print_help(sys.stderr)
        logger.error('Ce programme ne devrait pas être lancé directement, utiliser les scripts '
                     'server.bat, ffe.bat et chessevent.bat.')
except KeyboardInterrupt:
    pass
