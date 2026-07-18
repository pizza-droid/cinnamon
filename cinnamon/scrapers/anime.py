import base64
import hashlib
import json
import re
import socket
import time as _time
import contextlib
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..errors import ScraperNetworkError, ScraperNoStreamError, ScraperParseError
from ..player import DEFAULT_UA as UA
from .base import BaseScraper, ScraperResult


@contextlib.contextmanager
def _force_ipv4():
    """Temporarily make getaddrinfo prefer IPv4.

    allanime's API is served behind Cloudflare which publishes AAAA (IPv6)
    records first. On hosts without working IPv6, Python's getaddrinfo can
    intermittently fail with 'Errno 11002 getaddrinfo failed', so we bias
    resolution toward IPv4 for the duration of a request.
    """
    orig = socket.getaddrinfo

    def _prefer_v4(host, port, family=socket.AF_UNSPEC, type=0, proto=0, flags=0):
        try:
            return orig(host, port, socket.AF_INET, type, proto, flags)
        except socket.gaierror:
            return orig(host, port, family, type, proto, flags)

    socket.getaddrinfo = _prefer_v4
    try:
        yield
    finally:
        socket.getaddrinfo = orig


def _new_session(ua=UA, origin="https://youtu-chan.com"):
    """Build a requests.Session with retries and IPv4-biased DNS."""
    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Origin": origin})
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

TIMEOUT = 15
API = "https://api.allanime.day/api"

# ---------------------------------------------------------------------------
# AllAnime "aaReq" crypto gate.
#
# AllAnime now protects the episode-source GraphQL query behind an AES-GCM
# signed token (aaReq) that must be sent inside the request's `extensions`
# object, otherwise the API returns `AA_CRYPTO_MISSING`. The token's epoch and
# key rotate every few days and live in the frontend's `window.__aaCrypto` plus
# the app JS chunk, so we fetch them at runtime and fall back to the last known
# good hardcoded values when that fails. The tobeparsed response is encrypted
# with the same key (or a static legacy key), so decoding tries both.
# ---------------------------------------------------------------------------

_MKISSA_URL = "https://mkissa.to/"
_CDN_IMMUTABLE = "https://cdn.allanime.day/all/mk/_app/immutable/"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Last known good values, only used when the runtime fetch fails.
# Rotated 2026-07; the runtime fetch (_aa_fetch) overrides these with live
# values from the site so the token stays valid between code updates.
_FALLBACK_EPOCH = 4130
_FALLBACK_MASK = "5264513ba898cb78c5c646bc1c12f2965a53a99891d91e83a2bf9244c36cca41"
_FALLBACK_PART_B = "nSMmjt8SIaRRj6ebdfimy1qXlUBuvMoBlPoUiSFoORg="
_FALLBACK_QUERY_HASH = "d405d0edd690624b66baba3068e0edc3ac90f1597d898a1ec8db4e5c43c00fec"
# Static legacy key AllAnime also signs tobeparsed with, depending on rotation.
_RESP_STATIC_KEY = hashlib.sha256(b"Xot36i3lK3:v1").digest()

_crypto_cache = None  # (expires_ms, epoch, key, mask, query_hash)


def _aa_key(mask_hex: str, part_b: str) -> bytes:
    return bytes(a ^ b for a, b in zip(bytes.fromhex(mask_hex), base64.b64decode(part_b)))


def _aa_source_query_hash(chunk_js: str) -> Optional[str]:
    template = next(
        (t for t in re.findall(r"`([^`]*)`", chunk_js)
         if "sourceUrls" in t and "episode(" in t),
        None,
    )
    if template is None:
        return None

    def resolve(tmpl: str, depth: int = 0) -> str:
        if depth > 6:
            return tmpl
        for name in re.findall(r"\$\{([^}]+)\}", tmpl):
            if name.endswith("()"):
                fn = re.search(
                    r"\b" + re.escape(name[:-2]) +
                    r"\s*=\s*\w+\s*=>\s*\w+\s*\?\s*`[^`]*`\s*:\s*`([^`]*)`",
                    chunk_js,
                )
                repl = fn.group(1) if fn else ""
            else:
                var = re.search(r"\b" + re.escape(name) + r"\s*=\s*`([^`]*)`", chunk_js)
                repl = resolve(var.group(1), depth + 1) if var else ""
            tmpl = tmpl.replace("${" + name + "}", repl)
        return tmpl

    query = resolve(template)
    if "${" in query:
        return None
    return hashlib.sha256(query.encode()).hexdigest()


