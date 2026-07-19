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
_CDN_IMMUTABLE = "https://cdn.mkissa.net/all/mk/_app/immutable/"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Last known good values, only used when the runtime fetch fails.
# Rotated 2026-07; the runtime fetch (_aa_fetch) overrides these with live
# values from the site so the token stays valid between code updates.
_FALLBACK_EPOCH = 4130
_FALLBACK_MASK = "4e600edee179ef01e61d9e322afb6418efb0ea4a33e798adcb62edc5e885423b"
_FALLBACK_PART_B = "eu1Ih9XG2JYVqkp8XDkLzBEOIOEUQwCILJLs+ifdpeA="
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


# AllAnime rotates its persisted-query hash frequently, which makes the
# sha256(persistedQuery) approach break with "PersistedQueryNotFound". The
# source-query string itself lives in the site's JS chunk, so we resolve it
# at runtime (expanding the ${...} placeholders) and send it inline. This is
# far more stable than hardcoding / scraping a rotating hash.
_SOURCE_QUERY_CACHE = None  # (expires_ms, query_string)


def _aa_source_query_string():
    global _SOURCE_QUERY_CACHE
    if _SOURCE_QUERY_CACHE is not None and _SOURCE_QUERY_CACHE[0] > _time.time() * 1000:
        return _SOURCE_QUERY_CACHE[1]
    s = _new_session(ua=_BROWSER_UA, origin="https://mkissa.to")
    try:
        html = s.get(_MKISSA_URL, timeout=10).text
        app = re.search(r"_app/immutable/(entry/app\.[^\"']+\.js)", html)
        if not app:
            raise ValueError("no app entry")
        app_js = s.get(_CDN_IMMUTABLE + app.group(1), timeout=10).text
        chunk_urls = re.findall(r"chunks/[A-Za-z0-9_\-]+\.js", app_js)
        js = ""
        for cu in chunk_urls:
            c = s.get(_CDN_IMMUTABLE + cu, timeout=10).text
            if "sourceUrls" in c:
                js = c
                break
        if not js:
            raise ValueError("no source chunk")

        def _def(name):
            fn = re.search(
                r"\b" + re.escape(name) + r"\s*=\s*\w+\s*=>\s*\w+\s*\?\s*`([^`]*)`\s*:\s*`([^`]*)`",
                js,
            )
            if fn:
                return fn.group(1)
            var = re.search(r"\b" + re.escape(name) + r"\s*=\s*`([^`]*)`", js)
            return var.group(1) if var else None

        def _resolve(t, depth=0, seen=None):
            if seen is None:
                seen = set()
            if depth > 12:
                return t
            for name in re.findall(r"\$\{([^}]+)\}", t):
                name = name.strip()
                if name in seen:
                    continue
                seen.add(name)
                repl = _def(name)
                if repl is None:
                    repl = ""
                t = t.replace("${" + name + "}", repl)
            if "${" in t:
                t = _resolve(t, depth + 1, seen)
            return t

        m = re.search(r"`([^`]*episode\([^`]*sourceUrls[^`]*)`", js)
        if not m:
            raise ValueError("no query template")
        q = _resolve(m.group(1)).strip()
        if "${" in q:
            raise ValueError("unresolved placeholders")
        _SOURCE_QUERY_CACHE = (_time.time() * 1000 + 3600_000, q)
        return q
    except Exception:
        if _SOURCE_QUERY_CACHE is not None:
            return _SOURCE_QUERY_CACHE[1]
        raise ScraperNetworkError(
            "allanime", "Could not build source query (site layout may have changed)"
        )


def _gql_src_inline(session, variables, aa_req):
    global _LAST_REQUEST
    elapsed = _time.time() - _LAST_REQUEST
    if elapsed < 3.5:
        _time.sleep(3.5 - elapsed)
    query = _aa_source_query_string()
    body = json.dumps(
        {"query": query, "variables": variables, "extensions": {"aaReq": aa_req}},
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
    token, key = _aa_build_token()[1], _aa_build_token()[2]
    variables = {"showId": show_id, "translationType": tt, "episodeString": ep_str}
    data = _gql_src_inline(session, variables, token)
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
    q_words = frozenset(w for w in re.split(r"\W+", q) if len(w) > 2)
    best_sub = None
    best_sub_diff = float("inf")
    for r in results:
        rn = r.get("name", "").lower().strip()
        r_words = set(re.split(r"\W+", rn))
        shared = q_words & r_words
        if len(shared) >= max(len(q_words) * 0.5, 1) or rn in q or q in rn:
            diff = abs(len(rn) - len(q))
            if diff < best_sub_diff:
                best_sub_diff = diff
                best_sub = r["_id"]
    if best_sub:
        return best_sub

    q_has_movie = bool(re.search(r"\b(?:movie|film)\b", q))
    q_words = frozenset(w for w in re.split(r"[^\w]+", q) if len(w) > 2)
    scored = []
    for r in results:
        rn = r.get("name", "").lower().strip()
        r_words = set(re.split(r"[^\w]+", rn))
        overlap = len(q_words & r_words)
        all_match = q_words <= r_words
        has_suffix = bool(re.search(r"\b(?:part|season|special|cour|ova|movie|film)\s*\d*\b", rn))
        if q_has_movie:
            suffix_bonus = 1 if has_suffix else 0
        else:
            suffix_bonus = 0 if has_suffix else 1
        extra_words = len(r_words - q_words)
        name_len = len(rn)
        scored.append((overlap, all_match, suffix_bonus, extra_words, name_len, r["_id"]))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3], x[4]))
    return scored[0][5]

