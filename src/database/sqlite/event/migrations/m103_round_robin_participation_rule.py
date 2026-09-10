from database.sqlite.migration import BaseMigration


class Migration(BaseMigration):
    """Adds the round-robin < 50% participation rule flag (FIDE 6.6).

    Existing tournaments keep the rule disabled so their already-computed
    standings do not silently change; new tournaments enable it (the
    dataclass default is ``True``, written explicitly on insert)."""

    def forward(self):
        self.database.execute(
            'ALTER TABLE `tournament` ADD `round_robin_participation_rule` '
            'INTEGER NOT NULL DEFAULT 0'
        )

    def backward(self):
        self.database.execute(
            'ALTER TABLE `tournament` DROP COLUMN `round_robin_participation_rule`'
        )