def _aa_fetch():
    """Fetch (expires_ms, epoch, key, mask, query_hash) from the live site."""
    try:
        s = _new_session(ua=_BROWSER_UA, origin="https://mkissa.to")
        html = s.get(_MKISSA_URL, timeout=10).text
        aa = json.loads(re.search(r"window\.__aaCrypto\s*=\s*(\{.*?\})", html).group(1))
        part_b, epoch = aa["partB"], int(aa["epoch"])
        expires = max(aa.get("switchAt", 0) + aa.get("graceMs", 0),
                      _time.time() * 1000 + 3600_000)
        mask = None
        qh = _FALLBACK_QUERY_HASH

        app = re.search(r"_app/immutable/(entry/app\.[^\"']+\.js)", html)
        if app:
            app_js = s.get(_CDN_IMMUTABLE + app.group(1), timeout=10).text
            for chunk in re.findall(
                r"chunks/[A-Za-z0-9_\-]+\.js", app_js
            ):
                js = s.get(_CDN_IMMUTABLE + chunk, timeout=10).text
                if "__aaCrypto" not in js:
                    continue
                masks = re.findall(r"[0-9a-f]{64}", js)
                if len(masks) == 1:
                    mask = masks[0]
                    qh = _aa_source_query_hash(js) or _FALLBACK_QUERY_HASH
                break

        # If the mask could not be scraped, fall back to the last known good
        # mask but keep the freshly fetched epoch/partB so the token is at
        # least current (server returns STALE, not MISSING, and the next code
        # update can ship the new mask).
        if mask is None:
            mask = _FALLBACK_MASK
        return expires, epoch, _aa_key(mask, part_b), mask, qh
    except Exception:
        return None


def _aa_current() -> Tuple[int, bytes, str]:
    global _crypto_cache
    if _crypto_cache is None or _crypto_cache[0] <= _time.time() * 1000:
        fetched = _aa_fetch()
        if fetched is not None:
            _crypto_cache = fetched
    if _crypto_cache is not None:
        return _crypto_cache[1], _crypto_cache[2], _crypto_cache[4]
    return _FALLBACK_EPOCH, _aa_key(_FALLBACK_MASK, _FALLBACK_PART_B), _FALLBACK_QUERY_HASH


def _aa_build_token() -> Tuple[str, str, bytes]:
    epoch, key, query_hash = _aa_current()
    ts = int(_time.time() * 1000) // 300000 * 300000
    payload = {"v": 1, "ts": ts, "epoch": epoch, "qh": query_hash}
    iv = hashlib.sha256(f"{epoch}:{query_hash}:{ts}".encode()).digest()[:12]
    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    ciphertext, tag = cipher.encrypt_and_digest(
        json.dumps(payload, separators=(",", ":")).encode()
    )
    token = base64.b64encode(b"\x01" + iv + ciphertext + tag).decode()
    return query_hash, token, key


def _decrypt_tobeparsed(tp: str, key: bytes):
    try:
        raw = base64.b64decode(tp)
        iv, ciphertext, tag = raw[1:13], raw[13:-16], raw[-16:]
        from Crypto.Cipher import AES
        for candidate in (key, _RESP_STATIC_KEY):
            try:
                cipher = AES.new(candidate, AES.MODE_GCM, nonce=iv)
                plain = cipher.decrypt_and_verify(ciphertext, tag)
                return json.loads(plain.decode("utf-8"))
            except ValueError:
                continue
        return None
    except Exception:
        return None

