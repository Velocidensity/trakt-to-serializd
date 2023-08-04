# Trakt-to-Serializd
Migrate your watched shows from Trakt to Serializd!

# Usage

1. Run `trakt_to_serializd` and follow the interactive guide to log in to Serializd, and optionally Trakt.
2. Wait for the process to complete.

Unless you use `--no-credentials-save`, your credentials will be saved locally on your hard drive,
location dependent on your operating system.

- Windows: `%localappdata%\trakt_to_serializd\credentials.json`
- Linux: `~/.local/share/trakt_to_serializd/credentials.json`

Note: The migration is meant to be one time process. No issues should arise from rerunning it,
but a successful result is not guaranteed.

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

