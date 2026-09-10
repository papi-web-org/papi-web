from database.sqlite.migration import BaseMigration


class Migration(BaseMigration):
    """Adds the settings of the event snapshots.

    Snapshots are on by default, so the column defaults to 1 and the
    installations that already exist are covered by the upgrade as well as
    the new ones.
    """

    def forward(self):
        self.database.execute(
            'ALTER TABLE `info` ADD `snapshot_enabled` INTEGER NOT NULL DEFAULT 1'
        )
        self.database.execute('ALTER TABLE `info` ADD `snapshot_dir` TEXT')
        self.database.execute(
            'ALTER TABLE `info` ADD '
            '`snapshot_keep_milestones` INTEGER NOT NULL DEFAULT 20'
        )
        self.database.execute(
            'ALTER TABLE `info` ADD `snapshot_keep_auto` INTEGER NOT NULL DEFAULT 10'
        )
        self.database.execute(
            'ALTER TABLE `info` ADD '
            '`snapshot_max_total_mb` INTEGER NOT NULL DEFAULT 500'
        )
        self.database.execute(
            'ALTER TABLE `info` ADD `snapshot_max_age_days` INTEGER NOT NULL DEFAULT 90'
        )

    def backward(self):
        self.database.execute('ALTER TABLE `info` DROP COLUMN `snapshot_max_age_days`')
        self.database.execute('ALTER TABLE `info` DROP COLUMN `snapshot_max_total_mb`')
        self.database.execute('ALTER TABLE `info` DROP COLUMN `snapshot_keep_auto`')
        self.database.execute(
            'ALTER TABLE `info` DROP COLUMN `snapshot_keep_milestones`'
        )
        self.database.execute('ALTER TABLE `info` DROP COLUMN `snapshot_dir`')
        self.database.execute('ALTER TABLE `info` DROP COLUMN `snapshot_enabled`')
