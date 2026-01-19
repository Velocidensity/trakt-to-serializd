import logging
import time

import httpx

from trakt_to_serializd.consts import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI
from trakt_to_serializd.exceptions import TraktError

BASE_URL = 'https://api.trakt.tv'


class TraktAPI:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.session = httpx.Client(base_url=BASE_URL)
        self.session.headers.update({
            'Content-Type': 'application/json',
            'trakt-api-key': CLIENT_ID,
            'trakt-api-version': '2'
        })

    def load_token(self, access_token: str):
        """
        Loads saved Trakt access token

        Args:
            access_token: Trakt access token
        """
        self.session.headers['Authorization'] = f'Bearer {access_token}'

    def login(self) -> dict:
        """
        Performs OAuth login using a device code

        This is an interactive process, requiring user input

        Raises:
            TraktError: Unexpected response
        """
        code_data = self.session.post(
            '/oauth/device/code',
            json={
                'client_id': CLIENT_ID
            }
        ).json()
        self.logger.info(
            'Open %s and enter code: %s',
            code_data['verification_url'],
            code_data['user_code']
        )
        expiry = int(time.time()) + code_data['expires_in']

        auth_data = None
        while int(time.time()) < expiry:
            time.sleep(code_data['interval'])
            auth_resp = self.session.post(
                '/oauth/device/token',
                json={
                    'code': code_data['device_code'],
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET
                }
            )
            if auth_resp.status_code == 200:
                auth_data = auth_resp.json()
                break
            elif auth_resp.status_code != 400:
                self.logger.error(
                    'Login process ran into an unexpected error (status code: %02d)',
                    auth_resp.status_code
                )
                raise TraktError

        if not auth_data:
            self.logger.error('Login process timed out, please retry.')
            raise TraktError

        self.session.headers['Authorization'] = f'Bearer {auth_data["access_token"]}'
        return auth_data

    def refresh_token(self, refresh_token: str) -> dict:
        """
        Refreshes user authorization using a refresh token

        Args:
            refresh_token: Trakt refresh token

        Raises:
            TraktError: Unexpected response
        """
        resp = self.session.post(
            '/oauth/token',
            json={
                'refresh_token': refresh_token,
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'redirect_uri': REDIRECT_URI,
                'grant_type': 'refresh_token'
            }
        )
        if not resp.is_success:
            self.logger.error(f'Trakt returned status code: {resp.status_code}')
            self.logger.debug(resp.text)
            raise TraktError(f'Trakt returned status code: {resp.status_code}')

        auth_data = resp.json()
        self.session.headers['Authorization'] = f'Bearer {auth_data["access_token"]}'
        return auth_data

    def get_user_info(self) -> dict:
        """
        Fetches user information for the currently logged in user

        Requires authorization.

        Returns:
            dict: User in formation

        Raises:
            TraktError: Unexpected response
        """
        resp = self.session.get('/users/settings')
        if not resp.is_success:
            self.logger.error(f'Trakt returned status code: {resp.status_code}')
            raise TraktError(f'Trakt returned status code: {resp.status_code}')

        return resp.json()

    def get_watched_shows(self, username: str) -> dict:
        """
        Fetches watched shows for a given user

        Args:
            username: Trakt username

        Returns:
            dict: Watched show data

        Raises:
            TraktError: Unexpected response
        """
        resp = self.session.get(f'/users/{username}/watched/shows')
        if not resp.is_success:
            self.logger.error(f'Trakt returned status code: {resp.status_code}')
            raise TraktError(f'Trakt returned status code: {resp.status_code}')

        return resp.json()

    def get_episode_history(self, username: str, show_id: int | None = None, limit: int = 10000) -> list:
        """
        Fetches episode watch history for a user, including rewatches.
        
        Each watch event is returned separately, so if an episode was watched
        3 times, it appears 3 times with different watched_at timestamps.

        Args:
            username: Trakt username
            show_id: Optional TMDB show ID to filter by
            limit: Maximum number of history entries to return

        Returns:
            list: List of history entries with episode and watched_at data

        Raises:
            TraktError: Unexpected response
        """
        url = f'/users/{username}/history/episodes'
        params = {'limit': limit}
        
        resp = self.session.get(url, params=params)
        if not resp.is_success:
            self.logger.error(f'Trakt returned status code: {resp.status_code}')
            raise TraktError(f'Trakt returned status code: {resp.status_code}')

        history = resp.json()
        
        # Filter by show if specified
        if show_id:
            history = [h for h in history if h.get('show', {}).get('ids', {}).get('tmdb') == show_id]
        
        return history

    def get_full_episode_history(self, username: str) -> dict:
        """
        Fetches complete episode watch history and organizes it by show/season/episode.
        
        Returns data structure compatible with the migrator, but with multiple
        watch events per episode for rewatch support.

        Args:
            username: Trakt username

        Returns:
            dict: Organized watch data with all watch events per episode
                  Structure: {show_id: {season_num: {ep_num: [watched_at_dates]}}}

        Raises:
            TraktError: Unexpected response
        """
        self.logger.info('Fetching full episode history from Trakt (this may take a while)...')
        
        all_history = []
        page = 1
        per_page = 1000
        
        while True:
            resp = self.session.get(
                f'/users/{username}/history/episodes',
                params={'page': page, 'limit': per_page}
            )
            if not resp.is_success:
                self.logger.error(f'Trakt returned status code: {resp.status_code}')
                raise TraktError(f'Trakt returned status code: {resp.status_code}')
            
            batch = resp.json()
            if not batch:
                break
                
            all_history.extend(batch)
            self.logger.info(f'Fetched {len(all_history)} history entries...')
            
            # Check if there are more pages
            total_pages = int(resp.headers.get('x-pagination-page-count', 1))
            if page >= total_pages:
                break
            page += 1
        
        self.logger.info(f'Total: {len(all_history)} watch events')
        
        # Organize by show -> season -> episode -> list of watch dates
        # Use a set to deduplicate identical timestamps (sync issues)
        organized = {}
        for entry in all_history:
            show = entry.get('show', {})
            episode = entry.get('episode', {})
            watched_at = entry.get('watched_at')
            
            show_id = show.get('ids', {}).get('tmdb')
            season_num = episode.get('season')
            episode_num = episode.get('number')
            
            if not all([show_id, season_num is not None, episode_num, watched_at]):
                continue
            
            if show_id not in organized:
                organized[show_id] = {
                    'show': show,
                    'seasons': {}
                }
            
            if season_num not in organized[show_id]['seasons']:
                organized[show_id]['seasons'][season_num] = {}
            
            if episode_num not in organized[show_id]['seasons'][season_num]:
                organized[show_id]['seasons'][season_num][episode_num] = set()
            
            # Extract date part only (YYYY-MM-DD) to dedupe same-day rewatches
            date_part = watched_at[:10] if len(watched_at) >= 10 else watched_at
            organized[show_id]['seasons'][season_num][episode_num].add(date_part)
        
        # Convert sets to sorted lists
        for show_id in organized:
            for season_num in organized[show_id]['seasons']:
                for episode_num in organized[show_id]['seasons'][season_num]:
                    organized[show_id]['seasons'][season_num][episode_num] = sorted(
                        organized[show_id]['seasons'][season_num][episode_num]
                    )
        
        return organized
