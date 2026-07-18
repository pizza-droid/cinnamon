import requests

from .errors import CinnamonError

API = "https://graphql.anilist.co"
UA = "cinnamon/0.1.0"

_SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 20) {
    media(search: $search, type: ANIME) {
      id
      idMal
      title { romaji english native }
      episodes
      status
      format
      startDate { year }
      genres
    }
  }
}
"""


_RELATION_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 5) {
    media(search: $search, type: ANIME) {
      id
      title { romaji english }
      relations {
        edges {
          relationType
          node {
            id
            title { romaji english }
            episodes
            status
            format
          }
        }
      }
    }
  }
}
"""


def search_anime(query):
    try:
        resp = requests.post(
            API,
            json={"query": _SEARCH_QUERY, "variables": {"search": query, "page": 1}},
            timeout=15,
            headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])
    except requests.ConnectionError:
        raise CinnamonError("Could not reach AniList. Check your internet connection.")
    except requests.Timeout:
        raise CinnamonError("AniList request timed out.")
    except requests.HTTPError as e:
        raise CinnamonError(f"AniList returned an error (HTTP {e.response.status_code}).")


def find_sequel(anime_name):
    """Search AniList for an anime and return its first SEQUEL relation, or None."""
    try:
        resp = requests.post(
            API,
            json={"query": _RELATION_QUERY, "variables": {"search": anime_name}},
            timeout=15,
            headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        media_list = data.get("data", {}).get("Page", {}).get("media", [])
        for m in media_list:
            edges = m.get("relations", {}).get("edges", [])
            for e in edges:
                if e.get("relationType") == "SEQUEL":
                    node = e.get("node", {})
                    title = node.get("title", {})
                    name = title.get("romaji") or title.get("english") or ""
                    if name:
                        return {"id": node["id"], "name": name}
        return None
    except (requests.RequestException, CinnamonError):
        return None
