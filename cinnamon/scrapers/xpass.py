import re
from typing import Optional

import requests

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from ..player import DEFAULT_UA as UA
from .base import BaseScraper, ScraperResult

TIMEOUT = 20
_BASE = "https://play.xpass.top"


def _fetch_playlist(session, player_url):
    try:
        resp = session.get(player_url, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("xpass", f"Player page request failed: {e}")
    if resp.status_code != 200:
        raise ScraperNetworkError("xpass", f"Player page returned {resp.status_code}")

    m = re.search(r'playlist["\']?\s*:\s*["\']([^"\']+)', resp.text)
    if not m:
        raise ScraperParseError("xpass", "Could not find playlist path in player page")

    path = m.group(1)
    if path.startswith("/"):
        url = _BASE + path
    else:
        url = f"{_BASE}/{path}"

    try:
        resp2 = session.get(url, timeout=TIMEOUT, headers={"Referer": _BASE + "/"})
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("xpass", f"Playlist request failed: {e}")
    if resp2.status_code != 200:
        raise ScraperNetworkError("xpass", f"Playlist returned {resp2.status_code}")

    try:
        data = resp2.json()
    except ValueError:
        raise ScraperParseError("xpass", "Non-JSON playlist response")

    sources = data.get("playlist", [{}])[0].get("sources", [])
    if not sources:
        raise ScraperNoStreamError("xpass", "No sources in playlist")

    return sources


def _verify_m3u8(session, url):
    try:
        resp = session.get(url, timeout=TIMEOUT, headers={"Referer": _BASE + "/"})
    except requests.exceptions.RequestException:
        return False
    if resp.status_code != 200:
        return False
    return resp.text.lstrip().startswith("#EXTM3U")


class XPassScraper(BaseScraper):
    name = "xpass"
    description = "HLS streams from play.xpass.top (2embed backend, no browser needed)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        media_type = episode_info.get("media_type", "tv")
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id") or episode_info.get("movie_id")
        show = episode_info.get("show", "?")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)
        quality = episode_info.get("quality", "")

        if not tmdb_id:
            raise ScraperParseError(self.name, "Missing tmdb_id/movie_id/tv_id in episode_info")

        session = requests.Session()
        session.headers.update({"User-Agent": UA})

        if media_type == "movie":
            player_url = f"{_BASE}/e/movie/{tmdb_id}"
        else:
            player_url = f"{_BASE}/e/tv/{tmdb_id}/{season}/{episode}?autostart=true"

        sources = _fetch_playlist(session, player_url)

        last_error = None
        for src in sources:
            url = src.get("file", "")
            label = src.get("label", "?")
            if not url:
                continue
            if _verify_m3u8(session, url):
                title = f"{show}" if media_type == "movie" else f"{show} S{season:02d}E{episode:02d}"
                if label:
                    title = f"{title} ({label})"
                return ScraperResult(
                    title=title,
                    m3u8_url=url,
                    referer=_BASE + "/",
                    user_agent=UA,
                )
            last_error = f"Source {label} returned invalid playlist"

        raise ScraperNoStreamError(self.name, last_error or "No playable source found")
