import re

import requests

from ..errors import ScraperNetworkError, ScraperParseError, ScraperNoStreamError
from .base import BaseScraper, ScraperResult


class ExampleScraper(BaseScraper):
    name = "example"
    description = "Example scraper (placeholder - replace with real source)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        show = episode_info.get("show", "")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)

        url = f"https://example.com/watch/{show}/s{season:02d}e{episode:02d}"

        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
        except requests.ConnectionError as e:
            raise ScraperNetworkError(self.name, f"Failed to connect to {url}: {e}")
        except requests.Timeout as e:
            raise ScraperNetworkError(self.name, f"Timed out: {e}")
        except requests.HTTPError as e:
            if resp.status_code == 403:
                raise ScraperAuthError(self.name)
            elif resp.status_code == 429:
                raise ScraperRateLimitError(self.name)
            raise ScraperNetworkError(self.name, f"HTTP {resp.status_code}")

        try:
            match = re.search(r'(https?://[^"\']+\.m3u8[^"\']*)', resp.text)
        except re.error as e:
            raise ScraperParseError(self.name, str(e))

        if not match:
            raise ScraperNoStreamError(self.name)

        return ScraperResult(
            title=f"{show} S{season:02d}E{episode:02d}",
            m3u8_url=match.group(1),
            referer=url,
        )
