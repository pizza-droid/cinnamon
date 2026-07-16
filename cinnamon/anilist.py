import requests

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


def search_anime(query):
    resp = requests.post(
        API,
        json={"query": _SEARCH_QUERY, "variables": {"search": query, "page": 1}},
        timeout=15,
        headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("Page", {}).get("media", [])
