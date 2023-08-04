from pathlib import Path

import platformdirs


def get_data_directory() -> Path:
    """Returns trakt_to_serializd data directory"""
    return platformdirs.user_data_path() / 'trakt_to_serializd'