_SEARCH_GQL = """query ($search: SearchInput) {
  shows(search: $search, limit: 10, page: 1, translationType: sub, countryOrigin: ALL) {
    edges { _id name availableEpisodes __typename }
  }
}"""

_EP_GQL = "query ($showId: String!) { show(_id: $showId) { _id availableEpisodesDetail } }"

_SRC_GQL = "query ($showId: String!, $translationType: VaildTranslationTypeEnumType!, $episodeString: String!) { episode(showId: $showId translationType: $translationType episodeString: $episodeString) { episodeString sourceUrls } }"

_LAST_REQUEST = 0.0

def _gql(session, query, variables):
    global _LAST_REQUEST
    elapsed = _time.time() - _LAST_REQUEST
    if elapsed < 3.5:
        _time.sleep(3.5 - elapsed)
    body = json.dumps({"variables": json.dumps(variables), "query": query}, ensure_ascii=False, separators=(",", ":"))
    try:
        with _force_ipv4():
            resp = session.post(API, data=body, timeout=TIMEOUT, headers={"Content-Type": "application/json"})
    except (requests.ConnectionError, requests.Timeout) as e:
        raise ScraperNetworkError("allanime", f"Could not reach allanime API (check your connection / DNS): {e}")
    _LAST_REQUEST = _time.time()
    if resp.status_code != 200:
        raise ScraperNetworkError("allanime", f"GraphQL returned {resp.status_code}")
    return resp.json()

def _gql_src(session, variables, query_hash=None, aa_req=None):
    global _LAST_REQUEST
    elapsed = _time.time() - _LAST_REQUEST
    if elapsed < 3.5:
        _time.sleep(3.5 - elapsed)
    if query_hash is None:
        query_hash = _FALLBACK_QUERY_HASH
    extensions = {"persistedQuery": {"version": 1, "sha256Hash": query_hash}}
    if aa_req is not None:
        extensions["aaReq"] = aa_req
    body = json.dumps(
        {"extensions": extensions, "variables": json.dumps(variables)},
        ensure_ascii=False, separators=(",", ":"),
    )
    try:
        with _force_ipv4():
            resp = session.post(API, data=body, timeout=TIMEOUT, headers={"Content-Type": "application/json"})
    except (requests.ConnectionError, requests.Timeout) as e:
        raise ScraperNetworkError("allanime", f"Could not reach allanime API (check your connection / DNS): {e}")
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
    query_hash, token, key = _aa_build_token()
    variables = {"showId": show_id, "translationType": tt, "episodeString": ep_str}
    data = _gql_src(session, variables, query_hash, token)
    if isinstance(data, dict):
        tp = data.get("data", {}).get("tobeparsed", "")
        if not tp and data.get("errors"):
            err = data["errors"][0].get("message", "unknown error") if data["errors"] else "unknown error"
            raise ScraperNetworkError("allanime", f"source query failed: {err}")
    else:
        tp = ""
    if not tp:
        raise ScraperNetworkError("allanime", "No tobeparsed data in response")
    parsed = _decrypt_tobeparsed(tp, key)
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

    q_words = frozenset(w for w in re.split(r"[^\w]+", q) if len(w) > 2)
    scored = []
    for r in results:
        rn = r.get("name", "").lower().strip()
        r_words = set(re.split(r"[^\w]+", rn))
        overlap = len(q_words & r_words)
        all_match = q_words <= r_words
        has_suffix = bool(re.search(r"\b(?:part|season|special|cour|ova|movie|film)\s*\d*\b", rn))
        extra_words = len(r_words - q_words)
        name_len = len(rn)
        scored.append((overlap, all_match, 0 if has_suffix else 1, extra_words, name_len, r["_id"]))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3], x[4]))
    return scored[0][5]

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
        session = _new_session()

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
                    label = "Dub" if translation == "dub" else "Sub"
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
