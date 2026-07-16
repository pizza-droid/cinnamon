from typing import Optional


class CinnamonError(Exception):
    """Base for all cinnamon errors."""


class ConfigError(CinnamonError):
    """Configuration issues."""


class MissingAPIKey(ConfigError):
    def __init__(self):
        super().__init__("TMDB API key not configured.")


class InvalidConfig(ConfigError):
    def __init__(self, msg=""):
        super().__init__(msg or "Configuration file is invalid.")


class TMDBError(CinnamonError):
    """Base for TMDB API errors."""

    def __init__(self, message, status_code=None, details=None):
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class TMDBConnectionError(TMDBError):
    def __init__(self, cause=None):
        msg = "Could not connect to TMDB. Check your internet connection."
        if cause:
            msg = f"{msg}\n  Details: {cause}"
        super().__init__(msg)


class TMDBAuthError(TMDBError):
    def __init__(self):
        super().__init__(
            "Your TMDB API key is invalid or has been revoked.\n"
            "  Run [bold]cinnamon setup[/bold] to update it.",
            status_code=401,
        )


class TMDBRateLimitError(TMDBError):
    def __init__(self, retry_after=2):
        self.retry_after = retry_after
        super().__init__(
            f"TMDB rate limit hit. Auto-retrying in {retry_after}s...",
            status_code=429,
        )


class TMDBNotFoundError(TMDBError):
    def __init__(self, resource):
        super().__init__(
            f"{resource} not found on TMDB. The ID may be wrong or removed.",
            status_code=404,
        )


class TMDBAPIError(TMDBError):
    def __init__(self, status_code, message=""):
        super().__init__(
            message or f"TMDB API returned error {status_code}.",
            status_code=status_code,
        )


class ScraperError(CinnamonError):
    """Base for scraper errors."""


class ScraperNotFoundError(ScraperError):
    def __init__(self, name, available=None):
        msg = f"Scraper [bold]{name}[/bold] not found."
        if available:
            msg += f"\n  Available: {', '.join(available)}"
        super().__init__(msg)


class ScraperNetworkError(ScraperError):
    def __init__(self, scraper, cause=None):
        msg = f"Network error in scraper [bold]{scraper}[/bold]."
        if cause:
            msg += f"\n  Details: {cause}"
        super().__init__(msg)


class ScraperAuthError(ScraperError):
    def __init__(self, scraper):
        super().__init__(
            f"Scraper [bold]{scraper}[/bold] requires authentication.\n"
            f"  Configure it via [bold]cinnamon config scraper {scraper} --key ...[/bold]"
        )


class ScraperRateLimitError(ScraperError):
    def __init__(self, scraper, retry_after=None):
        msg = f"Scraper [bold]{scraper}[/bold] is rate-limited."
        if retry_after:
            msg += f" Retry in {retry_after}s."
        super().__init__(msg)


class ScraperParseError(ScraperError):
    def __init__(self, scraper, cause=None):
        msg = f"Failed to parse response from scraper [bold]{scraper}[/bold]."
        if cause:
            msg += f"\n  Details: {cause}"
        super().__init__(msg)


class ScraperNoStreamError(ScraperError):
    def __init__(self, scraper, message=None):
        super().__init__(
            message or f"Scraper [bold]{scraper}[/bold] found no streams for this episode."
        )


class PlayerError(CinnamonError):
    """Base for player errors."""


class PlayerNotFoundError(PlayerError):
    def __init__(self, player="auto"):
        msg = (
            f"No media player found."
        )
        if player in ("mpv", "auto"):
            msg += "\n  Install mpv: https://mpv.io"
        if player in ("vlc", "auto"):
            msg += "\n  Install VLC: https://videolan.org"
        super().__init__(msg)


class PlayerLaunchError(PlayerError):
    def __init__(self, player, cause=None):
        msg = f"Failed to launch [bold]{player}[/bold]."
        if cause:
            msg += f"\n  Details: {cause}"
        super().__init__(msg)
