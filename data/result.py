import re
from datetime import datetime
from functools import total_ordering
from logging import Logger
from pathlib import Path

from common.config_reader import TMP_DIR
from common.logger import get_logger
from database.papi import RESULT_STRINGS

logger: Logger = get_logger()


@total_ordering
class Result:
    def __init__(
            self, timestamp: float, tournament_id: str, round: int, board_id: int,
            white_player: str, black_player: str, result: int):
        self.__timestamp: float = timestamp
        self.__tournament_id: str = tournament_id
        self.__round: int = round
        self.__board_id: int = board_id
        self.__white_player: str = white_player
        self.__black_player: str = black_player
        self.__result: int = result

    @property
    def timestamp(self) -> float:
        return self.__timestamp

    @property
    def timestamp_str(self) -> str:
        return datetime.fromtimestamp(self.__timestamp).strftime('%H:%M')

    @property
    def tournament_id(self) -> str:
        return self.__tournament_id

    @property
    def round(self) -> int:
        return self.__round

    @property
    def board_id(self) -> int:
        return self.__board_id

    @property
    def white_player(self) -> str:
        return self.__white_player

    @property
    def black_player(self) -> str:
        return self.__black_player

    @property
    def result(self) -> int:
        return self.__result

    @property
    def result_str(self) -> str:
        return RESULT_STRINGS[self.result] if self.result else ''

    def __lt__(self, other):
        # p1 < p2 calls p1.__lt__(p2)
        return self.timestamp < other.timestamp

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        return self.timestamp == other.timestamp

    def __repr__(self):
        return (f'{type(self).__name__}('
                f'{self.timestamp_str} {self.tournament_id}.{self.board_id} '
                f'{self.white_player} {self.result_str} {self.black_player})')

    @classmethod
    def results_dir(cls, event_id: str) -> Path:
        return Path(TMP_DIR, event_id, 'results')

    @classmethod
    def get_results(cls, event_id: str, limit: int) -> list['Result']:
        results: list[Result] = []
        results_dir: Path = cls.results_dir(event_id)
        if not results_dir.is_dir():
            return results
        files: list[Path] = list(results_dir.glob("*"))
        if not reversed(files):
            return results
        prog = re.compile('^([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+) ([^ ]+)$')
        for file in files:
            matches = prog.match(Path(file).name)
            if not matches:
                logger.warning(f'invalid result filename [{file}]')
                continue
            group: int = 1
            timestamp: float
            try:
                timestamp = float(matches.group(group))
            except ValueError:
                logger.warning(f'invalid timestamp [{matches.group(group)}] for result file [{file}]')
                continue
            group += 1
            tournament_id: str = matches.group(group)
            group += 1
            round: int
            try:
                round = int(matches.group(group))
            except ValueError:
                logger.warning(f'invalid round number [{matches.group(group)}] for result file [{file}]')
                continue
            group += 1
            board_id: int
            try:
                board_id = int(matches.group(group))
            except ValueError:
                logger.warning(f'invalid board id [{matches.group(group)}] for result file [{file}]')
                continue
            group += 1
            white_player: str = matches.group(group).replace('_', ' ')
            group += 1
            black_player: str = matches.group(group).replace('_', ' ')
            group += 1
            result: int
            try:
                result = int(matches.group(group))
                if result not in RESULT_STRINGS:
                    logger.warning(f'invalid result [{matches.group(group)}] for result file [{file}]')
                    continue
            except ValueError:
                logger.warning(f'invalid result [{matches.group(group)}] for result file [{file}]')
                continue
            results.append(Result(timestamp, tournament_id, round, board_id, white_player, black_player, result))
            if limit and len(results) > limit:
                break
        return results
