import logging

import click
from rich.console import Console
from rich.prompt import Prompt, Confirm
from serializd import SerializdClient
from serializd.exceptions import LoginError

from trakt_to_serializd.credentials import CredentialHelper
from trakt_to_serializd.migrator import Migrator, MigrationCache


console = Console()


@click.group()
def cli() -> None:
    pass


def _login_serializd() -> tuple[SerializdClient, str]:
    """Login to Serializd and return (client, username)."""
    serializd_auth = CredentialHelper('serializd')
    serializd_auth.load()
    serializd = SerializdClient()
    username = None
    
    if token := serializd_auth.get('token'):
        result = serializd.check_token(token)
        if result.isValid:
            serializd.load_token(token, check=False)
            username = result.username
    
    if not serializd.access_token:
        console.print('[yellow]Please log in to Serializd[/yellow]')
        email = Prompt.ask('Enter Serializd email')
        password = Prompt.ask('Enter Serializd password (will not be echoed)', password=True)
        
        login_result = serializd.login(email=email, password=password)
        username = login_result.username
        serializd_auth['token'] = serializd.access_token
        serializd_auth.save()
    
    return serializd, username


def _populate_cache_if_needed(serializd: SerializdClient, username: str) -> None:
    """Populate cache from Serializd diary if cache is empty."""
    cache = MigrationCache()
    
    if cache.count() > 0:
        console.print(f'[dim]Cache has {cache.count()} entries, skipping diary fetch[/dim]')
        return
    
    console.print('[blue]Fetching existing diary entries to prevent duplicates...[/blue]')
    
    try:
        entries = serializd.get_all_diary_entries(username)
        if entries:
            added = cache.populate_from_diary(entries)
            cache.save()
            console.print(f'[green]Loaded {added} existing diary entries into cache[/green]')
    except Exception as e:
        console.print(f'[yellow]Could not fetch diary (will continue anyway): {e}[/yellow]')


@cli.command()
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--skip-cache-check', is_flag=True, help='Skip pre-populating cache from Serializd diary')
def migrate(debug: bool, skip_cache_check: bool) -> None:
    """Migrate all Trakt watch history to Serializd.
    
    This will:
    - Fetch your complete watch history from Trakt (including rewatches)
    - Preserve original watch dates in Serializd diary
    - Skip episodes that were already migrated
    - Handle rewatches by creating multiple diary entries
    
    Just run this command and follow the prompts!
    """
    console.print('[bold blue]Trakt → Serializd Migration[/bold blue]\n')
    
    # Pre-populate cache from Serializd if needed
    if not skip_cache_check:
        try:
            serializd, username = _login_serializd()
            console.print(f'[green]Logged in to Serializd as {username}[/green]')
            _populate_cache_if_needed(serializd, username)
        except LoginError as e:
            console.print(f'[red]Failed to log in to Serializd: {e}[/red]')
            return
        except Exception as e:
            console.print(f'[yellow]Warning: {e}[/yellow]')
    
    console.print('')
    
    # Run migration with full features (dates + rewatches)
    migrator = Migrator(use_credentials_store=True, with_dates=True)
    if debug:
        migrator.logger.setLevel(logging.DEBUG)

    migrator.main()


@cli.command('refresh-cache')
def refresh_cache() -> None:
    """Re-fetch diary entries from Serializd to update local cache.
    
    Use this if you manually added entries to Serializd and want to
    update the local cache before running migrate again.
    """
    try:
        serializd, username = _login_serializd()
        console.print(f'[green]Logged in as {username}[/green]')
    except LoginError as e:
        console.print(f'[red]Failed to log in: {e}[/red]')
        return
    
    console.print('[blue]Fetching all diary entries...[/blue]')
    
    try:
        entries = serializd.get_all_diary_entries(username)
    except Exception as e:
        console.print(f'[red]Failed to fetch diary: {e}[/red]')
        return
    
    console.print(f'[green]Found {len(entries)} diary entries[/green]')
    
    cache = MigrationCache()
    existing = cache.count()
    added = cache.populate_from_diary(entries)
    cache.save()
    
    console.print(f'[green]Cache updated: {added} new entries added[/green]')
    console.print(f'[blue]Total cache size: {cache.count()} entries[/blue]')


