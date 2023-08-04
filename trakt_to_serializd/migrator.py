import logging

import platformdirs
import rich
import rich.logging
import serializd

from trakt_to_serializd.trakt import TraktAPI


class Migrator:
    def __init__(self, use_credentials_store: bool = True):
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(
            level=logging.INFO,
            format='%(message)s',
            datefmt='[%X]',
            handlers=[rich.logging.RichHandler(rich_tracebacks=True)]
        )

        self.use_credentials_store = use_credentials_store
        self.credentials_store = platformdirs.user_data_path() / 'trakt_to_serializd'

    def main(self):
        pass
