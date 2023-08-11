# Trakt-to-Serializd
Migrate your watched shows from Trakt to Serializd!

# Features
- Support for private Trakt accounts
- Migrate shows, seasons, and even individual episodes

Note: Due to Serializd limitations, watch dates can not be migrated.

# Usage

1. Run `trakt_to_serializd migrate` and follow the interactive instructions to log in to Trakt and Serializd.
2. Wait for the process to complete.

Note: The migration is meant to be one time process. Rerunning it will fail as it will attempt to re-add the same shows.
This case is not currently handled by the migrator.

# Stored credentials

#### Pathes
- Windows: `%localappdata%\trakt_to_serializd\credentials.json`
- Linux: `~/.local/share/trakt_to_serializd/credentials.json`

Unless you use `--no-credentials-save`, your credentials will be saved locally on your hard drive,
location dependent on your operating system. This includes only access/refresh tokens, not email and password.

To clean saved credentials, run `trakt_to_serializd clean`.

# Installation
```
pip install git+https://github.com/Velocidensity/trakt-to-serializd
```
Optionally with a virtual environment of your choice.

# Development
Development environment is managed via poetry.

```
poetry install --with=dev
```

To install pre-commit hooks, run:
```
pre-commit install
```

