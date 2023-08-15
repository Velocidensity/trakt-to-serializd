import json
from collections import UserDict
from typing import Any

import platformdirs


class CredentialHelper(UserDict):
    directory = platformdirs.user_data_path() / 'trakt_to_serializd'

    def __init__(self, name: str):
        self.path = self.directory / f'{name}.json'
        self.data = {}
        self.saved_data: dict[str, Any] = {}

    def load(self):
        """Loads credential data from file"""
        self._create()
        try:
            with self.path.open(mode='r', encoding='utf-8') as f:
                self.data.update(json.load(f))
                self.saved_data = self.data.copy()
            self.saved_data = self.data.copy()
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            pass

    def save(self):
        """Saves credential data to file"""
        with self.path.open(mode='w', encoding='utf-8') as f:
            json.dump(self.data, f)
        self.saved_data = self.data.copy()

    def clear(self):
        """Clears credential data"""
        self.data = {}
        self.save()

    def remove(self):
        """Removes credential folder and file"""
        self.path.unlink(missing_ok=True)

    @classmethod
    def remove_folder(cls):
        """Removes credential directory"""
        if cls.directory.exists():
            cls.directory.rmdir()

    @property
    def modified(self) -> bool:
        """Modification status since last load/save"""
        return self.data != self.saved_data

    def _create(self):
        """Creates credential folder and file"""
        if not self.path.exists():
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text("{}")
