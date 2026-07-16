from typing import Optional

import requests

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from .base import BaseScraper, ScraperResult


class DirectStreamScraper(BaseScraper):
    name = "directstream"
    description = "Tries direct stream URLs from multiembed.mov and membed.net"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id")
        show = episode_info.get("show", "?")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)

        if not tmdb_id:
            raise ScraperParseError(self.name, "Missing tv_id/tmdb_id in episode_info")

        urls_to_try = [
            (
                "multiembed.mov",
                f"https://multiembed.mov/directstream.php?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}",
            ),
            (
                "membed.net",
                f"https://membed.net/directstream.php?video_id={tmdb_id}&tmdb=1&s={season}&e={episode}",
            ),
        ]

        headers_sets = [
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "*/*",
            },
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Referer": "https://multiembed.mov/",
                "Origin": "https://multiembed.mov",
            },
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Referer": "https://membed.net/",
                "Origin": "https://membed.net",
            },
        ]

        last_error = None
        for domain, url in urls_to_try:
            for headers in headers_sets:
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    text = resp.text.strip()

                    if not text or "File not found" in text or resp.status_code != 200:
                        continue

                    if resp.url != url:
                        return ScraperResult(
                            title=f"{show} S{season:02d}E{episode:02d}",
                            m3u8_url=resp.url,
                            referer=url,
                            user_agent=headers.get("User-Agent"),
                            headers={"Referer": url},
                        )

                    if text.startswith("http"):
                        return ScraperResult(
                            title=f"{show} S{season:02d}E{episode:02d}",
                            m3u8_url=text,
                            referer=url,
                            user_agent=headers.get("User-Agent"),
                            headers={"Referer": url},
                        )

                    if ".m3u8" in text:
                        import re
                        match = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', text)
                        if match:
                            return ScraperResult(
                                title=f"{show} S{season:02d}E{episode:02d}",
                                m3u8_url=match.group(1),
                                referer=url,
                                user_agent=headers.get("User-Agent"),
                                headers={"Referer": url},
                            )

                except requests.RequestException as e:
                    last_error = e
                    continue

        if last_error:
            raise ScraperNetworkError(self.name, str(last_error))
        raise ScraperNoStreamError(self.name)
