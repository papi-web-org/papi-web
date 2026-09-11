from database.sqlite.migration import BaseMigration


class Migration(BaseMigration):
    """Gives the installation what it needs to open an event to the internet.

    Everything here belongs to the machine rather than to any event. A tunnel
    reaches the server, and the server serves every event on it, so being
    reachable is one decision for the installation rather than one per event.

    The key is what the relay recognises a laptop by, so that one can be
    recognised and a lost one disowned without disturbing what it was serving.
    The account is who the server is opened under: an arbiter signs in once on
    the laptop they are working from. The identity is what the address is
    issued against, so that the address is the same every time this server is
    reachable.

    The columns hold nothing until remote access is first used, so an
    installation that never opens itself to the internet holds none of it.
    """

    def forward(self):
        self.database.execute('ALTER TABLE `info` ADD `remote_install_id` TEXT')
        self.database.execute(
            'ALTER TABLE `info` ADD `remote_install_private_key` TEXT'
        )
        self.database.execute('ALTER TABLE `info` ADD `remote_install_public_key` TEXT')
        self.database.execute('ALTER TABLE `info` ADD `remote_access_token` TEXT')
        self.database.execute(
            'ALTER TABLE `info` ADD `remote_access_refresh_token` TEXT'
        )
        self.database.execute(
            'ALTER TABLE `info` ADD `remote_access_token_expires_at` REAL'
        )
        self.database.execute('ALTER TABLE `info` ADD `remote_access` INTEGER')
        self.database.execute('ALTER TABLE `info` ADD `remote_uniq_id` TEXT')

    def backward(self):
        self.database.execute('ALTER TABLE `info` DROP COLUMN `remote_uniq_id`')
        self.database.execute('ALTER TABLE `info` DROP COLUMN `remote_access`')
        self.database.execute(
            'ALTER TABLE `info` DROP COLUMN `remote_access_token_expires_at`'
        )
        self.database.execute(
            'ALTER TABLE `info` DROP COLUMN `remote_access_refresh_token`'
        )
        self.database.execute('ALTER TABLE `info` DROP COLUMN `remote_access_token`')
        self.database.execute(
            'ALTER TABLE `info` DROP COLUMN `remote_install_public_key`'
        )
        self.database.execute(
            'ALTER TABLE `info` DROP COLUMN `remote_install_private_key`'
        )
        self.database.execute('ALTER TABLE `info` DROP COLUMN `remote_install_id`')