def _extract_mp4upload(session, embed_url):
    resp = session.get(embed_url, timeout=TIMEOUT)
    if resp.status_code != 200:
        return None
    m = re.search(r'src:\s*"([^"]+)"', resp.text)
    return m.group(1) if m else None


# AllAnime encodes some source URLs as "--<hex>" provider IDs. Each hex pair
# maps through a custom table to an ASCII char; the decoded string is a
# "/apivtwo/clock?id=..." path on allanime's CDN whose /clock.json endpoint
# returns the real stream URL. (Mirrors ani-cli / anilix's provider_init.)
_LUF_HEX = {
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


def _decode_luf(hexid):
    """Decode an AllAnime '--<hex>' provider id into its clock path."""
    if len(hexid) % 2 != 0:
        return None
    out = []
    for i in range(0, len(hexid), 2):
        ch = _LUF_HEX.get(hexid[i:i + 2].lower())
        if ch is None:
            return None
        out.append(ch)
    path = "".join(out).replace("/clock", "/clock.json")
    return "https://allanime.day" + path if path.startswith("/") else path


def _clock_stream(session, clock_url):
    """Fetch an AllAnime clock.json endpoint and return the stream URL."""
    try:
        resp = session.get(
            clock_url, timeout=TIMEOUT,
            headers={"User-Agent": _BROWSER_UA, "Referer": "https://allanime.day/"},
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    ct = resp.headers.get("Content-Type", "")
    text = resp.text.strip()
    if "application/json" in ct or text.startswith("{"):
        try:
            j = resp.json()
        except ValueError:
            return text if text.startswith("http") else None
        # clock.json may return the URL directly or nested under "url"/"links".
        if isinstance(j, str):
            return j if j.startswith("http") else None
        if isinstance(j, dict):
            for k in ("url", "src", "link", "stream"):
                v = j.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return v
            links = j.get("links") or j.get("sources")
            if isinstance(links, list) and links:
                first = links[0]
                if isinstance(first, dict):
                    return first.get("url") or first.get("file")
                if isinstance(first, str):
                    return first
    # Some clocks return the bare URL as text.
    if text.startswith("http"):
        return text.split()[0]
    return None


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

        label = "Dub" if translation == "dub" else "Sub"

        # 1) mp4upload — direct .mp4, no extra hops.
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
                    return ScraperResult(
                        title=f"{show_name} E{episode:02d} ({label})",
                        m3u8_url=direct,
                        referer="https://mp4upload.com/",
                        user_agent=UA,
                    )
            except Exception:
                pass

        # 2) AllAnime's hex-encoded providers (Luf-Mp4, S-mp4, Yt-mp4, ...):
        #    decode the "--<hex>" id to a clock.json path and fetch the real URL.
        for src in sources:
            if _time.time() >= deadline:
                break
            url = src.get("sourceUrl", "")
            name = (src.get("sourceName") or "").lower()
            if not url or not url.startswith("--"):
                continue
            try:
                clock = _decode_luf(url[2:])
                if not clock:
                    continue
                stream = _clock_stream(session, clock)
                if stream:
                    referer = "https://allanime.day/"
                    if "mp4upload" in stream:
                        referer = "https://mp4upload.com/"
                    return ScraperResult(
                        title=f"{show_name} E{episode:02d} ({label}) [{name}]",
                        m3u8_url=stream,
                        referer=referer,
                        user_agent=UA,
                    )
            except Exception:
                pass

        # 3) Any other directly-playable http(s) URL (already-resolved media:
        #    .m3u8 / .mp4 / .m4v / .mkv). Embed pages are NOT playable, so we
        #    only accept URLs that end in a known media extension (or carry an
        #    HLS query). Bare provider pages (.com/e/...) are skipped so the
        #    caller can fall back to webstream instead of handing mpv a webpage.
        for src in sources:
            if _time.time() >= deadline:
                break
            url = src.get("sourceUrl", "")
            if not url or not url.startswith("http"):
                continue
            low = url.split("?")[0].lower()
            if not (low.endswith((".m3u8", ".mp4", ".m4v", ".mkv", ".mov", ".webm")) or ".m3u8" in url):
                continue
            try:
                return ScraperResult(
                    title=f"{show_name} E{episode:02d} ({label})",
                    m3u8_url=url,
                    referer="https://allanime.day/",
                    user_agent=UA,
                )
            except Exception:
                pass

        raise ScraperNoStreamError(self.name,
            f"No playable stream found for {show_name} E{episode}")
