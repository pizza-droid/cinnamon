import time

import requests

from .errors import (
    TMDBConnectionError,
    TMDBError,
    TMDBNotFoundError,
    TMDBAPIError,
)

BASE_URL = "https://api.2embed.cc"
MAX_RETRIES = 3
RETRY_DELAY = 2

_COUNTRY_FULL_TO_CODE = {
    "Japan": "JP",
    "United States of America": "US",
    "United States": "US",
    "South Korea": "KR",
    "China": "CN",
    "United Kingdom": "GB",
    "France": "FR",
    "Germany": "DE",
    "Italy": "IT",
    "Spain": "ES",
    "Canada": "CA",
    "Australia": "AU",
    "India": "IN",
    "Brazil": "BR",
    "Mexico": "MX",
    "Russia": "RU",
    "Taiwan": "TW",
    "Hong Kong": "HK",
    "Thailand": "TH",
    "Philippines": "PH",
    "Indonesia": "ID",
    "Malaysia": "MY",
    "Vietnam": "VN",
    "Sweden": "SE",
    "Norway": "NO",
    "Denmark": "DK",
    "Finland": "FI",
    "Netherlands": "NL",
    "Belgium": "BE",
    "Switzerland": "CH",
    "Austria": "AT",
    "Poland": "PL",
    "Turkey": "TR",
    "Argentina": "AR",
    "Chile": "CL",
    "Colombia": "CO",
    "New Zealand": "NZ",
    "Ireland": "IE",
    "Portugal": "PT",
    "Czech Republic": "CZ",
}

_LANG_FULL_TO_CODE = {
    "Japanese": "ja",
    "English": "en",
    "Korean": "ko",
    "Chinese": "zh",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Spanish": "es",
    "Portuguese": "pt",
    "Russian": "ru",
    "Arabic": "ar",
    "Hindi": "hi",
    "Bengali": "bn",
    "Turkish": "tr",
    "Dutch": "nl",
    "Polish": "pl",
    "Swedish": "sv",
    "Danish": "da",
    "Finnish": "fi",
    "Norwegian": "no",
    "Czech": "cs",
    "Thai": "th",
    "Vietnamese": "vi",
    "Indonesian": "id",
    "Malay": "ms",
    "Tagalog": "tl",
    "Romanian": "ro",
    "Hungarian": "hu",
    "Greek": "el",
    "Hebrew": "he",
}


def _normalize_country(val):
    if isinstance(val, list):
        return [_COUNTRY_FULL_TO_CODE.get(c, c) for c in val]
    if isinstance(val, str):
        return _COUNTRY_FULL_TO_CODE.get(val, val)
    return val


def _normalize_language(val):
    return _LANG_FULL_TO_CODE.get(val, val)


def _normalize_search_result(item, media_type="tv"):
    item["_media_type"] = media_type
    if media_type == "tv":
        item["id"] = item.get("tmdb_id")
        item["_media_type"] = "tv"
    else:
        item["id"] = item.get("tmdb_id")
        item["_media_type"] = "movie"
    if "origin_country" in item:
        item["origin_country"] = _normalize_country(item["origin_country"])
    if "original_language" in item:
        item["original_language"] = _normalize_language(item["original_language"])
    return item


class EmbedClient:
    def __init__(self, api_key=None):
        pass

    def _request(self, path, params=None):
        params = params or {}
        url = f"{BASE_URL}{path}"

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=15)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", RETRY_DELAY))
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(retry_after)
                        continue
                    raise TMDBError(f"2embed rate limit hit. Retry in {retry_after}s.", status_code=429)

                if resp.status_code == 404:
                    hint = path.strip("/").replace("/", " > ").title()
                    raise TMDBNotFoundError(hint)

                if resp.status_code == 400:
                    body = resp.text[:200]
                    raise TMDBNotFoundError(f"2embed: {body}")

                resp.raise_for_status()
                return resp.json()

            except (TMDBError, TMDBNotFoundError):
                raise
            except requests.ConnectionError as e:
                if attempt == MAX_RETRIES - 1:
                    raise TMDBConnectionError(str(e))
                time.sleep(RETRY_DELAY)
            except requests.Timeout as e:
                if attempt == MAX_RETRIES - 1:
                    raise TMDBConnectionError(f"Request timed out: {e}")
                time.sleep(RETRY_DELAY)
            except requests.HTTPError as e:
                raise TMDBAPIError(resp.status_code, str(e))

    def search_tv(self, query):
        data = self._request("/searchtv", {"q": query, "page": 1})
        results = [_normalize_search_result(r, "tv") for r in data.get("results", [])]
        return {"results": results}

    def search_movie(self, query):
        data = self._request("/search", {"q": query, "page": 1})
        results = [_normalize_search_result(r, "movie") for r in data.get("results", [])]
        return {"results": results}

    def get_tv_details(self, tv_id):
        data = self._request("/tv", {"tmdb_id": tv_id})
        if "origin_country" in data:
            data["origin_country"] = _normalize_country(data["origin_country"])
        if "original_language" in data:
            data["original_language"] = _normalize_language(data["original_language"])
        seasons = data.get("seasons", [])
        real_seasons = [s for s in seasons if s.get("season_number", 0) > 0]
        data["number_of_seasons"] = len(real_seasons)
        return data

    def get_season_details(self, tv_id, season_number):
        return self._request("/season", {"tmdb_id": tv_id, "season": season_number})

    def get_episode_details(self, tv_id, season_number, episode_number):
        season_data = self.get_season_details(tv_id, season_number)
        for ep in season_data.get("episodes", []):
            if ep.get("episode_number") == episode_number:
                return ep
        raise TMDBNotFoundError(f"Episode S{season_number}E{episode_number}")

    def get_movie_details(self, movie_id):
        data = self._request("/movie", {"tmdb_id": movie_id})
        if "original_language" in data:
            data["original_language"] = _normalize_language(data["original_language"])
        return data
