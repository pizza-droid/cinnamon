import re
import time as _time
from typing import Optional

import requests

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from .base import BaseScraper, ScraperResult

from ..player import DEFAULT_UA as UA
TIMEOUT = 15



def _verify_playlist(session, master_url, source):
    """Fetch the master playlist and confirm it is a real HLS playlist.

    vixsrc sometimes returns an error page (e.g. HTTP 502) instead of a
    playlist. Returning that to the player yields a silent black screen, so we
    raise ScraperNoStreamError to let the caller fall back to another source."""
    try:
        resp = session.get(master_url, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise ScraperNoStreamError(source, f"Master playlist request failed: {e}")
    if resp.status_code != 200 or not resp.text.lstrip().startswith("#EXTM3U"):
        raise ScraperNoStreamError(source, f"Master playlist unavailable (status {resp.status_code}).")
    return resp



class WebStreamScraper(BaseScraper):
    name = "webstream"
    description = "HTTP streams from vixsrc.to and vidlink.pro (no browser needed)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        media_type = episode_info.get("media_type", "tv")
        tmdb_id = episode_info.get("tv_id") or episode_info.get("tmdb_id") or episode_info.get("movie_id")
        show = episode_info.get("show", "?")
        season = episode_info.get("season", 1)
        episode = episode_info.get("episode", 1)
        quality = episode_info.get("quality", "")
        # vidlink uses a different CDN that is not throttled like vixsrc's
        # segment edge, so prefer it when downloading to avoid 503 stalls.
        prefer_vidlink = bool(episode_info.get("download"))

        if not tmdb_id:
            raise ScraperParseError(self.name, "Missing tmdb_id/movie_id/tv_id in episode_info")

        deadline = _time.time() + 30

        if media_type == "movie":
            if prefer_vidlink:
                vixsrc_fn, vidlink_fn = _try_vidlink_movie, _try_vixsrc_movie
                vixsrc_ref = f"https://vixsrc.to/embed/movie/{tmdb_id}"
            else:
                vixsrc_fn, vidlink_fn = _try_vixsrc_movie, _try_vidlink_movie
                vixsrc_ref = f"https://vixsrc.to/embed/movie/{tmdb_id}"

            if _time.time() < deadline:
                try:
                    result = vixsrc_fn(tmdb_id, quality)
                    if result:
                        label = quality.upper() if quality else "Auto"
                        return ScraperResult(
                            title=f"{show} ({label})",
                            m3u8_url=result,
                            referer=vixsrc_ref,
                            user_agent=UA,
                        )
                except ScraperNetworkError:
                    pass

            if _time.time() < deadline:
                try:
                    result = vidlink_fn(tmdb_id, quality)
                    if result:
                        label = quality.upper() if quality else "Auto"
                        return ScraperResult(
                            title=f"{show} ({label})",
                            m3u8_url=result,
                            referer="https://vidlink.pro/",
                            user_agent=UA,
                        )
                except ScraperNetworkError:
                    pass

            raise ScraperNoStreamError(self.name, f"No HTTP stream found for {show}")

        # TV
        if prefer_vidlink:
            vixsrc_fn, vidlink_fn = _try_vidlink, _try_vixsrc
            vixsrc_ref = f"https://vixsrc.to/embed/tv/{tmdb_id}/{season}/{episode}"
        else:
            vixsrc_fn, vidlink_fn = _try_vixsrc, _try_vidlink
            vixsrc_ref = f"https://vixsrc.to/embed/tv/{tmdb_id}/{season}/{episode}"

        if _time.time() < deadline:
            try:
                result = vixsrc_fn(tmdb_id, season, episode, quality)
                if result:
                    label = quality.upper() if quality else "Auto"
                    return ScraperResult(
                        title=f"{show} S{season:02d}E{episode:02d} ({label})",
                        m3u8_url=result,
                        referer=vixsrc_ref,
                        user_agent=UA,
                    )
            except ScraperNetworkError:
                pass

        if _time.time() < deadline:
            try:
                result = vidlink_fn(tmdb_id, season, episode, quality)
                if result:
                    label = quality.upper() if quality else "Auto"
                    return ScraperResult(
                        title=f"{show} S{season:02d}E{episode:02d} ({label})",
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

    api_url = f"https://vixsrc.to/api/tv/{tmdb_id}/{season}/{episode}?lang=en"
    try:
        embed_resp = session.get(api_url, timeout=TIMEOUT, headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://vixsrc.to",
        })
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("vixsrc", f"API request failed: {e}")
    if embed_resp.status_code != 200:
        raise ScraperNetworkError("vixsrc", f"API returned {embed_resp.status_code}")
    embed_src = embed_resp.json().get("src")
    if not embed_src:
        raise ScraperNetworkError("vixsrc", "No src in API response")

    full_embed = "https://vixsrc.to" + embed_src
    sep = "&" if "?" in full_embed else "?"
    full_embed += f"{sep}lang=en"
    try:
        html = session.get(full_embed, timeout=TIMEOUT, headers={
            "Accept": "text/html,application/xhtml+xml,*/*",
        }).text
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("vixsrc", f"Embed page request failed: {e}")

    token = re.search(r'token["\']\s*:\s*["\']([^"\']+)', html)
    expires = re.search(r'expires["\']\s*:\s*["\']([^"\']+)', html)
    playlist = re.search(r'url\s*:\s*["\']([^"\']+)', html)
    if not (token and expires and playlist):
        raise ScraperNetworkError("vixsrc", "Could not extract token/playlist from embed page")

    sep = "&" if "?" in playlist.group(1) else "?"
    master_url = f'{playlist.group(1)}{sep}token={token.group(1)}&expires={expires.group(1)}&h=1&lang=en'

    if not quality:
        _verify_playlist(session, master_url, "vixsrc")
        return master_url

    # Parse master playlist and filter by quality
    master_resp = _verify_playlist(session, master_url, "vixsrc")

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


def _vidlink_quality_url(data, quality=""):
    """vidlink returns direct mp4 URLs per resolution under stream.qualities."""
    qualities = data.get("stream", {}).get("qualities", {})
    if not qualities:
        raise ScraperNetworkError("vidlink", "No qualities in stream response")
    if quality and quality not in ("best", "worst"):
        target = quality.replace("p", "")
        if target in qualities:
            return qualities[target]["url"]
    if quality == "worst":
        res = min(qualities, key=lambda r: int(r))
    else:
        res = max(qualities, key=lambda r: int(r))
    return qualities[res]["url"]


def _try_vidlink(tmdb_id, season, episode, quality="") -> Optional[str]:
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

    stream_url = f"https://vidlink.pro/api/b/tv/{encoded}/{season}/{episode}?multiLang=0&audio=eng&subLang=eng"
    stream_resp = session.get(stream_url, timeout=TIMEOUT, headers={
        "Referer": "https://vidlink.pro/",
    })
    if stream_resp.status_code != 200:
        raise ScraperNetworkError("vidlink", f"Stream API returned {stream_resp.status_code}")

    try:
        data = stream_resp.json()
    except ValueError:
        raise ScraperNetworkError("vidlink", "Non-JSON response from stream API")
    return _vidlink_quality_url(data, quality)


def _try_vixsrc_movie(tmdb_id, quality="") -> Optional[str]:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    api_url = f"https://vixsrc.to/api/movie/{tmdb_id}?lang=en"
    try:
        embed_resp = session.get(api_url, timeout=TIMEOUT, headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://vixsrc.to",
        })
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("vixsrc", f"API request failed: {e}")
    if embed_resp.status_code != 200:
        raise ScraperNetworkError("vixsrc", f"API returned {embed_resp.status_code}")
    embed_src = embed_resp.json().get("src")
    if not embed_src:
        raise ScraperNetworkError("vixsrc", "No src in API response")

    full_embed = "https://vixsrc.to" + embed_src
    sep = "&" if "?" in full_embed else "?"
    full_embed += f"{sep}lang=en"
    try:
        html = session.get(full_embed, timeout=TIMEOUT, headers={
            "Accept": "text/html,application/xhtml+xml,*/*",
        }).text
    except requests.exceptions.RequestException as e:
        raise ScraperNetworkError("vixsrc", f"Embed page request failed: {e}")

    token = re.search(r'token["\']\s*:\s*["\']([^"\']+)', html)
    expires = re.search(r'expires["\']\s*:\s*["\']([^"\']+)', html)
    playlist = re.search(r'url\s*:\s*["\']([^"\']+)', html)
    if not (token and expires and playlist):
        raise ScraperNetworkError("vixsrc", "Could not extract token/playlist from embed page")

    sep = "&" if "?" in playlist.group(1) else "?"
    master_url = f'{playlist.group(1)}{sep}token={token.group(1)}&expires={expires.group(1)}&h=1&lang=en'

    if not quality:
        _verify_playlist(session, master_url, "vixsrc")
        return master_url

    master_resp = _verify_playlist(session, master_url, "vixsrc")

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


def _try_vidlink_movie(tmdb_id, quality="") -> Optional[str]:
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

    stream_url = f"https://vidlink.pro/api/b/movie/{encoded}?multiLang=0&audio=eng&subLang=eng"
    stream_resp = session.get(stream_url, timeout=TIMEOUT, headers={
        "Referer": "https://vidlink.pro/",
    })
    if stream_resp.status_code != 200:
        raise ScraperNetworkError("vidlink", f"Stream API returned {stream_resp.status_code}")

    try:
        data = stream_resp.json()
    except ValueError:
        raise ScraperNetworkError("vidlink", "Non-JSON response from stream API")
    return _vidlink_quality_url(data, quality)
