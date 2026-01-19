import json
import logging
import sys
import time
from pathlib import Path
from datetime import datetime

from rich.logging import RichHandler
from rich.progress import track
from rich.prompt import Prompt
from serializd import SerializdClient
from serializd.exceptions import EmptySeasonError, LoginError

from trakt_to_serializd.credentials import CredentialHelper
from trakt_to_serializd.exceptions import TraktError
from trakt_to_serializd.trakt import TraktAPI
from trakt_to_serializd.utils import get_data_directory


class MigrationCache:
    """Tracks which episode watches have been migrated to prevent duplicates.
    
    Stores watch events by date to support rewatches - each unique watch date
    for an episode is tracked separately.
    """

    def __init__(self):
        self.path = get_data_directory() / 'migration_cache.json'
        self.data: set[str] = set()
        self._load()

    def _load(self):
        """Load cache from file."""
        if self.path.exists():
            try:
                with self.path.open('r', encoding='utf-8') as f:
                    self.data = set(json.load(f))
            except (json.JSONDecodeError, TypeError):
                self.data = set()

    def save(self):
        """Save cache to file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('w', encoding='utf-8') as f:
            json.dump(list(self.data), f)

    def _key(self, show_id: int, season_id: int, episode_number: int, watched_date: str | None = None) -> str:
        """Generate unique key for an episode watch event.
        
        Args:
            show_id: TMDB show ID
            season_id: Serializd season ID
            episode_number: Episode number
            watched_date: Date string (YYYY-MM-DD) for the watch event.
                         If None, uses legacy format for backward compatibility.
        """
        if watched_date:
            # Extract just the date part (YYYY-MM-DD) for comparison
            date_part = watched_date[:10] if len(watched_date) >= 10 else watched_date
            return f"{show_id}:{season_id}:{episode_number}:{date_part}"
        # Legacy format for backward compatibility with old cache
        return f"{show_id}:{season_id}:{episode_number}"

    def is_migrated(self, show_id: int, season_id: int, episode_number: int, watched_date: str | None = None) -> bool:
        """Check if an episode watch event has already been migrated.
        
        Args:
            show_id: TMDB show ID
            season_id: Serializd season ID
            episode_number: Episode number
            watched_date: If provided, checks for this specific watch date only.
                         If None, checks if episode was ever migrated (legacy).
        """
        if watched_date:
            # When a date is provided, ONLY check the date-specific key.
            # This allows rewatches to be migrated even if the episode
            # was previously migrated with the legacy (dateless) key.
            date_key = self._key(show_id, season_id, episode_number, watched_date)
            return date_key in self.data
        
        # Legacy check - episode migrated at any date (for backward compatibility)
        legacy_key = self._key(show_id, season_id, episode_number)
        return legacy_key in self.data

    def mark_migrated(self, show_id: int, season_id: int, episode_number: int, watched_date: str | None = None):
        """Mark an episode watch event as migrated.
        
        Args:
            show_id: TMDB show ID
            season_id: Serializd season ID
            episode_number: Episode number  
            watched_date: Date of the watch event. If None, uses legacy format.
        """
        self.data.add(self._key(show_id, season_id, episode_number, watched_date))
        # Also add legacy key for backward compatibility
        if watched_date:
            self.data.add(self._key(show_id, season_id, episode_number))

    def count(self) -> int:
        """Return number of migrated episodes."""
        return len(self.data)

    def populate_from_diary(self, diary_entries: list[dict]) -> int:
        """
        Populate cache from Serializd diary entries.
        
        Args:
            diary_entries: List of diary entry dicts from Serializd API
            
        Returns:
            Number of entries added to cache
        """
        added = 0
        for entry in diary_entries:
            show_id = entry.get('showId')
            season_id = entry.get('seasonId')
            episode_number = entry.get('episodeNumber')
            # Get the diary date (backdated or created date)
            backdate = entry.get('backdate') or entry.get('createdAt')
            
            if show_id and season_id and episode_number:
                # Add with date for rewatch tracking
                if backdate:
                    key = self._key(show_id, season_id, episode_number, backdate)
                    if key not in self.data:
                        self.data.add(key)
                        added += 1
                # Also add legacy key
                legacy_key = self._key(show_id, season_id, episode_number)
                if legacy_key not in self.data:
                    self.data.add(legacy_key)
        return added


class Migrator:
    def __init__(self, use_credentials_store: bool = True, with_dates: bool = False):
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            format='%(message)s',
            datefmt='[%X]',
            handlers=[RichHandler(rich_tracebacks=True)]
        )
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)

        self.use_credentials_store = use_credentials_store
        self.with_dates = with_dates
        self.trakt_auth = CredentialHelper('trakt')
        self.serializd_auth = CredentialHelper('serializd')
        if use_credentials_store:
            self.trakt_auth.load()
            self.serializd_auth.load()

        self.trakt = TraktAPI()
        self.serializd = SerializdClient()
        self.migration_cache = MigrationCache()

    def main(self):
        try:
            self.trakt_login()
        except TraktError:
            self.logger.error('Failed to log in to Trakt, quitting')
            sys.exit(1)

        try:
            self.serializd_login()
        except LoginError:
            self.logger.error('Failed to log in to Serializd, quitting')
            sys.exit(1)

        self.logger.debug('Fetching user info from Trakt')
        username = self.trakt.get_user_info()['user']['username']
        self.logger.info('Fetching watched show data from Trakt')
        watched_data = self.trakt.get_watched_shows(username)

        if self.with_dates:
            self._migrate_with_dates(watched_data)
        else:
            self._migrate_without_dates(watched_data)

    def _migrate_without_dates(self, watched_data: list) -> None:
        """Original migration method - logs episodes without dates."""
        for watched_show in track(
            watched_data,
            description=f'Updating {len(watched_data)} shows...',
            total=len(watched_data)
        ):
            # Skip shows without TMDB ID
            tmdb_id = watched_show['show']['ids'].get('tmdb')
            if not tmdb_id:
                self.logger.warning(
                    'Skipping show "%s" - no TMDB ID',
                    watched_show['show']['title']
                )
                continue
            
            complete_seasons = []
            for watched_season in watched_show['seasons']:
                self.logger.info(
                    'Updating season %d of show "%s"',
                    watched_season['number'],
                    watched_show['show']['title']
                )
                self.logger.debug(
                    'Fetching season info for season %d',
                    watched_season['number']
                )
                mark_full_season = False
                try:
                    season_info = self.serializd.get_season(
                        show_id=tmdb_id,
                        season_number=watched_season['number']
                    )
                    mark_full_season = len(season_info.episodes) == len(watched_season['episodes'])
                except EmptySeasonError:
                    self.logger.warning(
                        'Serializd returned no episodes, marking entire season as watched'
                    )
                    mark_full_season = True
                except Exception as e:
                    self.logger.warning(
                        'Failed to get season info for %s S%02d: %s',
                        watched_show['show']['title'],
                        watched_season['number'],
                        str(e)
                    )
                    continue

                if mark_full_season:
                    complete_seasons.append(season_info.seasonId)
                    continue

                try:
                    self.serializd.log_episodes(
                        show_id=tmdb_id,
                        season_id=season_info.seasonId,
                        episode_numbers=[ep['number'] for ep in watched_season['episodes']]
                    )
                except Exception as e:
                    self.logger.warning(
                        'Failed to log episodes for %s S%02d: %s',
                        watched_show['show']['title'],
                        watched_season['number'],
                        str(e)
                    )

            if complete_seasons:
                try:
                    self.serializd.log_seasons(
                        show_id=tmdb_id,
                        season_ids=complete_seasons
                    )
                except Exception as e:
                    self.logger.warning(
                        'Failed to log seasons for %s: %s',
                        watched_show['show']['title'],
                        str(e)
                    )

    def _migrate_with_dates(self, watched_data: list) -> None:
        """Migration with diary dates - logs each episode individually with watch date.
        
        Supports rewatches by fetching full history from Trakt and creating
        diary entries for each watch event.
        """
        # First, get the current user info for watched status checks
        serializd_username = self._get_serializd_username()
        
        # Fetch full history from Trakt (includes rewatches)
        self.logger.info('Fetching complete watch history from Trakt...')
        history_data = self.trakt.get_full_episode_history(
            self.trakt.get_user_info()['user']['username']
        )
        
        total_shows = len(history_data)
        total_watch_events = sum(
            len(dates)
            for show_data in history_data.values()
            for season in show_data['seasons'].values()
            for dates in season.values()
        )

        cached_count = self.migration_cache.count()
        if cached_count > 0:
            self.logger.info(
                'Found %d previously migrated watch events in cache',
                cached_count
            )

        self.logger.info(
            'Processing %d watch events from %d shows',
            total_watch_events, total_shows
        )

        episode_count = 0
        skipped_count = 0
        rewatch_count = 0
        
        for show_id, show_data in history_data.items():
            show_title = show_data['show'].get('title', 'Unknown')
            
            # Check which episodes are already watched in Serializd
            watched_episodes = self._get_watched_episodes(serializd_username, show_id)

            for season_number, episodes in show_data['seasons'].items():
                self.logger.info(
                    'Processing season %s of "%s"',
                    season_number, show_title
                )

                try:
                    season_info = self.serializd.get_season(
                        show_id=show_id,
                        season_number=season_number
                    )
                except EmptySeasonError:
                    self.logger.warning(
                        'Serializd returned no episodes for season %s of "%s", skipping',
                        season_number, show_title
                    )
                    continue
                except Exception as e:
                    self.logger.warning(
                        'Failed to fetch season %s of "%s": %s, skipping',
                        season_number, show_title, str(e)
                    )
                    continue

                for episode_number, watch_dates in track(
                    episodes.items(),
                    description=f'  S{season_number:02d}...',
                    total=len(episodes)
                ):
                    # Check if this episode is already watched in Serializd
                    already_watched = (season_number, episode_number) in watched_episodes
                    
                    # Process each watch event for this episode (watch_dates are already date-only strings)
                    for i, watched_date in enumerate(watch_dates):
                        # For API call, we need full datetime format
                        watched_at = f"{watched_date}T12:00:00Z"
                        
                        # Determine if this is a rewatch:
                        # - If it's not the first watch event from Trakt history, it's a rewatch
                        # - If the episode was already watched in Serializd before this migration, it's a rewatch
                        is_rewatch = (i > 0) or already_watched
                        
                        # Skip if this specific watch event is already migrated
                        if self.migration_cache.is_migrated(
                            show_id, season_info.seasonId, episode_number, watched_date
                        ):
                            skipped_count += 1
                            continue

                        try:
                            self.serializd.log_episode_to_diary(
                                show_id=show_id,
                                season_id=season_info.seasonId,
                                episode_number=episode_number,
                                watched_at=watched_at,
                                is_rewatch=is_rewatch,
                                # Skip marking as watched if already watched in Serializd
                                mark_as_watched=not already_watched
                            )
                        except Exception as e:
                            self.logger.warning(
                                'Failed to log S%02dE%02d of "%s" (%s): %s',
                                season_number, episode_number, show_title, watched_date, str(e)
                            )
                            # Still mark as migrated to avoid retrying failed entries
                            self.migration_cache.mark_migrated(
                                show_id, season_info.seasonId, episode_number, watched_date
                            )
                            continue

                        # Mark as migrated and save periodically
                        self.migration_cache.mark_migrated(
                            show_id, season_info.seasonId, episode_number, watched_date
                        )
                        episode_count += 1
                        if is_rewatch:
                            rewatch_count += 1
                        
                        # After first successful log, episode is now watched in Serializd
                        already_watched = True

                        # Save cache every 100 episodes to prevent data loss
                        if episode_count % 100 == 0:
                            self.migration_cache.save()

        # Final save
        self.migration_cache.save()

        self.logger.info(
            'Successfully migrated %d watch events (%d rewatches), %d skipped as already in cache',
            episode_count, rewatch_count, skipped_count
        )

    def _get_serializd_username(self) -> str:
        """Get the Serializd username of the logged-in user."""
        try:
            # The token check endpoint returns user info
            token_info = self.serializd.check_token(self.serializd.access_token)
            return token_info.user.username if token_info.user else ""
        except Exception:
            return ""

    def _get_watched_episodes(self, username: str, show_id: int) -> set[tuple[int, int]]:
        """Get set of (season_number, episode_number) tuples that are watched for a show."""
        watched = set()
        try:
            progress = self.serializd.get_user_show_progress(username, show_id)
            if progress:
                for season in progress.get('watchedSeasons', []):
                    season_num = season.get('seasonNumber')
                    for ep_num in season.get('watchedEpisodes', []):
                        watched.add((season_num, ep_num))
        except Exception:
            pass
        return watched

    def trakt_login(self):
        if self.use_credentials_store:
            self.logger.debug('Loading Trakt credentials from file')
            self.trakt_auth.load()

        if not self.trakt_auth:
            self.logger.debug('Logging in to Trakt')
            self.trakt_auth.update(self.trakt.login())

        if int(time.time()) >= self.trakt_auth['created_at'] + self.trakt_auth['expires_in']:
            self.logger.debug('Refreshing saved Trakt tokens')
            self.trakt_auth.update(self.trakt.refresh_token(self.trakt_auth['refresh_token']))

        self.trakt.load_token(self.trakt_auth['access_token'])

        if self.use_credentials_store and self.trakt_auth.modified:
            self.logger.debug('Saving Trakt credentials to file')
            self.trakt_auth.save()

    def serializd_login(self):
        if self.use_credentials_store:
            self.logger.debug('Loading Serializd credentials from file')
            self.serializd_auth.load()

        if token := self.serializd_auth.get('token'):
            self.logger.debug('Checking Serializd token')
            if self.serializd.check_token(token).isValid:
                self.serializd.load_token(token, check=False)

        if not self.serializd.access_token:
            self.logger.debug('Prompting user for Serializd credentials')
            email = Prompt.ask('Enter Serializd email')
            password = Prompt.ask('Enter Serializd password (will not be echoed)', password=True)

            self.logger.debug('Logging in to Serializd')
            self.serializd.login(email=email, password=password)
            self.serializd_auth['token'] = self.serializd.access_token

        if self.use_credentials_store and self.serializd_auth.modified:
            self.logger.debug('Saving Serializd credentials to file')
            self.serializd_auth.save()