@cli.command('cleanup-duplicates')
@click.option('--dry-run', is_flag=True, help='Preview what would be deleted without deleting')
def cleanup_duplicates(dry_run: bool) -> None:
    """Find and remove duplicate diary entries in Serializd.
    
    If the same episode was logged multiple times on the same date,
    keeps the oldest entry and removes the duplicates.
    """
    from collections import defaultdict
    from rich.progress import track

    try:
        serializd, username = _login_serializd()
        console.print(f'[green]Logged in as {username}[/green]')
    except LoginError as e:
        console.print(f'[red]Failed to log in: {e}[/red]')
        return
    
    console.print('[blue]Fetching all diary entries...[/blue]')
    
    try:
        entries = serializd.get_all_diary_entries(username)
    except Exception as e:
        console.print(f'[red]Failed to fetch diary: {e}[/red]')
        return
    
    console.print(f'[green]Found {len(entries)} diary entries[/green]')
    
    # Group by (show, season, episode, date)
    groups = defaultdict(list)
    for e in entries:
        backdate = e.get('backdate') or e.get('createdAt', '')
        date_part = backdate[:10] if backdate else 'unknown'
        key = (e.get('showId'), e.get('seasonId'), e.get('episodeNumber'), date_part)
        groups[key].append(e)
    
    # Find duplicates
    duplicates = {k: v for k, v in groups.items() if len(v) > 1}
    
    if not duplicates:
        console.print('[green]No duplicate entries found![/green]')
        return
    
    # Get IDs to delete (keep oldest by dateAdded)
    entries_to_delete = []
    for key, entries_list in duplicates.items():
        sorted_entries = sorted(entries_list, key=lambda x: x.get('dateAdded', ''))
        for e in sorted_entries[1:]:
            entries_to_delete.append(e)
    
    console.print(f'[yellow]Found {len(duplicates)} duplicate groups[/yellow]')
    console.print(f'[yellow]Total entries to delete: {len(entries_to_delete)}[/yellow]')
    
    # Show sample
    console.print('\n[bold]Sample of entries to delete:[/bold]')
    for e in entries_to_delete[:5]:
        console.print(
            f"  - {e.get('showName', 'Unknown')} S{e.get('seasonId')} E{e.get('episodeNumber')} "
            f"(added {e.get('dateAdded', 'unknown')[:10]})"
        )
    if len(entries_to_delete) > 5:
        console.print(f'  ... and {len(entries_to_delete) - 5} more')
    
    if dry_run:
        console.print('\n[yellow]Dry run - no entries were deleted[/yellow]')
        return
    
    # Confirm before deletion
    if not Confirm.ask(f'\nDelete {len(entries_to_delete)} duplicate entries?'):
        console.print('[yellow]Cancelled[/yellow]')
        return
    
    # Delete duplicates
    deleted = 0
    failed = 0
    for entry in track(entries_to_delete, description='Deleting duplicates...'):
        try:
            if serializd.delete_diary_entry(entry['id']):
                deleted += 1
            else:
                failed += 1
        except Exception as e:
            console.print(f'[red]Failed to delete {entry["id"]}: {e}[/red]')
            failed += 1
    
    console.print(f'\n[green]Successfully deleted {deleted} duplicate entries[/green]')
    if failed > 0:
        console.print(f'[red]Failed to delete {failed} entries[/red]')


@cli.command()
def clean() -> None:
    """Removes saved Trakt/Serializd credentials"""
    for service in ('trakt', 'serializd'):
        CredentialHelper(service).remove()

    CredentialHelper.remove_folder()
    print('Credential files have been removed.')


if __name__ == '__main__':
    cli()
