from database.sqlite.migration import BaseMigration

_AUTOMATIC_PAIRING_PREFIXES = (
    'ROUND_ROBIN_',
    'TEAM_ROUND_ROBIN_',
    'SCHEVENINGEN_',
)


class Migration(BaseMigration):
    """Record a knock-out's manually designated match winners: the team that
    advances from a level team match, and the player from a drawn individual
    game, when no computed tie-break settles it.

    Also marks the round count of a never-paired round-robin or Scheveningen as
    unset. These systems work their count out from the field, and their round
    field was stored with a placeholder while it was greyed out; the count is
    now read as an arbiter's schedule whenever it is not zero, and a placeholder
    left in place would be taken for a deliberate one."""

    def forward(self):
        self.database.execute(
            'ALTER TABLE `team_board` ADD `knockout_winner_team_id` INTEGER'
        )
        self.database.execute(
            'ALTER TABLE `board` ADD `knockout_winner_player_id` INTEGER'
        )
        conditions = ' OR '.join(
            "`pairing` LIKE '" + prefix + "%'" for prefix in _AUTOMATIC_PAIRING_PREFIXES
        )
        self.database.execute(
            'UPDATE `tournament` SET `rounds` = 0 '
            f'WHERE ({conditions}) AND `rounds` != 0 AND `id` NOT IN '
            '(SELECT DISTINCT `tournament_id` FROM `pairing`)'
        )

    def backward(self):
        self.database.execute(
            'ALTER TABLE `team_board` DROP COLUMN `knockout_winner_team_id`'
        )
        self.database.execute(
            'ALTER TABLE `board` DROP COLUMN `knockout_winner_player_id`'
        )
