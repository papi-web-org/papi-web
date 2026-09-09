from database.sqlite.migration import BaseMigration


class Migration(BaseMigration):
    """Lets the plugins that new events enable be chosen.

    The column holds nothing until a plugin is set one way or the other,
    and the plugin then keeps the default it declares itself, so nothing
    has to be written for the installations that already exist.
    """

    def forward(self):
        self.database.execute(
            'ALTER TABLE `plugin` ADD `default_event_is_enabled` INTEGER'
        )

    def backward(self):
        self.database.execute(
            'ALTER TABLE `plugin` DROP COLUMN `default_event_is_enabled`'
        )
