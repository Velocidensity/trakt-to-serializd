import logging

import click

from trakt_to_serializd.credentials import CredentialHelper
from trakt_to_serializd.migrator import Migrator


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option('--no-credentials-store', is_flag=True, help='Disables storage of user credentials')
@click.option('--debug', is_flag=True, help='Enables debug logging')
def migrate(no_credentials_store: bool, debug: bool) -> None:
    """Runs Trakt to Serializd migrator"""
    migrator = Migrator(not no_credentials_store)
    if debug:
        migrator.logger.setLevel(logging.DEBUG)

    migrator.main()


@cli.command()
def clean() -> None:
    """Removes saved Trakt/Serializd credentials"""
    for service in ('trakt', 'serializd'):
        CredentialHelper(service).remove()

    CredentialHelper.remove_folder()
    print('Credential files have been removed.')


if __name__ == '__main__':
    cli()
