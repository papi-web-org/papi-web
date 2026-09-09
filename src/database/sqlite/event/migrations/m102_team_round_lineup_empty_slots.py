from database.sqlite.migration import BaseMigration


class Migration(BaseMigration):
    """Lets a team lineup say that a board is empty.

    A lineup holds one row per board, and a board the team leaves empty
    is now a row with no player rather than the absence of a row — so a
    lineup that fields nobody at all is expressible, instead of reading
    as a round with no lineup of its own.

    ``board`` already holds an empty seat as a NULL player (m086); the
    two tables that describe seats now say it the same way.
    """

    # The table is rebuilt, so the ON DELETE rules of the tables it
    # points at must not fire while it is dropped.
    @staticmethod
    def are_foreign_keys_enabled() -> bool:
        return False

    def forward(self):
        self._rebuild_team_round_lineup_table('INTEGER')

    def backward(self):
        # An empty board has no way of being stored once the column is
        # NOT NULL again: such a lineup goes back to reading as a round
        # taking the previous round's.
        self.database.execute(
            'DELETE FROM `team_round_lineup` WHERE `player_id` IS NULL'
        )
        self._rebuild_team_round_lineup_table('INTEGER NOT NULL')

    def _rebuild_team_round_lineup_table(self, player_id_column_type: str):
        self.database.execute(
            'CREATE TABLE `team_round_lineup_new` ('
            '   `team_id` INTEGER NOT NULL,'
            '   `round` INTEGER NOT NULL,'
            f'   `player_id` {player_id_column_type},'
            '   `index` INTEGER NOT NULL,'
            '   PRIMARY KEY (`team_id`, `round`, `index`),'
            '   FOREIGN KEY (`team_id`) REFERENCES '
            '   `team`(`id`) ON DELETE CASCADE,'
            '   FOREIGN KEY (`player_id`) REFERENCES '
            '   `player`(`id`) ON DELETE CASCADE'
            ')'
        )
        self.database.execute(
            'INSERT INTO `team_round_lineup_new` '
            '(`team_id`, `round`, `player_id`, `index`) '
            'SELECT `team_id`, `round`, `player_id`, `index` '
            'FROM `team_round_lineup`'
        )
        self.database.execute('DROP TABLE `team_round_lineup`')
        self.database.execute(
            'ALTER TABLE `team_round_lineup_new` RENAME TO `team_round_lineup`'
        )
