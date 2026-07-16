import time

import requests

from .config import get_tmdb_api_key
from .errors import (
    MissingAPIKey,
    TMDBAuthError,
    TMDBConnectionError,
    TMDBError,
    TMDBRateLimitError,
    TMDBNotFoundError,
    TMDBAPIError,
)

BASE_URL = "https://api.themoviedb.org/3"
MAX_RETRIES = 3
RETRY_DELAY = 2


class TMDBClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or get_tmdb_api_key()
        if not self.api_key:
            raise MissingAPIKey()

    def _request(self, path, params=None):
        params = params or {}
        params["api_key"] = self.api_key
        url = f"{BASE_URL}{path}"

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=15)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", RETRY_DELAY))
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(retry_after)
                        continue
                    raise TMDBRateLimitError(retry_after)

                if resp.status_code == 401:
                    raise TMDBAuthError()
                if resp.status_code == 404:
                    hint = path.strip("/").replace("/", " > ").title()
                    raise TMDBNotFoundError(hint)

                resp.raise_for_status()
                return resp.json()

            except TMDBError:
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
        return self._request("/search/tv", {"query": query})

    def get_tv_details(self, tv_id):
        return self._request(f"/tv/{tv_id}")

    def get_movie_details(self, movie_id):
        return self._request(f"/movie/{movie_id}")

    def get_season_details(self, tv_id, season_number):
        return self._request(f"/tv/{tv_id}/season/{season_number}")

    def get_episode_details(self, tv_id, season_number, episode_number):
        return self._request(
            f"/tv/{tv_id}/season/{season_number}/episode/{episode_number}"
        )

    def search_movie(self, query):
        return self._request("/search/movie", {"query": query})
