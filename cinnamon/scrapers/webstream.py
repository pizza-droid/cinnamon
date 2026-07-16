import re
import time as _time
from typing import Optional

import requests

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from .base import BaseScraper, ScraperResult

from ..player import DEFAULT_UA as UA
TIMEOUT = 15


class WebStreamScraper(BaseScraper):
    name = "webstream"
    description = "HTTP streams from vixsrc.to and vidlink.pro (no browser needed)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id")
        show = episode_info.get("show", "?")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)
        quality = episode_info.get("quality", "")

        if not tmdb_id:
            raise ScraperParseError(self.name, "Missing tv_id/tmdb_id in episode_info")

        deadline = _time.time() + 30

        # Try vixsrc.to first
        if _time.time() < deadline:
            try:
                result = _try_vixsrc(tmdb_id, season, episode, quality)
                if result:
                    label = quality.upper() if quality else "vixsrc"
                    return ScraperResult(
                        title=f"{show} S{season:02d}E{episode:02d} ({label})",
                        m3u8_url=result,
                        referer=f"https://vixsrc.to/embed/tv/{tmdb_id}/{season}/{episode}",
                        user_agent=UA,
                    )
            except ScraperNetworkError:
                pass

        # Try vidlink.pro as fallback
        if _time.time() < deadline:
            try:
                result = _try_vidlink(tmdb_id, season, episode)
                if result:
                    return ScraperResult(
                        title=f"{show} S{season:02d}E{episode:02d} (vidlink)",
                        m3u8_url=result,
                        referer="https://vidlink.pro/",
                        user_agent=UA,
                    )
            except ScraperNetworkError:
                pass

        raise ScraperNoStreamError(self.name,
            f"No HTTP stream found for {show} S{season:02d}E{episode:02d}")


_QUALITY_RENDITIONS = {"480p": "480p", "720p": "720p", "1080p": "1080p", "best": "", "worst": "worst"}

def _try_vixsrc(tmdb_id, season, episode, quality="") -> Optional[str]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    api_url = f"https://vixsrc.to/api/tv/{tmdb_id}/{season}/{episode}"
    embed_resp = session.get(api_url, timeout=TIMEOUT, headers={
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://vixsrc.to",
    })
    if embed_resp.status_code != 200:
        raise ScraperNetworkError("vixsrc", f"API returned {embed_resp.status_code}")
    embed_src = embed_resp.json().get("src")
    if not embed_src:
        raise ScraperNetworkError("vixsrc", "No src in API response")

    full_embed = "https://vixsrc.to" + embed_src
    html = session.get(full_embed, timeout=TIMEOUT, headers={
        "Accept": "text/html,application/xhtml+xml,*/*",
    }).text

    token = re.search(r'token["\']\s*:\s*["\']([^"\']+)', html)
    expires = re.search(r'expires["\']\s*:\s*["\']([^"\']+)', html)
    playlist = re.search(r'url\s*:\s*["\']([^"\']+)', html)
    if not (token and expires and playlist):
        raise ScraperNetworkError("vixsrc", "Could not extract token/playlist from embed page")

    sep = "&" if "?" in playlist.group(1) else "?"
    master_url = f'{playlist.group(1)}{sep}token={token.group(1)}&expires={expires.group(1)}&h=1'

    if not quality:
        return master_url

    # Parse master playlist and filter by quality
    master_resp = session.get(master_url, timeout=TIMEOUT)
    if master_resp.status_code != 200:
        return master_url

    variants = re.findall(
        r'#EXT-X-STREAM-INF:.*?RESOLUTION=\d+x(\d+).*?\n(https?://\S+)',
        master_resp.text,
    )
    if not variants:
        return master_url

    target = quality.replace("p", "")
    if quality == "best":
        match = max(variants, key=lambda v: int(v[0]))
    elif quality == "worst":
        match = min(variants, key=lambda v: int(v[0]))
    else:
        matches = [v for v in variants if v[0] == target]
        match = matches[0] if matches else max(variants, key=lambda v: int(v[0]))

    return match[1]


def _try_vidlink(tmdb_id, season, episode) -> Optional[str]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    enc = session.get(
        f"https://enc-dec.app/api/enc-vidlink?text={tmdb_id}",
        timeout=TIMEOUT,
    )
    if enc.status_code != 200:
        raise ScraperNetworkError("vidlink", f"Encryption API returned {enc.status_code}")
    try:
        encoded = enc.json().get("result")
    except ValueError:
        raise ScraperNetworkError("vidlink", "Non-JSON response from encryption API")
    if not encoded:
        raise ScraperNetworkError("vidlink", "No encrypted ID from API")

    stream_url = f"https://vidlink.pro/api/b/tv/{encoded}/{season}/{episode}?multiLang=0"
    stream_resp = session.get(stream_url, timeout=TIMEOUT, headers={
        "Referer": "https://vidlink.pro/",
    })
    if stream_resp.status_code != 200:
        raise ScraperNetworkError("vidlink", f"Stream API returned {stream_resp.status_code}")

    try:
        data = stream_resp.json()
    except ValueError:
        raise ScraperNetworkError("vidlink", "Non-JSON response from stream API")
    playlist = data.get("stream", {}).get("playlist")
    if not playlist:
        raise ScraperNetworkError("vidlink", "No playlist in stream response")

    return playlist
