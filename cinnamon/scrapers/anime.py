import json
import re
import time as _time
from typing import Optional

import requests

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from ..player import DEFAULT_UA as UA
from .base import BaseScraper, ScraperResult

TIMEOUT = 15
API = "https://api.allanime.day/api"

_ALLANIME_KEY = None

def _get_key():
    global _ALLANIME_KEY
    if not _ALLANIME_KEY:
        import hashlib
        _ALLANIME_KEY = hashlib.sha256(b"Xot36i3lK3:v1").digest()
    return _ALLANIME_KEY

_HEX_MAP = {
    "79": "A", "7a": "B", "7b": "C", "7c": "D", "7d": "E", "7e": "F", "7f": "G",
    "70": "H", "71": "I", "72": "J", "73": "K", "74": "L", "75": "M", "76": "N",
    "77": "O", "68": "P", "69": "Q", "6a": "R", "6b": "S", "6c": "T", "6d": "U",
    "6e": "V", "6f": "W", "60": "X", "61": "Y", "62": "Z",
    "59": "a", "5a": "b", "5b": "c", "5c": "d", "5d": "e", "5e": "f", "5f": "g",
    "50": "h", "51": "i", "52": "j", "53": "k", "54": "l", "55": "m", "56": "n",
    "57": "o", "48": "p", "49": "q", "4a": "r", "4b": "s", "4c": "t", "4d": "u",
    "4e": "v", "4f": "w", "40": "x", "41": "y", "42": "z",
    "08": "0", "09": "1", "0a": "2", "0b": "3", "0c": "4", "0d": "5", "0e": "6",
    "0f": "7", "00": "8", "01": "9",
    "15": "-", "16": ".", "67": "_", "46": "~", "02": ":", "17": "/", "07": "?",
    "1b": "#", "63": "[", "65": "]", "78": "@", "19": "!", "1c": "$", "1e": "&",
    "10": "(", "11": ")", "12": "*", "13": "+", "14": ",", "03": ";", "05": "=",
    "1d": "%",
}

def _decode_custom_hex(encoded):
    out = []
    for i in range(0, len(encoded), 2):
        out.append(_HEX_MAP.get(encoded[i:i+2], "?"))
    return "".join(out)

def _decrypt_tobeparsed(tp):
    try:
        from Crypto.Cipher import AES

        raw = __import__("base64").b64decode(tp)
        iv, ct = raw[1:13], raw[13:-16]
        ctr_iv = iv + b"\x00\x00\x00\x02"
        cipher = AES.new(_get_key(), AES.MODE_CTR, nonce=b"", initial_value=ctr_iv)
        return json.loads(cipher.decrypt(ct).decode("utf-8"))
    except Exception:
        return None

_SEARCH_GQL = """query ($search: SearchInput) {
  shows(search: $search, limit: 10, page: 1, translationType: sub, countryOrigin: ALL) {
    edges { _id name availableEpisodes __typename }
  }
}"""

_EP_GQL = "query ($showId: String!) { show(_id: $showId) { _id availableEpisodesDetail } }"

_SRC_GQL = "query ($showId: String!, $translationType: VaildTranslationTypeEnumType!, $episodeString: String!) { episode(showId: $showId translationType: $translationType episodeString: $episodeString) { episodeString sourceUrls } }"

_QUERY_HASH = "d405d0edd690624b66baba3068e0edc3ac90f1597d898a1ec8db4e5c43c00fec"

_LAST_REQUEST = 0.0

def _gql(session, query, variables):
    global _LAST_REQUEST
    elapsed = _time.time() - _LAST_REQUEST
    if elapsed < 3.5:
        _time.sleep(3.5 - elapsed)
    body = json.dumps({"variables": json.dumps(variables), "query": query}, ensure_ascii=False, separators=(",", ":"))
    resp = session.post(API, data=body, timeout=TIMEOUT, headers={"Content-Type": "application/json"})
    _LAST_REQUEST = _time.time()
    if resp.status_code != 200:
        raise ScraperNetworkError("allanime", f"GraphQL returned {resp.status_code}")
    return resp.json()

