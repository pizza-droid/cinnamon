from typing import Optional

import requests

from ..errors import ScraperNoStreamError, ScraperNetworkError
from ..player import DEFAULT_UA as UA
from .base import BaseScraper, ScraperResult

TORRENTIO_BASE = "https://torrentio.strem.fun"
QUALITY_ORDER = ["4k", "2160p", "1080p", "720p", "480p", "360p"]
TRACKERS = [
    "http://tracker3.itzmx.com:6961/announce",
    "http://tracker1.itzmx.com:8080/announce",
    "http://tracker.itzmx.com:6961/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
]


def _quality_from_name(name: str) -> tuple[int, str]:
    name_lower = name.lower()
    for q in QUALITY_ORDER:
        if q in name_lower:
            return (len(QUALITY_ORDER) - QUALITY_ORDER.index(q), q)
    return (0, "unknown")


def _magnet_from_info(info_hash: str, name: str = "") -> str:
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    if name:
        import urllib.parse
        magnet += f"&dn={urllib.parse.quote(name)}"
    for tr in TRACKERS:
        magnet += f"&tr={tr}"
    return magnet


class TorrentioScraper(BaseScraper):
    name = "torrentio"
    description = "Finds torrent streams via Torrentio (scrapes 1337x, TPB, RARBG, etc.)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        media_type = episode_info.get("media_type", "tv")
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id") or episode_info.get("movie_id")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)
        show_name = episode_info.get("show", "?")

        if not tmdb_id:
            from ..errors import ScraperParseError
            raise ScraperParseError(self.name, "Missing tmdb_id/movie_id/tv_id in episode_info")

        imdb_id = self._get_imdb_id(tmdb_id, media_type)
        if not imdb_id:
            raise ScraperNoStreamError(self.name,
                f"Could not find IMDb ID for TMDB ID {tmdb_id}")

        if media_type == "movie":
            streams = self._fetch_movie_streams(imdb_id)
            label = f"{show_name} (movie torrent)"
        else:
            streams = self._fetch_streams(imdb_id, season, episode)
            label = f"{show_name} S{season:02d}E{episode:02d}"

        if not streams:
            raise ScraperNoStreamError(self.name,
                f"No torrents found for {label}")

        best = max(streams, key=lambda s: _quality_from_name(s.get("name", "")))
        info_hash = best["infoHash"]
        filename = best.get("behaviorHints", {}).get("filename", "")

        magnet = _magnet_from_info(info_hash, filename)
        _, quality_label = _quality_from_name(best.get("name", ""))

        return ScraperResult(
            title=f"{label} ({quality_label} torrent)",
            m3u8_url=magnet,
        )

    def _get_imdb_id(self, tmdb_id: int, media_type: str = "tv") -> Optional[str]:
        try:
            from ..config import get_tmdb_api_key
            api_key = get_tmdb_api_key()
            headers = {"User-Agent": UA}
            tmdb_type = "movie" if media_type == "movie" else "tv"
            r = requests.get(
                f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}",
                headers=headers,
                params={"api_key": api_key, "append_to_response": "external_ids"},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            return data.get("external_ids", {}).get("imdb_id")
        except requests.RequestException:
            return None

    def _fetch_streams(self, imdb_id: str, season: int, episode: int) -> list:
        try:
            url = f"{TORRENTIO_BASE}/stream/series/{imdb_id}:{season}:{episode}.json"
            headers = {"User-Agent": UA}
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data.get("streams", [])
        except requests.RequestException as e:
            raise ScraperNetworkError(self.name, str(e))

    def _fetch_movie_streams(self, imdb_id: str) -> list:
        try:
            url = f"{TORRENTIO_BASE}/stream/movie/{imdb_id}.json"
            headers = {"User-Agent": UA}
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data.get("streams", [])
        except requests.RequestException as e:
            raise ScraperNetworkError(self.name, str(e))
