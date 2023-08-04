import logging
import time

import httpx

from trakt_to_serializd.consts import CLIENT_ID, CLIENT_SECRET
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

    def login(self):
        """
        Performs OAuth login using a device code

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
        resp = self.session.get(f'/users/{username}/watched/movies')
        if not resp.is_success:
            self.logger.error(f'Trakt returned status code: {resp.status_code}')
            raise TraktError(f'Trakt returned status code: {resp.status_code}')

        return resp.json()
