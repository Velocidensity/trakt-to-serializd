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
