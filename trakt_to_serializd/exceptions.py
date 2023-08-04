class MigratorError(Exception):
    """Main exception class"""

    def __init__(self, message: str | None = None):
        self.message = message

    def __str__(self) -> str:
        return self.message or ''


class TraktError(MigratorError):
    """Trakt error exception"""
    pass
