import re
import time
from datetime import datetime
from functools import total_ordering
from logging import Logger
from pathlib import Path
from dataclasses import dataclass

from common.config_reader import TMP_DIR
from common.logger import get_logger
from data.util import Result as DataResult

logger: Logger = get_logger()


@dataclass
@total_ordering
class Result:
    timestamp: float
    tournament_id: str
    round: int
    board_id: int
    white_player: str
    black_player: str
    result: DataResult

    @property
    def timestamp_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime('%H:%M')

    @property
    def result_str(self) -> str:
        return str(self.result) if self.result else ''

    def __lt__(self, other):
        # p1 < p2 calls p1.__lt__(p2)
        return self.timestamp < other.timestamp

    def __eq__(self, other):
        # p1 == p2 calls p1.__eq__(p2)
        return self.timestamp == other.timestamp

    def __repr__(self):
        return (f'{self.__class__.__name__}('
                f'{self.timestamp_str} {self.tournament_id}.{self.board_id} '
                f'{self.white_player} {self.result_str} {self.black_player})')

    @classmethod
    def results_dir(cls, event_id: str) -> Path:
        return TMP_DIR / 'events' / event_id / 'results'

    @classmethod
    def get_results(cls, event_id: str, limit: int) -> list['Result']:
        results: list[Result] = []
        results_dir: Path = cls.results_dir(event_id)
        files: list[Path] = list(results_dir.glob("*"))
        # delete too old files
        limit_ts: float = time.time() - 3600
        files_deleted: bool = False
        for file in files:
            if file.lstat().st_ctime < limit_ts:
                file.unlink()
                logger.debug(f'le fichier [{file}] a été supprimé')
                files_deleted = True
        if files_deleted:
            logger.debug('de vieux fichiers de résultat ont été supprimés, rechargement...')
            files = list(results_dir.glob("*"))
        if not reversed(files):
            return results
        prog = re.compile(
                r'^(?P<timestamp>[\d.]+) (?P<tournament_id>[^ ]+) '
                r'(?P<round>\d+) (?P<board_id>\d+) (?P<white_player>[^ ]+) '
                r'(?P<black_player>[^ ]+) (?P<result>[0-6])$')
        for file in files:
            matches = prog.match(Path(file).name)
            if not matches:
                logger.warning(f'invalid result filename [{file}]')
                continue
            group: str = 'timestamp'
            timestamp: float
            try:
                timestamp = float(matches.group(group))
            except ValueError:
                logger.warning(f'invalid timestamp [{matches.group(group)}] for result file [{file}]')
                continue
            group = 'tournament_id'
            tournament_id: str = matches.group(group)
            group = 'round'
            round: int
            try:
                round = int(matches.group(group))
            except ValueError:
                logger.warning(f'invalid round number [{matches.group(group)}] for result file [{file}]')
                continue
            group = 'board_id'
            board_id: int
            try:
                board_id = int(matches.group(group))
            except ValueError:
                logger.warning(f'invalid board id [{matches.group(group)}] for result file [{file}]')
                continue
            group = 'white_player'
            white_player: str = matches.group(group).replace('_', ' ')
            group = 'black_player'
            black_player: str = matches.group(group).replace('_', ' ')
            group = 'result'
            result: int | DataResult
            try:
                result = int(matches.group(group))
                result = DataResult.from_papi_value(result)
            except ValueError:
                logger.warning(f'invalid result [{matches.group(group)}] for result file [{file}]')
                continue
            results.append(Result(timestamp, tournament_id, round, board_id, white_player, black_player, result))
            if limit and len(results) > limit:
                break
        return results