def _gql_src(session, variables):
    global _LAST_REQUEST
    elapsed = _time.time() - _LAST_REQUEST
    if elapsed < 3.5:
        _time.sleep(3.5 - elapsed)
    body = json.dumps({"extensions": {"persistedQuery": {"version": 1, "sha256Hash": _QUERY_HASH}}, "variables": json.dumps(variables)}, ensure_ascii=False, separators=(",", ":"))
    resp = session.post(API, data=body, timeout=TIMEOUT, headers={"Content-Type": "application/json"})
    _LAST_REQUEST = _time.time()
    if resp.status_code != 200:
        raise ScraperNetworkError("allanime", f"Source GQL returned {resp.status_code}")
    return resp.json()

def _allanime_search(session, query):
    data = _gql(session, _SEARCH_GQL, {"search": {"allowAdult": False, "allowUnknown": False, "query": query}})
    return data.get("data", {}).get("shows", {}).get("edges", [])

def _allanime_episodes(session, show_id):
    data = _gql(session, _EP_GQL, {"showId": show_id})
    return data.get("data", {}).get("show", {}).get("availableEpisodesDetail", {})

def _allanime_sources(session, show_id, ep_str, tt="sub"):
    data = _gql_src(session, {"showId": show_id, "translationType": tt, "episodeString": ep_str})
    tp = data.get("data", {}).get("tobeparsed", "") if isinstance(data, dict) else ""
    if not tp:
        raise ScraperNetworkError("allanime", "No tobeparsed data in response")
    parsed = _decrypt_tobeparsed(tp)
    if not parsed:
        raise ScraperNoStreamError("allanime", "Failed to decrypt stream sources (source format may have changed)")
    episode = parsed.get("episode")
    if not isinstance(episode, dict):
        raise ScraperNoStreamError("allanime", "No stream data for this episode (source may be unavailable)")
    return episode.get("sourceUrls", [])

def _find_show(session, name):
    results = _allanime_search(session, name)
    if not results:
        return None
    q = name.lower().strip()
    for r in results:
        rn = r.get("name", "").lower().strip()
        if q == rn:
            return r["_id"]
    for r in results:
        rn = r.get("name", "").lower().strip()
        if q in rn or rn in q:
            return r["_id"]
    return results[0]["_id"]

def _extract_mp4upload(session, embed_url):
    resp = session.get(embed_url, timeout=TIMEOUT)
    if resp.status_code != 200:
        return None
    m = re.search(r'src:\s*"([^"]+)"', resp.text)
    return m.group(1) if m else None


class AnimeScraper(BaseScraper):
    name = "anime"
    description = "Anime streams from allanime.day via mp4upload (no browser needed)"

    def search(self, query):
        return []

    def resolve(self, episode_info):
        show_name = episode_info.get("show", "")
        episode = episode_info.get("episode", 1)
        quality = episode_info.get("quality", "")
        translation = episode_info.get("translation", "sub")

        if not show_name:
            raise ScraperParseError(self.name, "Missing show name in episode_info")

        deadline = _time.time() + 30
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Origin": "https://youtu-chan.com"})

        if _time.time() >= deadline:
            raise ScraperNoStreamError(self.name, "Timeout searching allanime")
        show_id = _find_show(session, show_name)
        if not show_id:
            raise ScraperNoStreamError(self.name, f'No allanime match for "{show_name}"')

        if _time.time() >= deadline:
            raise ScraperNoStreamError(self.name, "Timeout fetching sources")
        sources = _allanime_sources(session, show_id, str(episode), translation)

        if not sources:
            raise ScraperNoStreamError(self.name, f"No sources for episode {episode}")

        for src in sources:
            if _time.time() >= deadline:
                break
            url = src.get("sourceUrl", "")
            if not url or "mp4upload" not in url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            try:
                direct = _extract_mp4upload(session, url)
                if direct:
                    label = quality.upper() if quality else "Mp4upload"
                    return ScraperResult(
                        title=f"{show_name} E{episode:02d} ({label})",
                        m3u8_url=direct,
                        referer="https://mp4upload.com/",
                        user_agent=UA,
                    )
            except Exception:
                pass

        raise ScraperNoStreamError(self.name,
            f"No playable stream found for {show_name} E{episode}")
