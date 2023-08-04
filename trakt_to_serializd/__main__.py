import logging

import click

from trakt_to_serializd.migrator import Migrator


@click.command()
@click.option('--no-credentials-store', is_flag=True, help='Disables storage of user credentials')
@click.option('--debug', is_flag=True, help='Enables debug logging')
def cli(no_credentials_store: bool, debug: bool):
    migrator = Migrator(not no_credentials_store)
    if debug:
        migrator.logger.setLevel(logging.DEBUG)

    migrator.main()


if __name__ == '__main__':
    cli()
